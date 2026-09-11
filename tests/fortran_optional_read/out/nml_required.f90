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
    nml__achar => achar, &
    nml__all => all, &
    nml__allocated => allocated, &
    nml__any => any, &
    nml__huge => huge, &
    nml__len => len, &
    nml__len_trim => len_trim, &
    nml__minval => minval, &
    nml__present => present, &
    nml__reshape => reshape, &
    nml__shape => shape, &
    nml__size => size, &
    nml__trim => trim, &
    to_lower
  ! kind specifiers listed in the nml-tools configuration file
  use iso_fortran_env, only: &
    i4=>int32

  implicit none

  private :: nml_required_read__from_file
  private :: nml__achar, nml__all, nml__allocated, nml__any, nml__huge, nml__len, &
    nml__len_trim, nml__minval, nml__present, nml__reshape, nml__shape, nml__size, &
    nml__trim

  !> \class nml_required_data_t
  !> \brief Schema-backed values for required
  type, public :: nml_required_data_t
    integer(i4) :: count !< count
  end type nml_required_data_t

  !> \class nml_required_t
  !> \brief Required generated reader
  !> \details Required generated reader
  type, public :: nml_required_t
    type(nml_required_data_t) :: data !< schema-backed namelist values
    logical :: is_configured = .false. !< whether the namelist has been configured
  contains
    procedure :: init => nml_required_init
    procedure :: from_file => nml_required_from_file
    procedure :: set => nml_required_set
    procedure :: is_set => nml_required_is_set
    procedure :: is_valid => nml_required_is_valid
  end type nml_required_t

contains

  !> \brief Initialize defaults and sentinels for required
  integer function nml_required_init(nml__obj, errmsg) result(nml__status)
    class(nml_required_t), intent(inout) :: nml__obj !< namelist instance
    character(len=*), intent(out), optional :: errmsg !< error message for non-OK status values

    nml__status = NML_OK
    if (nml__present(errmsg)) errmsg = ""
    nml__obj%is_configured = .false.

    ! sentinel values for required/optional parameters
    nml__obj%data%count = -nml__huge(nml__obj%data%count) ! sentinel for required integer
  end function nml_required_init


  !> \brief Read required namelist from file
  integer function nml_required_from_file(nml__obj, file, errmsg) result(nml__status)
    class(nml_required_t), intent(inout) :: nml__obj !< namelist instance
    character(len=*), intent(in) :: file !< path to namelist file
    character(len=*), intent(out), optional :: errmsg !< error message for non-OK status values

    nml__status = nml_required_read__from_file(nml__obj, file, errmsg)
  end function nml_required_from_file

  integer function nml_required_read__from_file(nml__obj, nml__file, errmsg) &
    result(nml__status)
    class(nml_required_t), intent(inout) :: nml__obj
    character(len=*), intent(in) :: nml__file
    character(len=*), intent(out), optional :: errmsg
    ! namelist variables
    integer(i4) :: count
    ! locals
    type(nml_file_t) :: nml__reader
    integer :: nml__iostat
    integer :: nml__close_status
    character(len=nml_line_buffer) :: nml__iomsg

    namelist /required/ &
      count

    nml__status = nml__obj%init(errmsg=errmsg)
    if (nml__status /= NML_OK) return
    count = nml__obj%data%count

    nml__status = nml__reader%open(nml__file, errmsg=errmsg)
    if (nml__status /= NML_OK) return

    nml__status = nml__reader%find("required", errmsg=errmsg)
    if (nml__status /= NML_OK) then
      nml__close_status = nml__reader%close()
      return
    end if

    ! read namelist
    read(nml__reader%unit, nml=required, iostat=nml__iostat, iomsg=nml__iomsg)
    if (nml__iostat /= 0) then
      nml__status = NML_ERR_READ
      if (nml__present(errmsg)) errmsg = nml__trim(nml__iomsg)
      nml__close_status = nml__reader%close()
      return
    end if
    nml__close_status = nml__reader%close(errmsg=errmsg)
    if (nml__close_status /= NML_OK) then
      nml__status = nml__close_status
      return
    end if

    ! assign values
    nml__obj%data%count = count

    ! mark as configured
    nml__obj%is_configured = .true.
    nml__status = NML_OK
  end function nml_required_read__from_file

  !> \brief Set required values
  integer function nml_required_set(nml__obj, &
    count, &
    errmsg) result(nml__status)

    class(nml_required_t), intent(inout) :: nml__obj !< namelist instance
    character(len=*), intent(out), optional :: errmsg !< error message for non-OK status values
    integer(i4), intent(in) :: count !< count
    nml__status = nml__obj%init(errmsg=errmsg)
    if (nml__status /= NML_OK) return

    ! required parameters
    nml__obj%data%count = count

    ! mark as configured
    nml__obj%is_configured = .true.
    nml__status = NML_OK
  end function nml_required_set

  !> \brief Check whether a namelist value was set
  integer function nml_required_is_set(nml__obj, name, idx, errmsg) result(nml__status)
    class(nml_required_t), intent(in) :: nml__obj !< namelist instance
    character(len=*), intent(in) :: name !< field name
    integer, intent(in), optional :: idx(:) !< optional field index values
    character(len=*), intent(out), optional :: errmsg !< error message for non-OK status values

    nml__status = NML_OK
    if (nml__present(errmsg)) errmsg = ""
    if (.not. nml__obj%is_configured) then
      nml__status = NML_ERR_NOT_SET
      if (nml__present(errmsg)) errmsg = "namelist not configured; call set or from_file"
      return
    end if
    select case (to_lower(nml__trim(name)))
    case ("count")
      if (nml__present(idx)) then
        nml__status = NML_ERR_INVALID_INDEX
        if (nml__present(errmsg)) errmsg = "index not supported for 'count'"
        return
      end if
      if (nml__obj%data%count == -nml__huge(nml__obj%data%count)) nml__status = NML_ERR_NOT_SET
    case default
      nml__status = NML_ERR_INVALID_NAME
      if (nml__present(errmsg)) errmsg = "unknown field: " // nml__trim(name)
    end select
    if (nml__status == NML_ERR_NOT_SET .and. nml__present(errmsg)) then
      if (nml__len_trim(errmsg) == 0) errmsg = "field not set: " // nml__trim(name)
    end if
  end function nml_required_is_set

  !> \brief Validate required values and constraints
  integer function nml_required_is_valid(nml__obj, errmsg) result(nml__status)
    class(nml_required_t), intent(in) :: nml__obj !< namelist instance
    character(len=*), intent(out), optional :: errmsg !< error message for non-OK status values
    integer :: nml__istat

    nml__status = NML_OK
    if (nml__present(errmsg)) errmsg = ""
    if (.not. nml__obj%is_configured) then
      nml__status = NML_ERR_NOT_SET
      if (nml__present(errmsg)) errmsg = "namelist not configured; call set or from_file"
      return
    end if

    ! required parameters
    nml__istat = nml__obj%is_set("count", errmsg=errmsg)
    if (nml__istat == NML_ERR_NOT_SET) then
      nml__status = NML_ERR_REQUIRED
      if (nml__present(errmsg)) then
        if (nml__len_trim(errmsg) == 0) then
          errmsg = "field not set: count"
        end if
        errmsg = "required " // nml__trim(errmsg)
      end if
      return
    end if
    if (nml__istat /= NML_OK) then
      nml__status = nml__istat
      return
    end if
  end function nml_required_is_valid

end module nml_required
