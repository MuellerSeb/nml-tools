!> \file nml_report.f90
!> \copydoc nml_report

!> \brief Reference-driven report configuration
!> \details A second namelist sharing the external definition library.
module nml_report
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
    to_lower, &
    label_len
  use ieee_arithmetic, only: nml__ieee_value => ieee_value, &
    nml__ieee_quiet_nan => ieee_quiet_nan, nml__ieee_is_nan => ieee_is_nan
  ! kind specifiers listed in the nml-tools configuration file
  use iso_fortran_env, only: &
    i4=>int32, &
    dp=>real64

  implicit none

  ! default values
  character(len=label_len), parameter, public :: label__default = "station-summary"
  integer(i4), parameter, public :: level__default = 1_i4
  real(dp), parameter, public :: acceptance_fraction__default = 0.75_dp

  ! enum values
  integer(i4), parameter, public :: level__enum_values(3) = [0_i4, 1_i4, 2_i4]

  ! bounds values
  real(dp), parameter, public :: acceptance_fraction__min = 0.5_dp
  real(dp), parameter, public :: acceptance_fraction__max = 1.0_dp

  private :: nml_report_read__from_file
  private :: nml__achar, nml__all, nml__allocated, nml__any, nml__huge, nml__len, &
    nml__len_trim, nml__minval, nml__present, nml__reshape, nml__shape, nml__size, &
    nml__trim
  private :: nml__ieee_value, nml__ieee_quiet_nan, nml__ieee_is_nan

  !> \class nml_report_data_t
  !> \brief Schema-backed values for report
  type, public :: nml_report_data_t
    character(len=label_len) :: label !< Report label
    integer(i4) :: level !< Reporting detail
    real(dp) :: acceptance_fraction !< Acceptance fraction
  end type nml_report_data_t

  !> \class nml_report_t
  !> \brief Reference-driven report configuration
  !> \details A second namelist sharing the external definition library.
  type, public :: nml_report_t
    type(nml_report_data_t) :: data !< schema-backed namelist values
    logical :: is_configured = .false. !< whether the namelist has been configured
  contains
    procedure :: init => nml_report_init
    procedure :: from_file => nml_report_from_file
    procedure :: set => nml_report_set
    procedure :: is_set => nml_report_is_set
    procedure :: is_valid => nml_report_is_valid
  end type nml_report_t

