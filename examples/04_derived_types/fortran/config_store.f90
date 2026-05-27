!> \file config_store.f90
!> \copydoc config_store

!> \brief Persistent Fortran configuration store for the derived-type example.
module config_store
  use iso_c_binding, only: c_intptr_t, c_loc, c_ptr
  use iso_fortran_env, only: i4=>int32
  use nml_run, only: nml_run_t

  implicit none

  private
  public :: get_config_handle
  public :: reset_config
  public :: get_period_start
  public :: get_period_item_start
  public :: get_station_code
  public :: get_station_label

  type(nml_run_t), target, save :: config

contains

  subroutine get_config_handle(handle)
    integer(c_intptr_t), intent(out) :: handle
    type(c_ptr) :: ptr

    ptr = c_loc(config)
    handle = transfer(ptr, 0_c_intptr_t)
  end subroutine get_config_handle

  subroutine reset_config(status, errmsg)
    integer, intent(out) :: status
    character(len=512), intent(out) :: errmsg

    status = config%init(errmsg=errmsg)
  end subroutine reset_config

  subroutine get_period_start(value)
    integer(i4), intent(out) :: value

    value = config%period%start_year
  end subroutine get_period_start

  subroutine get_period_item_start(index, value)
    integer, intent(in) :: index
    integer(i4), intent(out) :: value

    value = config%periods(index)%start_year
  end subroutine get_period_item_start

  subroutine get_station_code(value)
    integer(i4), intent(out) :: value

    value = config%station%code
  end subroutine get_station_code

  subroutine get_station_label(value)
    character(len=24), intent(out) :: value

    value = config%station%label
  end subroutine get_station_label

end module config_store
