!> \brief Helper module for namelist file operations
module nml_helper

  !> \brief Buffer length for reading lines
  integer, public :: len_buf = 1024

  !> \class nml_file_t
  !> \brief Type for namelist file operations
  type, public :: nml_file_t
    integer :: unit = 0
    logical :: is_open = .false.
  contains
    procedure :: open => nml_open
    procedure :: find => nml_find
    procedure :: close => nml_close
  end type nml_file_t

contains

  !> \brief Open a namelist file
  subroutine nml_open(this, file)
    class(nml_file_t), intent(inout) :: this
    character(len=*), intent(in) :: file
    integer :: iostat
    call this%close()
    open(newunit=this%unit, file=file, status='old', action='read', iostat=iostat)
    this%is_open = (iostat == 0)
    if (.not.this%is_open) this%unit = 0
  end subroutine nml_open

  !> \brief Find a namelist in the opened file
  function nml_find(this, nml) result(found)
    class(nml_file_t), intent(inout) :: this
    character(len=*), intent(in) :: nml
    logical :: found
    integer :: iostat
    character(len=len_buf) :: line
    found = .false.
    if (.not. this%is_open) return
    rewind(unit=this%unit)
    do
      read(this%unit, *, iostat=iostat) line
      if (iostat /= 0) exit
      if (index(to_lower(line), '&' // to_lower(trim(nml))) /= 0) then
        found = .true.
        backspace(this%unit)
        exit
      end if
    end do
  end function nml_find

  !> \brief Close the namelist file
  subroutine nml_close(this)
    class(nml_file_t), intent(inout) :: this
    if (this%is_open) close(unit=this%unit)
    this%is_open = .false.
    this%unit = 0
  end subroutine nml_close

  !> \brief Convert string to lower case
  pure function to_lower(string) result(lower_string)
    character(len=*), intent(in) :: string
    character(len=len(string)) :: lower_string
    integer, parameter :: shift=iachar('a')-iachar('A'), upA=iachar('A'), upZ=iachar('Z')
    integer :: k, i
    do i = 1, len(string)
      k = ichar(string(i:i))
      if (k>=upA .and. k<=upZ) k = k + shift
      lower_string(i:i) = char(k)
    end do
  end function to_lower

end module nml_helper
