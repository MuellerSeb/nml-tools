!> \file nml_helper.f90
!> \copydoc nml_helper

!> \brief Helper module for namelist file operations
module nml_helper
  ! kind specifiers used by locally generated derived types
  use iso_fortran_env, only: &
    i4=>int32

  !> \brief Buffer length for reading lines
  integer, public :: nml_line_buffer = 512
  !> \brief Status code: success
  integer, parameter, public :: NML_OK = 0
  !> \brief Status code: file not found
  integer, parameter, public :: NML_ERR_FILE_NOT_FOUND = 1
  !> \brief Status code: failed to open file
  integer, parameter, public :: NML_ERR_OPEN = 2
  !> \brief Status code: file not open
  integer, parameter, public :: NML_ERR_NOT_OPEN = 3
  !> \brief Status code: namelist not found
  integer, parameter, public :: NML_ERR_NML_NOT_FOUND = 4
  !> \brief Status code: read error
  integer, parameter, public :: NML_ERR_READ = 5
  !> \brief Status code: close error
  integer, parameter, public :: NML_ERR_CLOSE = 6
  !> \brief Status code: required value missing
  integer, parameter, public :: NML_ERR_REQUIRED = 10
  !> \brief Status code: enum validation failed
  integer, parameter, public :: NML_ERR_ENUM = 11
  !> \brief Status code: value not set
  integer, parameter, public :: NML_ERR_NOT_SET = 12
  !> \brief Status code: array partially set
  integer, parameter, public :: NML_ERR_PARTLY_SET = 13
  !> \brief Status code: bounds validation failed
  integer, parameter, public :: NML_ERR_BOUNDS = 14
  !> \brief Status code: invalid field name
  integer, parameter, public :: NML_ERR_INVALID_NAME = 20
  !> \brief Status code: invalid index
  integer, parameter, public :: NML_ERR_INVALID_INDEX = 21
  !> \brief Status code: zero opaque handle
  integer, parameter, public :: NML_ERR_INVALID_HANDLE = 22

  !> \brief Shared constants for generated namelist modules
  integer, parameter, public :: period_label_len = 12 !< Storage length of labels on locally generated periods.
  integer, parameter, public :: station_label_len = 8 !< Mapped station label length; imported application storage must match.
  integer, parameter, public :: n_periods__dim_default = 2 !< Default number of configured periods.

  !> \class period_t
  !> \brief Simulation period
  !> \details Start and end years for a configured time window.
  type, public :: period_t
    integer(i4) :: start_year !< Start year
    integer(i4) :: end_year !< End year
    character(len=period_label_len) :: label !< Period label
  end type period_t

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
  integer function nml_open(this, file, errmsg) result(nml__status)
    class(nml_file_t), intent(inout) :: this
    character(len=*), intent(in) :: file
    character(len=*), intent(out), optional :: errmsg
    integer :: nml__iostat
    logical :: nml__exists
    character(len=nml_line_buffer) :: nml__iomsg
    if (present(errmsg)) errmsg = ""
    nml__status = this%close()
    inquire(file=file, exist=nml__exists)
    if (.not. nml__exists) then
      this%is_open = .false.
      this%unit = 0
      nml__status = NML_ERR_FILE_NOT_FOUND
      if (present(errmsg)) errmsg = "file not found: " // trim(file)
      return
    end if
    open(newunit=this%unit, file=file, status='old', action='read', &
      iostat=nml__iostat, iomsg=nml__iomsg)
    this%is_open = (nml__iostat == 0)
    if (.not. this%is_open) then
      this%unit = 0
      nml__status = NML_ERR_OPEN
      if (present(errmsg)) errmsg = trim(nml__iomsg)
      return
    end if
    nml__status = NML_OK
  end function nml_open

  !> \brief Find a namelist in the opened file
  integer function nml_find(this, nml, errmsg) result(nml__status)
    class(nml_file_t), intent(inout) :: this
    character(len=*), intent(in) :: nml
    character(len=*), intent(out), optional :: errmsg
    integer :: nml__iostat
    character(len=nml_line_buffer) :: nml__line
    character(len=nml_line_buffer) :: nml__iomsg
    if (present(errmsg)) errmsg = ""
    nml__status = NML_ERR_NML_NOT_FOUND
    if (.not. this%is_open) then
      nml__status = NML_ERR_NOT_OPEN
      if (present(errmsg)) errmsg = "file not open"
      return
    end if
    rewind(unit=this%unit)
    do
      read(this%unit, '(A)', iostat=nml__iostat, iomsg=nml__iomsg) nml__line
      if (nml__iostat < 0) exit
      if (nml__iostat > 0) then
        nml__status = NML_ERR_READ
        if (present(errmsg)) errmsg = trim(nml__iomsg)
        return
      end if
      if (index(to__lower(nml__line), '&' // to__lower(trim(nml))) /= 0) then
        nml__status = NML_OK
        backspace(this%unit)
        return
      end if
    end do
    if (present(errmsg)) errmsg = "namelist not found: " // trim(nml)
  end function nml_find

  !> \brief Close the namelist file
  integer function nml_close(this, errmsg) result(nml__status)
    class(nml_file_t), intent(inout) :: this
    character(len=*), intent(out), optional :: errmsg
    integer :: nml__iostat
    character(len=nml_line_buffer) :: nml__iomsg
    if (present(errmsg)) errmsg = ""
    nml__status = NML_OK
    if (this%is_open) then
      close(unit=this%unit, iostat=nml__iostat, iomsg=nml__iomsg)
      if (nml__iostat /= 0) then
        nml__status = NML_ERR_CLOSE
        if (present(errmsg)) errmsg = trim(nml__iomsg)
      end if
    end if
    this%is_open = .false.
    this%unit = 0
  end function nml_close

  !> \brief Convert string to lower case
  pure function to__lower(nml__string) result(nml__lower_string)
    character(len=*), intent(in) :: nml__string
    character(len=len(nml__string)) :: nml__lower_string
    integer, parameter :: nml__shift=iachar('a')-iachar('A'), nml__upA=iachar('A'), nml__upZ=iachar('Z')
    integer :: nml__k, nml__i
    do nml__i = 1, len(nml__string)
      nml__k = ichar(nml__string(nml__i:nml__i))
      if (nml__k>=nml__upA .and. nml__k<=nml__upZ) nml__k = nml__k + nml__shift
      nml__lower_string(nml__i:nml__i) = char(nml__k)
    end do
  end function to__lower

  !> \brief Validate index bounds for array access
  integer function idx__check(nml__idx, nml__extents, nml__field, errmsg) result(nml__status)
    integer, intent(in) :: nml__idx(:)
    integer, intent(in) :: nml__extents(:)
    character(len=*), intent(in) :: nml__field
    character(len=*), intent(out), optional :: errmsg

    nml__status = NML_OK
    if (present(errmsg)) errmsg = ""
    if (size(nml__idx) /= size(nml__extents)) then
      nml__status = NML_ERR_INVALID_INDEX
      if (present(errmsg)) errmsg = "index rank mismatch for '" // trim(nml__field) // "'"
    else if (any(nml__idx < 1) .or. any(nml__idx > nml__extents)) then
      nml__status = NML_ERR_INVALID_INDEX
      if (present(errmsg)) errmsg = "index out of bounds for '" // trim(nml__field) // "'"
    end if
  end function idx__check

end module nml_helper
