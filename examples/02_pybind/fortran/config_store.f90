!> \file config_store.f90
!> \copydoc config_store

!> \brief Persistent Fortran configuration store for the pybind example
!> \details This module owns the target namelist instance used by the Python
!! binding example. It exposes a small Fortran API for obtaining an opaque
!! handle and checking values after Python-side configuration.
module config_store
  use iso_c_binding, only: c_intptr_t, c_loc, c_ptr
  use iso_fortran_env, only: dp=>real64
  use nml_config, only: nml_config_t

  implicit none

  private
  public :: get_config_handle
  public :: reset_config
  public :: get_iterations
  public :: get_tolerance
  public :: get_weight
  public :: get_enabled
  public :: print_config

  type(nml_config_t), target, save :: config

contains

  !> \brief Return an opaque integer handle to the persistent config instance
  subroutine get_config_handle(handle)
    integer(c_intptr_t), intent(out) :: handle !< integer representation of the config address
    type(c_ptr) :: ptr

    ptr = c_loc(config)
    handle = transfer(ptr, handle)
  end subroutine get_config_handle

  !> \brief Reset the persistent config instance to defaults and sentinels
  subroutine reset_config(status, errmsg)
    integer, intent(out) :: status !< nml-tools status code
    character(len=512), intent(out) :: errmsg !< error message for non-OK status values

    status = config%init(errmsg=errmsg)
  end subroutine reset_config

  !> \brief Return the configured iteration count
  subroutine get_iterations(value)
    integer, intent(out) :: value !< current iteration count

    value = config%iterations
  end subroutine get_iterations

  !> \brief Return the configured tolerance
  subroutine get_tolerance(value)
    real(dp), intent(out) :: value !< current tolerance

    value = config%tolerance
  end subroutine get_tolerance

  !> \brief Return one configured weight
  subroutine get_weight(index, value)
    integer, intent(in) :: index !< one-based weight index
    real(dp), intent(out) :: value !< current weight value

    value = config%weights(index)
  end subroutine get_weight

  !> \brief Return the configured enabled flag
  subroutine get_enabled(value)
    logical, intent(out) :: value !< current enabled flag

    value = config%enabled
  end subroutine get_enabled

  !> \brief Print the persistent config instance
  subroutine print_config()
    write(*, '(a, i0)') 'iterations = ', config%iterations
    write(*, '(a, es12.5)') 'tolerance = ', config%tolerance
    write(*, '(a, l1)') 'enabled = ', config%enabled
    write(*, '(a, 3(es12.5, 1x))') 'weights = ', config%weights
  end subroutine print_config

end module config_store
