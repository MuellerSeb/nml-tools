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
  use nml_helper_intrinsics, only: nml__achar => achar
  use nml_helper_intrinsics, only: nml__all => all
  use nml_helper_intrinsics, only: nml__allocated => allocated
  use nml_helper_intrinsics, only: nml__any => any
  use nml_helper_intrinsics, only: nml__huge => huge
  use nml_helper_intrinsics, only: nml__len => len
  use nml_helper_intrinsics, only: nml__len_trim => len_trim
  use nml_helper_intrinsics, only: nml__minval => minval
  use nml_helper_intrinsics, only: nml__present => present
  use nml_helper_intrinsics, only: nml__reshape => reshape
  use nml_helper_intrinsics, only: nml__shape => shape
  use nml_helper_intrinsics, only: nml__size => size
  use nml_helper_intrinsics, only: nml__trim => trim
  ! kind specifiers listed in the nml-tools configuration file
  use iso_fortran_env, only: &
    i4=>int32

  implicit none

  ! default values
  integer(i4), parameter, public :: count__default = 7_i4

  private :: nml_optional_read__from_file
  private :: nml__achar, nml__all, nml__allocated, nml__any, nml__huge, nml__len, &
    nml__len_trim, nml__minval, nml__present, nml__reshape, nml__shape, nml__size, &
    nml__trim

  !> \class nml_optional_data_t
  !> \brief Schema-backed values for optional
  type, public :: nml_optional_data_t
    integer(i4) :: count !< count
    character(len=16) :: label !< label
  end type nml_optional_data_t

  !> \class nml_optional_t
  !> \brief Optional generated reader
  !> \details Optional generated reader
  type, public :: nml_optional_t
    type(nml_optional_data_t) :: data !< schema-backed namelist values
    logical :: is_configured = .false. !< whether the namelist has been configured
  contains
    procedure :: init => nml_optional_init
    procedure :: from_file => nml_optional_from_file
    procedure :: set => nml_optional_set
    procedure :: is_set => nml_optional_is_set
    procedure :: is_valid => nml_optional_is_valid
  end type nml_optional_t

contains

  !> \brief Initialize defaults and sentinels for optional
  integer function nml_optional_init(nml__obj, errmsg) result(nml__status)
    class(nml_optional_t), intent(inout) :: nml__obj !< namelist instance
    character(len=*), intent(out), optional :: errmsg !< error message for non-OK status values

    nml__status = NML_OK
    if (nml__present(errmsg)) errmsg = ""
    nml__obj%is_configured = .false.

    ! sentinel values for required/optional parameters
    nml__obj%data%label = nml__achar(0) ! sentinel for optional string
    ! default values
    nml__obj%data%count = count__default
  end function nml_optional_init


  !> \brief Read optional namelist from file
  integer function nml_optional_from_file(nml__obj, file, errmsg) result(nml__status)
    class(nml_optional_t), intent(inout) :: nml__obj !< namelist instance
    character(len=*), intent(in) :: file !< path to namelist file
    character(len=*), intent(out), optional :: errmsg !< error message for non-OK status values

    nml__status = nml_optional_read__from_file(nml__obj, file, errmsg)
  end function nml_optional_from_file

  integer function nml_optional_read__from_file(nml__obj, nml__file, errmsg) &
    result(nml__status)
    class(nml_optional_t), intent(inout) :: nml__obj
    character(len=*), intent(in) :: nml__file
    character(len=*), intent(out), optional :: errmsg
    ! namelist variables
    integer(i4) :: count
    character(len=16) :: label
    ! locals
    type(nml_file_t) :: nml__reader
    integer :: nml__iostat
    integer :: nml__close_status
    character(len=nml_line_buffer) :: nml__iomsg

    namelist /optional/ &
      count, &
      label

    nml__status = nml__obj%init(errmsg=errmsg)
    if (nml__status /= NML_OK) return
    count = nml__obj%data%count
    label = nml__obj%data%label

    nml__status = nml__reader%open(nml__file, errmsg=errmsg)
    if (nml__status /= NML_OK) return

    nml__status = nml__reader%find("optional", errmsg=errmsg)
    if (nml__status /= NML_OK) then
      if (nml__status == NML_ERR_NML_NOT_FOUND) then
        nml__close_status = nml__reader%close(errmsg=errmsg)
        if (nml__close_status /= NML_OK) then
          nml__status = nml__close_status
          return
        end if
        nml__obj%is_configured = .true.
        nml__status = NML_OK
        return
      end if
      nml__close_status = nml__reader%close()
      return
    end if

    ! read namelist
    read(nml__reader%unit, nml=optional, iostat=nml__iostat, iomsg=nml__iomsg)
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
    nml__obj%data%label = label

    ! mark as configured
    nml__obj%is_configured = .true.
    nml__status = NML_OK
  end function nml_optional_read__from_file

  !> \brief Set optional values
  integer function nml_optional_set(nml__obj, &
    count, &
    label, &
    errmsg) result(nml__status)

    class(nml_optional_t), intent(inout) :: nml__obj !< namelist instance
    character(len=*), intent(out), optional :: errmsg !< error message for non-OK status values
    integer(i4), intent(in), optional :: count !< count
    character(len=*), intent(in), optional :: label !< label
    nml__status = nml__obj%init(errmsg=errmsg)
    if (nml__status /= NML_OK) return

    ! required parameters
    ! override with provided values
    if (nml__present(count)) nml__obj%data%count = count
    if (nml__present(label)) nml__obj%data%label = label

    ! mark as configured
    nml__obj%is_configured = .true.
    nml__status = NML_OK
  end function nml_optional_set

  !> \brief Check whether a namelist value was set
  integer function nml_optional_is_set(nml__obj, name, idx, errmsg) result(nml__status)
    class(nml_optional_t), intent(in) :: nml__obj !< namelist instance
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
    case ("label")
      if (nml__present(idx)) then
        nml__status = NML_ERR_INVALID_INDEX
        if (nml__present(errmsg)) errmsg = "index not supported for 'label'"
        return
      end if
      if (nml__obj%data%label == nml__achar(0)) nml__status = NML_ERR_NOT_SET
    case default
      nml__status = NML_ERR_INVALID_NAME
      if (nml__present(errmsg)) errmsg = "unknown field: " // nml__trim(name)
    end select
    if (nml__status == NML_ERR_NOT_SET .and. nml__present(errmsg)) then
      if (nml__len_trim(errmsg) == 0) errmsg = "field not set: " // nml__trim(name)
    end if
  end function nml_optional_is_set

  !> \brief Validate required values and constraints
  integer function nml_optional_is_valid(nml__obj, errmsg) result(nml__status)
    class(nml_optional_t), intent(in) :: nml__obj !< namelist instance
    character(len=*), intent(out), optional :: errmsg !< error message for non-OK status values
    integer :: nml__istat

    nml__status = NML_OK
    if (nml__present(errmsg)) errmsg = ""
    if (.not. nml__obj%is_configured) then
      nml__status = NML_ERR_NOT_SET
      if (nml__present(errmsg)) errmsg = "namelist not configured; call set or from_file"
      return
    end if

  end function nml_optional_is_valid

end module nml_optional