contains

  !> \brief Check whether a value is part of an enum
  elemental logical function level__in_enum(val, allow_missing) result(in_enum)
    integer(i4), intent(in) :: val !< value to check
    logical, intent(in), optional :: allow_missing !< allow sentinel values as valid

    if (nml__present(allow_missing)) then
      if (allow_missing) then
        if (val == -nml__huge(val)) then
          in_enum = .true.
          return
        end if
      end if
    end if
    in_enum = nml__any(val == level__enum_values)
  end function level__in_enum

  !> \brief Check whether a value is within bounds
  elemental logical function acceptance_fraction__in_bounds(val, allow_missing) result(in_bounds)
    real(dp), intent(in) :: val !< value to check
    logical, intent(in), optional :: allow_missing !< allow sentinel values as valid

    if (nml__present(allow_missing)) then
      if (allow_missing) then
        if (nml__ieee_is_nan(val)) then
          in_bounds = .true.
          return
        end if
      end if
    end if

    in_bounds = .true.
    if (val < acceptance_fraction__min) in_bounds = .false.
    if (val > acceptance_fraction__max) in_bounds = .false.
  end function acceptance_fraction__in_bounds

  !> \brief Initialize defaults and sentinels for report
  integer function nml_report_init(nml__obj, errmsg) result(nml__status)
    class(nml_report_t), intent(inout) :: nml__obj !< namelist instance
    character(len=*), intent(out), optional :: errmsg !< error message for non-OK status values

    nml__status = NML_OK
    if (nml__present(errmsg)) errmsg = ""
    nml__obj%is_configured = .false.

    ! default values
    nml__obj%data%label = label__default
    nml__obj%data%level = level__default
    nml__obj%data%acceptance_fraction = acceptance_fraction__default
  end function nml_report_init


  !> \brief Read report namelist from file
  integer function nml_report_from_file(nml__obj, file, errmsg) result(nml__status)
    class(nml_report_t), intent(inout) :: nml__obj !< namelist instance
    character(len=*), intent(in) :: file !< path to namelist file
    character(len=*), intent(out), optional :: errmsg !< error message for non-OK status values

    nml__status = nml_report_read__from_file(nml__obj, file, errmsg)
  end function nml_report_from_file

  integer function nml_report_read__from_file(nml__obj, nml__file, errmsg) &
    result(nml__status)
    class(nml_report_t), intent(inout) :: nml__obj
    character(len=*), intent(in) :: nml__file
    character(len=*), intent(out), optional :: errmsg
    ! namelist variables
    character(len=label_len) :: label
    integer(i4) :: level
    real(dp) :: acceptance_fraction
    ! locals
    type(nml_file_t) :: nml__reader
    integer :: nml__iostat
    integer :: nml__close_status
    character(len=nml_line_buffer) :: nml__iomsg

    namelist /report/ &
      label, &
      level, &
      acceptance_fraction

    nml__status = nml__obj%init(errmsg=errmsg)
    if (nml__status /= NML_OK) return
    label = nml__obj%data%label
    level = nml__obj%data%level
    acceptance_fraction = nml__obj%data%acceptance_fraction

    nml__status = nml__reader%open(nml__file, errmsg=errmsg)
    if (nml__status /= NML_OK) return

    nml__status = nml__reader%find("report", errmsg=errmsg)
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
    read(nml__reader%unit, nml=report, iostat=nml__iostat, iomsg=nml__iomsg)
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
    nml__obj%data%label = label
    nml__obj%data%level = level
    nml__obj%data%acceptance_fraction = acceptance_fraction

    ! mark as configured
    nml__obj%is_configured = .true.
    nml__status = NML_OK
  end function nml_report_read__from_file

  !> \brief Set report values
  integer function nml_report_set(nml__obj, &
    label, &
    level, &
    acceptance_fraction, &
    errmsg) result(nml__status)

    class(nml_report_t), intent(inout) :: nml__obj !< namelist instance
    character(len=*), intent(out), optional :: errmsg !< error message for non-OK status values
    character(len=*), intent(in), optional :: label !< Report label
    integer(i4), intent(in), optional :: level !< Reporting detail
    real(dp), intent(in), optional :: acceptance_fraction !< Acceptance fraction
    nml__status = nml__obj%init(errmsg=errmsg)
    if (nml__status /= NML_OK) return

    ! required parameters
    ! override with provided values
    if (nml__present(label)) nml__obj%data%label = label
    if (nml__present(level)) nml__obj%data%level = level
    if (nml__present(acceptance_fraction)) nml__obj%data%acceptance_fraction = acceptance_fraction

    ! mark as configured
    nml__obj%is_configured = .true.
    nml__status = NML_OK
  end function nml_report_set

  !> \brief Check whether a namelist value was set
  integer function nml_report_is_set(nml__obj, name, idx, errmsg) result(nml__status)
    class(nml_report_t), intent(in) :: nml__obj !< namelist instance
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
    case ("label")
      if (nml__present(idx)) then
        nml__status = NML_ERR_INVALID_INDEX
        if (nml__present(errmsg)) errmsg = "index not supported for 'label'"
        return
      end if
    case ("level")
      if (nml__present(idx)) then
        nml__status = NML_ERR_INVALID_INDEX
        if (nml__present(errmsg)) errmsg = "index not supported for 'level'"
        return
      end if
    case ("acceptance_fraction")
      if (nml__present(idx)) then
        nml__status = NML_ERR_INVALID_INDEX
        if (nml__present(errmsg)) errmsg = "index not supported for 'acceptance_fraction'"
        return
      end if
    case default
      nml__status = NML_ERR_INVALID_NAME
      if (nml__present(errmsg)) errmsg = "unknown field: " // nml__trim(name)
    end select
    if (nml__status == NML_ERR_NOT_SET .and. nml__present(errmsg)) then
      if (nml__len_trim(errmsg) == 0) errmsg = "field not set: " // nml__trim(name)
    end if
  end function nml_report_is_set

  !> \brief Validate required values and constraints
  integer function nml_report_is_valid(nml__obj, errmsg) result(nml__status)
    class(nml_report_t), intent(in) :: nml__obj !< namelist instance
    character(len=*), intent(out), optional :: errmsg !< error message for non-OK status values
    integer :: nml__istat

    nml__status = NML_OK
    if (nml__present(errmsg)) errmsg = ""
    if (.not. nml__obj%is_configured) then
      nml__status = NML_ERR_NOT_SET
      if (nml__present(errmsg)) errmsg = "namelist not configured; call set or from_file"
      return
    end if

    ! enum constraints
    nml__istat = nml__obj%is_set("level", errmsg=errmsg)
    if (nml__istat == NML_OK) then
      if (.not. level__in_enum(nml__obj%data%level)) then
        nml__status = NML_ERR_ENUM
        if (nml__present(errmsg)) errmsg = "enum constraint failed: level"
        return
      end if
    else if (nml__istat /= NML_ERR_NOT_SET) then
      nml__status = nml__istat
      return
    end if
    ! bounds constraints
    nml__istat = nml__obj%is_set("acceptance_fraction", errmsg=errmsg)
    if (nml__istat == NML_OK) then
      if (.not. acceptance_fraction__in_bounds(nml__obj%data%acceptance_fraction)) then
        nml__status = NML_ERR_BOUNDS
        if (nml__present(errmsg)) errmsg = "bounds constraint failed: acceptance_fraction"
        return
      end if
    else if (nml__istat /= NML_ERR_NOT_SET) then
      nml__status = nml__istat
      return
    end if
  end function nml_report_is_valid

end module nml_report
