!> \file f2py_config_store.f90
!> \copydoc f2py_config_store

!> \brief Intrinsic-only f2py wrappers for the derived-type store.
module f2py_config_store
  use iso_c_binding, only: c_intptr_t
  use iso_fortran_env, only: i4=>int32
  use config_store, only: &
    get_config_handle, &
    get_period_item_start, &
    get_period_start, &
    get_station_code, &
    get_station_label, &
    reset_config

  implicit none

contains

  subroutine run_get_handle_wrapper(handle)
    integer(c_intptr_t), intent(out) :: handle

    call get_config_handle(handle)
  end subroutine run_get_handle_wrapper

  subroutine run_reset_wrapper(status, errmsg)
    integer, intent(out) :: status
    character(len=512), intent(out) :: errmsg

    call reset_config(status, errmsg)
  end subroutine run_reset_wrapper

  subroutine run_get_period_start_wrapper(value)
    integer(i4), intent(out) :: value

    call get_period_start(value)
  end subroutine run_get_period_start_wrapper

  subroutine run_get_period_item_start_wrapper(index, value)
    integer, intent(in) :: index
    integer(i4), intent(out) :: value

    call get_period_item_start(index, value)
  end subroutine run_get_period_item_start_wrapper

  subroutine run_get_station_code_wrapper(value)
    integer(i4), intent(out) :: value

    call get_station_code(value)
  end subroutine run_get_station_code_wrapper

  subroutine run_get_station_label_wrapper(value)
    character(len=24), intent(out) :: value

    call get_station_label(value)
  end subroutine run_get_station_label_wrapper

end module f2py_config_store
