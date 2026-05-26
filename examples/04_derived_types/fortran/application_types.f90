!> \file application_types.f90
!> \copydoc application_types

!> \brief Maintainer-owned types used by the derived-type example.
module application_types
  use iso_fortran_env, only: i4=>int32

  implicit none

  private
  public :: station_t

  !> \brief Application-owned station storage.
  !> \details The label is longer than the eight-character schema contract.
  type :: station_t
    integer(i4) :: code
    character(len=24) :: label
  end type station_t

end module application_types
