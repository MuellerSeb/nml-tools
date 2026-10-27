!> \file nml_required.f90
!> \copydoc nml_required

!> \brief Required generated reader
!> \details Required generated reader
module nml_required
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

  !> \class nml_required_t
  !> \brief Required generated reader
  !> \details Required generated reader
  type, public :: nml_required_t
    logical :: is_configured = .false. !< whether the namelist has been configured
    integer(i4) :: count !< count
  contains
    procedure :: init => nml_required_init
    procedure :: from_file => nml_required_from_file
    procedure :: set => nml_required_set
    procedure :: is_set => nml_required_is_set
    procedure :: is_valid => nml_required_is_valid
  end type nml_required_t

contains

  !> \brief Initialize defaults and sentinels for required
  integer function nml_required_init(this, errmsg) result(status)
    class(nml_required_t), intent(inout) :: this !< namelist instance
    character(len=*), intent(out), optional :: errmsg !< error message for non-OK status values

    status = NML_OK
    if (present(errmsg)) errmsg = ""
    this%is_configured = .false.

    ! sentinel values for required/optional parameters
    this%count = -huge(this%count) ! sentinel for required integer
  end function nml_required_init


  !> \brief Read required namelist from file
  integer function nml_required_from_file(this, file, errmsg) result(status)
    class(nml_required_t), intent(inout) :: this !< namelist instance
    character(len=*), intent(in) :: file !< path to namelist file
    character(len=*), intent(out), optional :: errmsg !< error message for non-OK status values
    ! namelist variables
    integer(i4) :: count
    ! locals
    type(nml_file_t) :: nml
    integer :: iostat
    integer :: close_status
    character(len=nml_line_buffer) :: iomsg

    namelist /required/ &
      count

    status = this%init(errmsg=errmsg)
    if (status /= NML_OK) return
    count = this%count

    status = nml%open(file, errmsg=errmsg)
    if (status /= NML_OK) return

    status = nml%find("required", errmsg=errmsg)
    if (status /= NML_OK) then
      close_status = nml%close()
      return
    end if

    ! read namelist
    read(nml%unit, nml=required, iostat=iostat, iomsg=iomsg)
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

    ! mark as configured
    this%is_configured = .true.
    status = NML_OK
  end function nml_required_from_file

  !> \brief Set required values
  integer function nml_required_set(this, &
    count, &
    errmsg) result(status)

    class(nml_required_t), intent(inout) :: this !< namelist instance
    character(len=*), intent(out), optional :: errmsg !< error message for non-OK status values
    integer(i4), intent(in) :: count !< count

    status = this%init(errmsg=errmsg)
    if (status /= NML_OK) return

    ! required parameters
    this%count = count

    ! mark as configured
    this%is_configured = .true.
    status = NML_OK
  end function nml_required_set

  !> \brief Check whether a namelist value was set
  integer function nml_required_is_set(this, name, idx, errmsg) result(status)
    class(nml_required_t), intent(in) :: this !< namelist instance
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
      if (this%count == -huge(this%count)) status = NML_ERR_NOT_SET
    case default
      status = NML_ERR_INVALID_NAME
      if (present(errmsg)) errmsg = "unknown field: " // trim(name)
    end select
    if (status == NML_ERR_NOT_SET .and. present(errmsg)) then
      if (len_trim(errmsg) == 0) errmsg = "field not set: " // trim(name)
    end if
  end function nml_required_is_set

  !> \brief Validate required values and constraints
  integer function nml_required_is_valid(this, errmsg) result(status)
    class(nml_required_t), intent(in) :: this !< namelist instance
    character(len=*), intent(out), optional :: errmsg !< error message for non-OK status values
    integer :: istat

    status = NML_OK
    if (present(errmsg)) errmsg = ""
    if (.not. this%is_configured) then
      status = NML_ERR_NOT_SET
      if (present(errmsg)) errmsg = "namelist not configured; call set or from_file"
      return
    end if

    ! required parameters
    istat = this%is_set("count", errmsg=errmsg)
    if (istat == NML_ERR_NOT_SET) then
      status = NML_ERR_REQUIRED
      if (present(errmsg)) then
        if (len_trim(errmsg) == 0) then
          errmsg = "field not set: count"
        end if
        errmsg = "required " // trim(errmsg)
      end if
      return
    end if
    if (istat /= NML_OK) then
      status = istat
      return
    end if
  end function nml_required_is_valid

end module nml_required
