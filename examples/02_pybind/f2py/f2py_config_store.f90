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

  subroutine config_get_handle_wrapper(handle)
    integer(c_intptr_t), intent(out) :: handle

    call get_config_handle(handle)
  end subroutine config_get_handle_wrapper

  subroutine config_reset_wrapper(status, errmsg)
    integer, intent(out) :: status
    character(len=512), intent(out) :: errmsg

    call reset_config(status, errmsg)
  end subroutine config_reset_wrapper

  subroutine config_get_iterations_wrapper(value)
    integer, intent(out) :: value

    call get_iterations(value)
  end subroutine config_get_iterations_wrapper

  subroutine config_get_tolerance_wrapper(value)
    real(dp), intent(out) :: value

    call get_tolerance(value)
  end subroutine config_get_tolerance_wrapper

  subroutine config_get_weight_wrapper(index, value)
    integer, intent(in) :: index
    real(dp), intent(out) :: value

    call get_weight(index, value)
  end subroutine config_get_weight_wrapper

  subroutine config_get_enabled_wrapper(value)
    logical, intent(out) :: value

    call get_enabled(value)
  end subroutine config_get_enabled_wrapper

  subroutine config_print_wrapper()
    call print_config()
  end subroutine config_print_wrapper

end module f2py_config_store
