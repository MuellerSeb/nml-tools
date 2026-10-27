!> \file nml_optional.f90
!> \copydoc nml_optional

!> \brief Optional generated reader
!> \details Optional generated reader
module nml_optional
  use nml_helper, only: &
    nml_file_t, &
    nml_line_buffer, &
    NML_OK, &
    NML_ERR_FILE_NOT_FOUND, &
    NML_ERR_OPEN, &
    NML_ERR_NOT_OPEN, &
    NML_ERR_NML_NOT_FOUND, &
    NML_ERR_READ, &
    NML_ERR_CLOSE, &
    NML_ERR_REQUIRED, &
    NML_ERR_ENUM, &
    NML_ERR_BOUNDS, &
    NML_ERR_NOT_SET, &
    NML_ERR_INVALID_NAME, &
    NML_ERR_INVALID_INDEX, &
    idx_check, &
    to_lower
  ! kind specifiers listed in the nml-tools configuration file
  use iso_fortran_env, only: &
    i4=>int32

  implicit none

  ! default values
  integer(i4), parameter, public :: count__default = 7_i4

  !> \class nml_optional_t
  !> \brief Optional generated reader
  !> \details Optional generated reader
  type, public :: nml_optional_t
    logical :: is_configured = .false. !< whether the namelist has been configured
    integer(i4) :: count !< count
    character(len=16) :: label !< label
  contains
    procedure :: init => nml_optional_init
    procedure :: from_file => nml_optional_from_file
    procedure :: set => nml_optional_set
    procedure :: is_set => nml_optional_is_set
    procedure :: is_valid => nml_optional_is_valid
  end type nml_optional_t

contains

  !> \brief Initialize defaults and sentinels for optional
  integer function nml_optional_init(this, errmsg) result(status)
    class(nml_optional_t), intent(inout) :: this !< namelist instance
    character(len=*), intent(out), optional :: errmsg !< error message for non-OK status values

    status = NML_OK
    if (present(errmsg)) errmsg = ""
    this%is_configured = .false.

    ! sentinel values for required/optional parameters
    this%label = achar(0) ! sentinel for optional string
    ! default values
    this%count = count__default
  end function nml_optional_init


  !> \brief Read optional namelist from file
  integer function nml_optional_from_file(this, file, errmsg) result(status)
    class(nml_optional_t), intent(inout) :: this !< namelist instance
    character(len=*), intent(in) :: file !< path to namelist file
    character(len=*), intent(out), optional :: errmsg !< error message for non-OK status values
    ! namelist variables
    integer(i4) :: count
    character(len=16) :: label
    ! locals
    type(nml_file_t) :: nml
    integer :: iostat
    integer :: close_status
    character(len=nml_line_buffer) :: iomsg

    namelist /optional/ &
      count, &
      label

    status = this%init(errmsg=errmsg)
    if (status /= NML_OK) return
    count = this%count
    label = this%label

    status = nml%open(file, errmsg=errmsg)
    if (status /= NML_OK) return

    status = nml%find("optional", errmsg=errmsg)
    if (status /= NML_OK) then
      if (status == NML_ERR_NML_NOT_FOUND) then
        close_status = nml%close(errmsg=errmsg)
        if (close_status /= NML_OK) then
          status = close_status
          return
        end if
        this%is_configured = .true.
        status = NML_OK
        return
      end if
      close_status = nml%close()
      return
    end if

    ! read namelist
    read(nml%unit, nml=optional, iostat=iostat, iomsg=iomsg)
    if (iostat /= 0) then
      status = NML_ERR_READ
      if (present(errmsg)) errmsg = trim(iomsg)
      close_status = nml%close()
      return
    end if
    close_status = nml%close(errmsg=errmsg)
    if (close_status /= NML_OK) then
      status = close_status
      return
    end if

    ! assign values
    this%count = count
    this%label = label

    ! mark as configured
    this%is_configured = .true.
    status = NML_OK
  end function nml_optional_from_file

  !> \brief Set optional values
  integer function nml_optional_set(this, &
    count, &
    label, &
    errmsg) result(status)

    class(nml_optional_t), intent(inout) :: this !< namelist instance
    character(len=*), intent(out), optional :: errmsg !< error message for non-OK status values
    integer(i4), intent(in), optional :: count !< count
    character(len=*), intent(in), optional :: label !< label

    status = this%init(errmsg=errmsg)
    if (status /= NML_OK) return

    ! required parameters
    ! override with provided values
    if (present(count)) this%count = count
    if (present(label)) this%label = label

    ! mark as configured
    this%is_configured = .true.
    status = NML_OK
  end function nml_optional_set

  !> \brief Check whether a namelist value was set
  integer function nml_optional_is_set(this, name, idx, errmsg) result(status)
    class(nml_optional_t), intent(in) :: this !< namelist instance
    character(len=*), intent(in) :: name !< field name
    integer, intent(in), optional :: idx(:) !< optional field index values
    character(len=*), intent(out), optional :: errmsg !< error message for non-OK status values

    status = NML_OK
    if (present(errmsg)) errmsg = ""
    if (.not. this%is_configured) then
      status = NML_ERR_NOT_SET
      if (present(errmsg)) errmsg = "namelist not configured; call set or from_file"
      return
    end if
    select case (to_lower(trim(name)))
    case ("count")
      if (present(idx)) then
        status = NML_ERR_INVALID_INDEX
        if (present(errmsg)) errmsg = "index not supported for 'count'"
        return
      end if
    case ("label")
      if (present(idx)) then
        status = NML_ERR_INVALID_INDEX
        if (present(errmsg)) errmsg = "index not supported for 'label'"
        return
      end if
      if (this%label == achar(0)) status = NML_ERR_NOT_SET
    case default
      status = NML_ERR_INVALID_NAME
      if (present(errmsg)) errmsg = "unknown field: " // trim(name)
    end select
    if (status == NML_ERR_NOT_SET .and. present(errmsg)) then
      if (len_trim(errmsg) == 0) errmsg = "field not set: " // trim(name)
    end if
  end function nml_optional_is_set

  !> \brief Validate required values and constraints
  integer function nml_optional_is_valid(this, errmsg) result(status)
    class(nml_optional_t), intent(in) :: this !< namelist instance
    character(len=*), intent(out), optional :: errmsg !< error message for non-OK status values
    integer :: istat

    status = NML_OK
    if (present(errmsg)) errmsg = ""
    if (.not. this%is_configured) then
      status = NML_ERR_NOT_SET
      if (present(errmsg)) errmsg = "namelist not configured; call set or from_file"
      return
    end if

  end function nml_optional_is_valid

end module nml_optional
