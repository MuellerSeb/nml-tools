!> \file f2py_config_store.f90
!> \copydoc f2py_config_store
!>
!> \brief f2py wrappers for the example configuration store.
!> \details This module exposes only intrinsic dummy arguments so f2py can build
!! a package-local extension.  It forwards calls to the Fortran store module,
!! which owns the persistent namelist instance.
module f2py_config_store
  use iso_c_binding, only: c_intptr_t
  use iso_fortran_env, only: dp=>real64
  use config_store, only: &
    get_config_handle, &
    get_enabled, &
    get_iterations, &
    get_tolerance, &
    get_weight, &
    print_config, &
    reset_config

  implicit none

contains

  !> \brief Return the opaque handle for the persistent config instance.
  subroutine config_get_handle_wrapper(handle)
    integer(c_intptr_t), intent(out) :: handle !< integer address handle for the Fortran target instance

    call get_config_handle(handle)
  end subroutine config_get_handle_wrapper

  !> \brief Reset the persistent config instance to generated defaults.
  subroutine config_reset_wrapper(status, errmsg)
    integer, intent(out) :: status !< nml-tools status code
    character(len=512), intent(out) :: errmsg !< error message for non-OK status values

    call reset_config(status, errmsg)
  end subroutine config_reset_wrapper

  !> \brief Return the configured iteration count.
  subroutine config_get_iterations_wrapper(value)
    integer, intent(out) :: value !< current iteration count

    call get_iterations(value)
  end subroutine config_get_iterations_wrapper

  !> \brief Return the configured tolerance.
  subroutine config_get_tolerance_wrapper(value)
    real(dp), intent(out) :: value !< current tolerance value

    call get_tolerance(value)
  end subroutine config_get_tolerance_wrapper

  !> \brief Return one configured weight value.
  subroutine config_get_weight_wrapper(index, value)
    integer, intent(in) :: index !< one-based weight index
    real(dp), intent(out) :: value !< weight value at the requested index

    call get_weight(index, value)
  end subroutine config_get_weight_wrapper

  !> \brief Return whether the example configuration is enabled.
  subroutine config_get_enabled_wrapper(value)
    logical, intent(out) :: value !< current enabled flag

    call get_enabled(value)
  end subroutine config_get_enabled_wrapper

  !> \brief Print the persistent config instance through the Fortran store.
  subroutine config_print_wrapper()
    call print_config()
  end subroutine config_print_wrapper

end module f2py_config_store
