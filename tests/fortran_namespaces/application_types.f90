module application_types
  implicit none

  type :: status
    integer :: code
  end type status

  type :: c_ptr
    integer :: code
  end type c_ptr
end module application_types
