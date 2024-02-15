# !/usr/bin/env python3
# -*- coding: utf-8 -*-

from femdb.NLFEMDataBase import NLFEMDataBase
from element.ElementBase import ElementBaseClass
from femdb.ElementGroup import ElementGroup
from femdb.Plasticity import PlasticDeformationState
from utils.GlobalEnum import *
from femdb.Material import *
import numpy as np

"""
Single instance mode, convenient for programming, Connect Database
"""
fem_db = NLFEMDataBase()
KINEMATICS = fem_db.kinematics
dim = GetDomainDimension()
element_indexi = fem_db.global_k.indexi
element_indexj = fem_db.global_k.indexj
element_stiffness = fem_db.global_k.stiffness
IDENTITY_TENSOR = fem_db.identity_tensor
MESH = fem_db.Mesh


def ElementForceAndStiffness(xlocal, Xlocal, mat_id, Ve,
                             ele: ElementBaseClass,
                             grp: ElementGroup,
                             ele_idx: int):
    """
    #TODO: 所谓的Voigt格式在哪里体现
    Computes the element vector of global internal forces and the tangent
    stiffness matrix.
    @return:
    """
    grp_ele_info = grp.element_info
    T_internal = np.zeros((grp_ele_info.n_dofs_elem, 1))
    KINEMATICS.ComputeGradients(xlocal, Xlocal, grp.interpolation.element_DN_chi)
    mat = fem_db.Material.Mat[mat_id]

    """
    Computes element mean dilatation kinematics, pressure and bulk modulus.
    """
    if isinstance(mat, HyperElasticPlasticInPrincipal):
        DN_x_mean = np.zeros((GetDomainDimension(), grp_ele_info.n_nodes_elem))
        ve = 0
        for ii in range(grp_ele_info.ngauss):
            """
            Gauss contribution to the elemental deformed volume.
            Elemental averaged shape functions.
            """
            JW = KINEMATICS.Jx_chi[ii] * grp.quadrature.element_w[ii]
            ve += JW
            DN_x_mean += grp.interpolation.element_DN_chi[:, :, ii] * JW
        DN_x_mean = DN_x_mean / ve
        Jbar = ve / Ve

        """
        Computes element mean dilatation pressure and bulk modulus.
        """
        if isinstance(mat, HyperElasticPlasticInPrincipal):
            kappa = mat.value_dict[MaterialKey.Kappa]
            press = kappa * np.log(Jbar) / Jbar
            kappa_bar = kappa / Jbar - press
        else:
            kappa_bar = 0
            press = 0

    else:
        raise NoImplSuchMaterial(mat.GetName())

    """
    Gauss quadrature integration loop. Extract kinematics at the particular Gauss point.
    Obtain stresses (for incompressible or nearly incompressible, 
    only deviatoric component) and internal variables in plasticity.
    Obtain elasticity tensor (for incompressible or nearly incompressible, 
    only deviatoric component).
    """
    if isinstance(mat, HyperElasticPlasticInPrincipal):
        PLAST_element = PlasticDeformationState()
        PLAST_element.epbar = grp.global_plasticity.epbar[:, ele_idx]
        PLAST_element.invCp = grp.global_plasticity.invCp[:, :, :, ele_idx]
    else:
        raise NoImplSuchMaterial(mat.GetName())

    from constitutive_laws.CauchyTypeSelection import CauchyTypeSelection
    from constitutive_laws.ElasticityModulus import ElasticityModulusSelection
    for igauss in range(grp_ele_info.ngauss):
        Cauchy, PLAST_gauss = CauchyTypeSelection(PLAST_element, igauss, mat)
        c = ElasticityModulusSelection(PLAST_element, PLAST_gauss, igauss, mat_id)

        """
        Add pressure contribution to stresses and elasticity tensor.
        """
        Cauchy = Cauchy + press * IDENTITY_TENSOR.I
        c = c + press * (IDENTITY_TENSOR.c1 - IDENTITY_TENSOR.c2)

        """
        Compute numerical integration multipliers, Computes the thickness in the deformed 
        configuration for plane stress problems.
        """
        JW = KINEMATICS.Jx_chi[igauss] * grp.interpolation.quadrature.element_w[igauss]

        """
        Compute equivalent (internal) force vector.
        """
        T = np.matmul(Cauchy, KINEMATICS.DN_Dx[:, :, igauss])
        T_internal += T.T.reshape(T.size, 1)

        """
        Compute contribution (and extract relevant information for subsequent
        assembly) of the constitutive term of the stiffness matrix.
        """
        from element_calculation.ConstitutiveMatrix import ConstitutiveMatrix
        ConstitutiveMatrix(grp, ele, igauss, c, JW)

        """
        Compute contribution (and extract relevant information for subsequent
        assembly) of the geometric term of the stiffness matrix.
        """
        DN_sigma_DN = np.matmul(KINEMATICS.DN_Dx[:, :, igauss].T, np.matmul(Cauchy, KINEMATICS.DN_Dx[:, :, igauss]))

        from element_calculation.GeometricMatrix import GeometricMatrix
        GeometricMatrix(grp, ele, DN_sigma_DN, JW)

    """
    Compute contribution (and extract relevant information for subsequent
    assembly) of the mean dilatation term (Kk) of the stiffness matrix.
    """
    counter = fem_db.global_k.counter
    if isinstance(mat, HyperElasticPlasticInPrincipal):
        for bnode in range(grp_ele_info.n_nodes_elem):
            for anode in range(grp_ele_info.n_nodes_elem):
                DN_x_meana_DN_x_meanb = np.outer(DN_x_mean[:, anode], DN_x_mean[:, bnode])

                indexi = MESH.dof_nodes[:, ele.node_ids[anode] - 1]
                indexi = np.tile(indexi, (1, dim))

                indexj = MESH.dof_nodes[:, ele.node_ids[bnode] - 1]
                indexj = np.tile(indexj, (1, dim))
                indexj = indexj.T

                # Index for row identification.
                element_indexi[counter:counter + dim ** 2, 0] = indexi.flatten()

                # Index for column identification.
                element_indexj[counter:counter + dim ** 2, 0] = indexj.flatten()

                # Mean dilatation stiffness matrix contribution.
                element_stiffness[counter:counter + dim ** 2, 0] = kappa_bar * ve * DN_x_meana_DN_x_meanb.flatten()

                counter += dim ** 2

    return T_internal, PLAST_element
