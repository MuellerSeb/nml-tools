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

  subroutine get_config_handle(handle)
    integer(c_intptr_t), intent(out) :: handle
    type(c_ptr) :: ptr

    ptr = c_loc(config)
    handle = transfer(ptr, handle)
  end subroutine get_config_handle

  subroutine reset_config(status, errmsg)
    integer, intent(out) :: status
    character(len=512), intent(out) :: errmsg

    status = config%init(errmsg=errmsg)
  end subroutine reset_config

  subroutine get_iterations(value)
    integer, intent(out) :: value

    value = config%iterations
  end subroutine get_iterations

  subroutine get_tolerance(value)
    real(dp), intent(out) :: value

    value = config%tolerance
  end subroutine get_tolerance

  subroutine get_weight(index, value)
    integer, intent(in) :: index
    real(dp), intent(out) :: value

    value = config%weights(index)
  end subroutine get_weight

  subroutine get_enabled(value)
    logical, intent(out) :: value

    value = config%enabled
  end subroutine get_enabled

  subroutine print_config()
    write(*, '(a, i0)') 'iterations = ', config%iterations
    write(*, '(a, es12.5)') 'tolerance = ', config%tolerance
    write(*, '(a, l1)') 'enabled = ', config%enabled
    write(*, '(a, 3(es12.5, 1x))') 'weights = ', config%weights
  end subroutine print_config

end module config_store
