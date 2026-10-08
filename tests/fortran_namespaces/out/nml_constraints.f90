!> \file nml_constraints.f90
!> \copydoc nml_constraints

!> \brief Constraint internal state
!> \details Constraint internal state
module nml_constraints
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
    idx__check, &
    to__lower
  ! kind specifiers listed in the nml-tools configuration file
  use iso_fortran_env, only: &
    val=>int32, &
    allow_missing=>int16, &
    in_bounds=>int64

  implicit none

  ! enum values
  integer(val), parameter, public :: choice__enum_values(2) = [1_val, 2_val]

  ! bounds values
  integer(val), parameter, public :: choice__min = 1_val
  integer(val), parameter, public :: choice__max = 2_val
  integer(allow_missing), parameter, public :: limit__min = 0_allow_missing
  integer(in_bounds), parameter, public :: upper__max = 4_in_bounds

  private :: nml_constraints_read__from_file

  !> \class nml_constraints_data_t
  !> \brief Schema-backed values for constraints
  type, public :: nml_constraints_data_t
    integer(val) :: choice !< choice
    integer(allow_missing) :: limit !< limit
    integer(in_bounds) :: upper !< upper
  end type nml_constraints_data_t

  !> \class nml_constraints_t
  !> \brief Constraint internal state
  !> \details Constraint internal state
  type, public :: nml_constraints_t
    type(nml_constraints_data_t) :: data !< schema-backed namelist values
    logical :: is_configured = .false. !< whether the namelist has been configured
  contains
    procedure :: init => nml_constraints_init
    procedure :: from_file => nml_constraints_from_file
    procedure :: set => nml_constraints_set
    procedure :: is_set => nml_constraints_is_set
    procedure :: is_valid => nml_constraints_is_valid
  end type nml_constraints_t

