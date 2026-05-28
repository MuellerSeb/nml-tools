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
    to_lower, &
    label_len
  use ieee_arithmetic, only: ieee_value, ieee_quiet_nan, ieee_is_nan
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

  !> \class nml_report_t
  !> \brief Reference-driven report configuration
  !> \details A second namelist sharing the external definition library.
  type, public :: nml_report_t
    logical :: is_configured = .false. !< whether the namelist has been configured
    character(len=label_len) :: label !< Report label
    integer(i4) :: level !< Reporting detail
    real(dp) :: acceptance_fraction !< Acceptance fraction
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

    if (present(allow_missing)) then
      if (allow_missing) then
        if (val == -huge(val)) then
          in_enum = .true.
          return
        end if
      end if
    end if
    in_enum = any(val == level__enum_values)
  end function level__in_enum

  !> \brief Check whether a value is within bounds
  elemental logical function acceptance_fraction__in_bounds(val, allow_missing) result(in_bounds)
    real(dp), intent(in) :: val !< value to check
    logical, intent(in), optional :: allow_missing !< allow sentinel values as valid

    if (present(allow_missing)) then
      if (allow_missing) then
        if (ieee_is_nan(val)) then
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
  integer function nml_report_init(this, errmsg) result(status)
    class(nml_report_t), intent(inout) :: this !< namelist instance
    character(len=*), intent(out), optional :: errmsg !< error message for non-OK status values

    status = NML_OK
    if (present(errmsg)) errmsg = ""
    this%is_configured = .false.

    ! default values
    this%label = label__default
    this%level = level__default
    this%acceptance_fraction = acceptance_fraction__default
  end function nml_report_init


  !> \brief Read report namelist from file
  integer function nml_report_from_file(this, file, errmsg) result(status)
    class(nml_report_t), intent(inout) :: this !< namelist instance
    character(len=*), intent(in) :: file !< path to namelist file
    character(len=*), intent(out), optional :: errmsg !< error message for non-OK status values
    ! namelist variables
    character(len=label_len) :: label
    integer(i4) :: level
    real(dp) :: acceptance_fraction
    ! locals
    type(nml_file_t) :: nml
    integer :: iostat
    integer :: close_status
    character(len=nml_line_buffer) :: iomsg

    namelist /report/ &
      label, &
      level, &
      acceptance_fraction

    status = this%init(errmsg=errmsg)
    if (status /= NML_OK) return
    label = this%label
    level = this%level
    acceptance_fraction = this%acceptance_fraction

    status = nml%open(file, errmsg=errmsg)
    if (status /= NML_OK) return

    status = nml%find("report", errmsg=errmsg)
    if (status /= NML_OK) then
      close_status = nml%close()
      return
    end if

    ! read namelist
    read(nml%unit, nml=report, iostat=iostat, iomsg=iomsg)
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
    this%label = label
    this%level = level
    this%acceptance_fraction = acceptance_fraction

    ! mark as configured
    this%is_configured = .true.
    status = NML_OK
  end function nml_report_from_file

  !> \brief Set report values
  integer function nml_report_set(this, &
    label, &
    level, &
    acceptance_fraction, &
    errmsg) result(status)

    class(nml_report_t), intent(inout) :: this !< namelist instance
    character(len=*), intent(out), optional :: errmsg !< error message for non-OK status values
    character(len=*), intent(in), optional :: label !< Report label
    integer(i4), intent(in), optional :: level !< Reporting detail
    real(dp), intent(in), optional :: acceptance_fraction !< Acceptance fraction

    status = this%init(errmsg=errmsg)
    if (status /= NML_OK) return

    ! required parameters
    ! override with provided values
    if (present(label)) this%label = label
    if (present(level)) this%level = level
    if (present(acceptance_fraction)) this%acceptance_fraction = acceptance_fraction

    ! mark as configured
    this%is_configured = .true.
    status = NML_OK
  end function nml_report_set

  !> \brief Check whether a namelist value was set
  integer function nml_report_is_set(this, name, idx, errmsg) result(status)
    class(nml_report_t), intent(in) :: this !< namelist instance
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
    case ("label")
      if (present(idx)) then
        status = NML_ERR_INVALID_INDEX
        if (present(errmsg)) errmsg = "index not supported for 'label'"
        return
      end if
    case ("level")
      if (present(idx)) then
        status = NML_ERR_INVALID_INDEX
        if (present(errmsg)) errmsg = "index not supported for 'level'"
        return
      end if
    case ("acceptance_fraction")
      if (present(idx)) then
        status = NML_ERR_INVALID_INDEX
        if (present(errmsg)) errmsg = "index not supported for 'acceptance_fraction'"
        return
      end if
    case default
      status = NML_ERR_INVALID_NAME
      if (present(errmsg)) errmsg = "unknown field: " // trim(name)
    end select
    if (status == NML_ERR_NOT_SET .and. present(errmsg)) then
      if (len_trim(errmsg) == 0) errmsg = "field not set: " // trim(name)
    end if
  end function nml_report_is_set

  !> \brief Validate required values and constraints
  integer function nml_report_is_valid(this, errmsg) result(status)
    class(nml_report_t), intent(in) :: this !< namelist instance
    character(len=*), intent(out), optional :: errmsg !< error message for non-OK status values
    integer :: istat

    status = NML_OK
    if (present(errmsg)) errmsg = ""
    if (.not. this%is_configured) then
      status = NML_ERR_NOT_SET
      if (present(errmsg)) errmsg = "namelist not configured; call set or from_file"
      return
    end if

    ! enum constraints
    istat = this%is_set("level", errmsg=errmsg)
    if (istat == NML_OK) then
      if (.not. level__in_enum(this%level)) then
        status = NML_ERR_ENUM
        if (present(errmsg)) errmsg = "enum constraint failed: level"
        return
      end if
    else if (istat /= NML_ERR_NOT_SET) then
      status = istat
      return
    end if
    ! bounds constraints
    istat = this%is_set("acceptance_fraction", errmsg=errmsg)
    if (istat == NML_OK) then
      if (.not. acceptance_fraction__in_bounds(this%acceptance_fraction)) then
        status = NML_ERR_BOUNDS
        if (present(errmsg)) errmsg = "bounds constraint failed: acceptance_fraction"
        return
      end if
    else if (istat /= NML_ERR_NOT_SET) then
      status = istat
      return
    end if
  end function nml_report_is_valid

end module nml_report