contains

  !> \brief Check whether a value is part of an enum
  elemental logical function choice__in_enum(nml__val, nml__allow_missing) result(nml__in_enum)
    integer(val), intent(in) :: nml__val !< value to check
    logical, intent(in), optional :: nml__allow_missing !< allow sentinel values as valid

    if (present(nml__allow_missing)) then
      if (nml__allow_missing) then
        if (nml__val == -huge(nml__val)) then
          nml__in_enum = .true.
          return
        end if
      end if
    end if
    nml__in_enum = any(nml__val == choice__enum_values)
  end function choice__in_enum

  !> \brief Check whether a value is within bounds
  elemental logical function choice__in_bounds(nml__val, nml__allow_missing) result(nml__in_bounds)
    integer(val), intent(in) :: nml__val !< value to check
    logical, intent(in), optional :: nml__allow_missing !< allow sentinel values as valid

    if (present(nml__allow_missing)) then
      if (nml__allow_missing) then
        if (nml__val == -huge(nml__val)) then
          nml__in_bounds = .true.
          return
        end if
      end if
    end if

    nml__in_bounds = .true.
    if (nml__val < choice__min) nml__in_bounds = .false.
    if (nml__val > choice__max) nml__in_bounds = .false.
  end function choice__in_bounds

  !> \brief Check whether a value is within bounds
  elemental logical function limit__in_bounds(nml__val, nml__allow_missing) result(nml__in_bounds)
    integer(allow_missing), intent(in) :: nml__val !< value to check
    logical, intent(in), optional :: nml__allow_missing !< allow sentinel values as valid

    if (present(nml__allow_missing)) then
      if (nml__allow_missing) then
        if (nml__val == -huge(nml__val)) then
          nml__in_bounds = .true.
          return
        end if
      end if
    end if

    nml__in_bounds = .true.
    if (nml__val < limit__min) nml__in_bounds = .false.
  end function limit__in_bounds

  !> \brief Check whether a value is within bounds
  elemental logical function upper__in_bounds(nml__val, nml__allow_missing) result(nml__in_bounds)
    integer(in_bounds), intent(in) :: nml__val !< value to check
    logical, intent(in), optional :: nml__allow_missing !< allow sentinel values as valid

    if (present(nml__allow_missing)) then
      if (nml__allow_missing) then
        if (nml__val == -huge(nml__val)) then
          nml__in_bounds = .true.
          return
        end if
      end if
    end if

    nml__in_bounds = .true.
    if (nml__val > upper__max) nml__in_bounds = .false.
  end function upper__in_bounds

  !> \brief Initialize defaults and sentinels for constraints
  integer function nml_constraints_init(nml__obj, errmsg) result(nml__status)
    class(nml_constraints_t), intent(inout) :: nml__obj !< namelist instance
    character(len=*), intent(out), optional :: errmsg !< error message for non-OK status values

    nml__status = NML_OK
    if (present(errmsg)) errmsg = ""
    nml__obj%is_configured = .false.

    ! sentinel values for required/optional parameters
    nml__obj%data%choice = -huge(nml__obj%data%choice) ! sentinel for optional integer
    nml__obj%data%limit = -huge(nml__obj%data%limit) ! sentinel for optional integer
    nml__obj%data%upper = -huge(nml__obj%data%upper) ! sentinel for optional integer
  end function nml_constraints_init


  !> \brief Read constraints namelist from file
  integer function nml_constraints_from_file(nml__obj, file, errmsg) result(nml__status)
    class(nml_constraints_t), intent(inout) :: nml__obj !< namelist instance
    character(len=*), intent(in) :: file !< path to namelist file
    character(len=*), intent(out), optional :: errmsg !< error message for non-OK status values

    nml__status = nml_constraints_read__from_file(nml__obj, file, errmsg)
  end function nml_constraints_from_file

  integer function nml_constraints_read__from_file(nml__obj, nml__file, errmsg) &
    result(nml__status)
    class(nml_constraints_t), intent(inout) :: nml__obj
    character(len=*), intent(in) :: nml__file
    character(len=*), intent(out), optional :: errmsg
    ! namelist variables
    integer(val) :: choice
    integer(allow_missing) :: limit
    integer(in_bounds) :: upper
    ! locals
    type(nml_file_t) :: nml__reader
    integer :: nml__iostat
    integer :: nml__close_status
    character(len=nml_line_buffer) :: nml__iomsg

    namelist /constraints/ &
      choice, &
      limit, &
      upper

    nml__status = nml__obj%init(errmsg=errmsg)
    if (nml__status /= NML_OK) return
    choice = nml__obj%data%choice
    limit = nml__obj%data%limit
    upper = nml__obj%data%upper

    nml__status = nml__reader%open(nml__file, errmsg=errmsg)
    if (nml__status /= NML_OK) return

    nml__status = nml__reader%find("constraints", errmsg=errmsg)
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
    read(nml__reader%unit, nml=constraints, iostat=nml__iostat, iomsg=nml__iomsg)
    if (nml__iostat /= 0) then
      nml__status = NML_ERR_READ
      if (present(errmsg)) errmsg = trim(nml__iomsg)
      nml__close_status = nml__reader%close()
      return
    end if
    nml__close_status = nml__reader%close(errmsg=errmsg)
    if (nml__close_status /= NML_OK) then
      nml__status = nml__close_status
      return
    end if

    ! assign values
    nml__obj%data%choice = choice
    nml__obj%data%limit = limit
    nml__obj%data%upper = upper

    ! mark as configured
    nml__obj%is_configured = .true.
    nml__status = NML_OK
  end function nml_constraints_read__from_file

  !> \brief Set constraints values
  integer function nml_constraints_set(nml__obj, &
    choice, &
    limit, &
    upper, &
    errmsg) result(nml__status)

    class(nml_constraints_t), intent(inout) :: nml__obj !< namelist instance
    character(len=*), intent(out), optional :: errmsg !< error message for non-OK status values
    integer(val), intent(in), optional :: choice !< choice
    integer(allow_missing), intent(in), optional :: limit !< limit
    integer(in_bounds), intent(in), optional :: upper !< upper
    nml__status = nml__obj%init(errmsg=errmsg)
    if (nml__status /= NML_OK) return

    ! required parameters
    ! override with provided values
    if (present(choice)) nml__obj%data%choice = choice
    if (present(limit)) nml__obj%data%limit = limit
    if (present(upper)) nml__obj%data%upper = upper

    ! mark as configured
    nml__obj%is_configured = .true.
    nml__status = NML_OK
  end function nml_constraints_set

  !> \brief Check whether a namelist value was set
  integer function nml_constraints_is_set(nml__obj, name, idx, errmsg) result(nml__status)
    class(nml_constraints_t), intent(in) :: nml__obj !< namelist instance
    character(len=*), intent(in) :: name !< field name
    integer, intent(in), optional :: idx(:) !< optional field index values
    character(len=*), intent(out), optional :: errmsg !< error message for non-OK status values

    nml__status = NML_OK
    if (present(errmsg)) errmsg = ""
    if (.not. nml__obj%is_configured) then
      nml__status = NML_ERR_NOT_SET
      if (present(errmsg)) errmsg = "namelist not configured; call set or from_file"
      return
    end if
    select case (to__lower(trim(name)))
    case ("choice")
      if (present(idx)) then
        nml__status = NML_ERR_INVALID_INDEX
        if (present(errmsg)) errmsg = "index not supported for 'choice'"
        return
      end if
      if (nml__obj%data%choice == -huge(nml__obj%data%choice)) nml__status = NML_ERR_NOT_SET
    case ("limit")
      if (present(idx)) then
        nml__status = NML_ERR_INVALID_INDEX
        if (present(errmsg)) errmsg = "index not supported for 'limit'"
        return
      end if
      if (nml__obj%data%limit == -huge(nml__obj%data%limit)) nml__status = NML_ERR_NOT_SET
    case ("upper")
      if (present(idx)) then
        nml__status = NML_ERR_INVALID_INDEX
        if (present(errmsg)) errmsg = "index not supported for 'upper'"
        return
      end if
      if (nml__obj%data%upper == -huge(nml__obj%data%upper)) nml__status = NML_ERR_NOT_SET
    case default
      nml__status = NML_ERR_INVALID_NAME
      if (present(errmsg)) errmsg = "unknown field: " // trim(name)
    end select
    if (nml__status == NML_ERR_NOT_SET .and. present(errmsg)) then
      if (len_trim(errmsg) == 0) errmsg = "field not set: " // trim(name)
    end if
  end function nml_constraints_is_set

  !> \brief Validate required values and constraints
  integer function nml_constraints_is_valid(nml__obj, errmsg) result(nml__status)
    class(nml_constraints_t), intent(in) :: nml__obj !< namelist instance
    character(len=*), intent(out), optional :: errmsg !< error message for non-OK status values
    integer :: nml__istat

    nml__status = NML_OK
    if (present(errmsg)) errmsg = ""
    if (.not. nml__obj%is_configured) then
      nml__status = NML_ERR_NOT_SET
      if (present(errmsg)) errmsg = "namelist not configured; call set or from_file"
      return
    end if

    ! enum constraints
    nml__istat = nml__obj%is_set("choice", errmsg=errmsg)
    if (nml__istat == NML_OK) then
      if (.not. choice__in_enum(nml__obj%data%choice)) then
        nml__status = NML_ERR_ENUM
        if (present(errmsg)) errmsg = "enum constraint failed: choice"
        return
      end if
    else if (nml__istat /= NML_ERR_NOT_SET) then
      nml__status = nml__istat
      return
    end if
    ! bounds constraints
    nml__istat = nml__obj%is_set("choice", errmsg=errmsg)
    if (nml__istat == NML_OK) then
      if (.not. choice__in_bounds(nml__obj%data%choice)) then
        nml__status = NML_ERR_BOUNDS
        if (present(errmsg)) errmsg = "bounds constraint failed: choice"
        return
      end if
    else if (nml__istat /= NML_ERR_NOT_SET) then
      nml__status = nml__istat
      return
    end if
    nml__istat = nml__obj%is_set("limit", errmsg=errmsg)
    if (nml__istat == NML_OK) then
      if (.not. limit__in_bounds(nml__obj%data%limit)) then
        nml__status = NML_ERR_BOUNDS
        if (present(errmsg)) errmsg = "bounds constraint failed: limit"
        return
      end if
    else if (nml__istat /= NML_ERR_NOT_SET) then
      nml__status = nml__istat
      return
    end if
    nml__istat = nml__obj%is_set("upper", errmsg=errmsg)
    if (nml__istat == NML_OK) then
      if (.not. upper__in_bounds(nml__obj%data%upper)) then
        nml__status = NML_ERR_BOUNDS
        if (present(errmsg)) errmsg = "bounds constraint failed: upper"
        return
      end if
    else if (nml__istat /= NML_ERR_NOT_SET) then
      nml__status = nml__istat
      return
    end if
  end function nml_constraints_is_valid

end module nml_constraints
