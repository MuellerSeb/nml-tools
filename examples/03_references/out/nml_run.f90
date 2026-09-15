!> \file nml_run.f90
!> \copydoc nml_run

!> \brief Reference-driven run configuration
!> \details Configuration composed from a reusable root schema and local fields.
module nml_run
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
    to__lower, &
    label_len, &
    n_stations__dim_default
  use ieee_arithmetic, only: nml__ieee_value => ieee_value, &
    nml__ieee_quiet_nan => ieee_quiet_nan, nml__ieee_is_nan => ieee_is_nan
  ! kind specifiers listed in the nml-tools configuration file
  use iso_fortran_env, only: &
    i4=>int32, &
    dp=>real64

  implicit none

  ! default values
  character(len=label_len), parameter, public :: label__default = "reference-example"
  real(dp), parameter, public :: station_weights__default(2) = [0.5_dp, 1.0_dp]
  character(len=label_len), parameter, public :: method__default = "RK2"
  real(dp), parameter, public :: relaxation__default = 0.25_dp

  ! enum values
  character(len=label_len), parameter, public :: &
    method__enum_values(3) = [character(len=label_len) :: "Euler", "RK2", "RK4"]

  ! bounds values
  integer(i4), parameter, public :: steps__min = 1_i4
  integer(i4), parameter, public :: steps__max = 10000_i4
  real(dp), parameter, public :: station_weights__min = 0.0_dp
  real(dp), parameter, public :: relaxation__min_excl = 0.0_dp
  real(dp), parameter, public :: relaxation__max = 0.5_dp

  private :: nml_run_read__from_file

  !> \class nml_run_data_t
  !> \brief Schema-backed values for run
  type, public :: nml_run_data_t
    character(len=label_len) :: label !< Run label
    integer(i4) :: steps !< Simulation steps
    real(dp), allocatable, dimension(:) :: station_weights !< Station weights
    character(len=label_len) :: method !< Time integration method
    real(dp) :: relaxation !< Relaxation factor
  end type nml_run_data_t

  !> \class nml_run_dims_t
  !> \brief Runtime dimensions for run
  type, public :: nml_run_dims_t
    integer :: n_stations = n_stations__dim_default !< runtime dimension for n_stations
  end type nml_run_dims_t

  !> \class nml_run_t
  !> \brief Reference-driven run configuration
  !> \details Configuration composed from a reusable root schema and local fields.
  type, public :: nml_run_t
    type(nml_run_data_t) :: data !< schema-backed namelist values
    type(nml_run_dims_t) :: dims !< runtime array dimensions
    logical :: is_configured = .false. !< whether the namelist has been configured
  contains
    procedure :: init => nml_run_init
    procedure :: set_dims => nml_run_set_dims
    procedure :: from_file => nml_run_from_file
    procedure :: set => nml_run_set
    procedure :: is_set => nml_run_is_set
    procedure :: is_valid => nml_run_is_valid
  end type nml_run_t

contains

  !> \brief Check whether a value is part of an enum
  elemental logical function method__in_enum(val, allow_missing) result(in_enum)
    character(len=*), intent(in) :: val !< value to check
    logical, intent(in), optional :: allow_missing !< allow sentinel values as valid

    if (present(allow_missing)) then
      if (allow_missing) then
        if (val == achar(0)) then
          in_enum = .true.
          return
        end if
      end if
    end if
    in_enum = any(trim(val) == method__enum_values)
  end function method__in_enum

  !> \brief Check whether a value is within bounds
  elemental logical function steps__in_bounds(val, allow_missing) result(in_bounds)
    integer(i4), intent(in) :: val !< value to check
    logical, intent(in), optional :: allow_missing !< allow sentinel values as valid

    if (present(allow_missing)) then
      if (allow_missing) then
        if (val == -huge(val)) then
          in_bounds = .true.
          return
        end if
      end if
    end if

    in_bounds = .true.
    if (val < steps__min) in_bounds = .false.
    if (val > steps__max) in_bounds = .false.
  end function steps__in_bounds

  !> \brief Check whether a value is within bounds
  elemental logical function station_weights__in_bounds(val, allow_missing) result(in_bounds)
    real(dp), intent(in) :: val !< value to check
    logical, intent(in), optional :: allow_missing !< allow sentinel values as valid

    if (present(allow_missing)) then
      if (allow_missing) then
        if (nml__ieee_is_nan(val)) then
          in_bounds = .true.
          return
        end if
      end if
    end if

    in_bounds = .true.
    if (val < station_weights__min) in_bounds = .false.
  end function station_weights__in_bounds

  !> \brief Check whether a value is within bounds
  elemental logical function relaxation__in_bounds(val, allow_missing) result(in_bounds)
    real(dp), intent(in) :: val !< value to check
    logical, intent(in), optional :: allow_missing !< allow sentinel values as valid

    if (present(allow_missing)) then
      if (allow_missing) then
        if (nml__ieee_is_nan(val)) then
          in_bounds = .true.
          return
        end if
      end if
    end if

    in_bounds = .true.
    if (val <= relaxation__min_excl) in_bounds = .false.
    if (val > relaxation__max) in_bounds = .false.
  end function relaxation__in_bounds

  !> \brief Initialize defaults and sentinels for run
  integer function nml_run_init(nml__obj, errmsg) result(nml__status)
    class(nml_run_t), intent(inout) :: nml__obj !< namelist instance
    character(len=*), intent(out), optional :: errmsg !< error message for non-OK status values

    nml__status = NML_OK
    if (present(errmsg)) errmsg = ""
    nml__obj%is_configured = .false.

    ! allocate runtime-sized fields
    if (allocated(nml__obj%data%station_weights)) deallocate(nml__obj%data%station_weights)
    allocate(nml__obj%data%station_weights(nml__obj%dims%n_stations))

    ! sentinel values for required/optional parameters
    nml__obj%data%steps = -huge(nml__obj%data%steps) ! sentinel for required integer
    ! default values
    nml__obj%data%label = label__default
    nml__obj%data%station_weights = reshape( &
      station_weights__default, &
      shape=[nml__obj%dims%n_stations], &
      pad=station_weights__default)
    nml__obj%data%method = method__default
    nml__obj%data%relaxation = relaxation__default
  end function nml_run_init

  !> \brief Reset runtime dimensions for run
  integer function nml_run_set_dims(nml__obj, &
    n_stations, &
    errmsg) result(nml__status)
    class(nml_run_t), intent(inout) :: nml__obj !< namelist instance
    integer, intent(in), optional :: n_stations !< runtime dimension override for n_stations
    integer :: candidate__n_stations
    character(len=*), intent(out), optional :: errmsg !< error message for non-OK status values

    nml__status = NML_OK
    if (present(errmsg)) errmsg = ""
    if (present(n_stations)) then
      candidate__n_stations = n_stations
    else
      candidate__n_stations = n_stations__dim_default
    end if
    if (candidate__n_stations <= 0) then
      nml__status = NML_ERR_INVALID_INDEX
      if (present(errmsg)) errmsg = "dimension 'n_stations' must be positive"
      return
    end if
    if (candidate__n_stations < 2) then
      nml__status = NML_ERR_INVALID_INDEX
      if (present(errmsg)) errmsg = "shape constants for 'station_weights' must allow at least 2 default values"
      return
    end if
    nml__obj%dims%n_stations = candidate__n_stations

    ! deallocate runtime-sized fields; init/set/from_file allocate them again
    if (allocated(nml__obj%data%station_weights)) deallocate(nml__obj%data%station_weights)
    nml__obj%is_configured = .false.
  end function nml_run_set_dims


  !> \brief Read run namelist from file
  integer function nml_run_from_file(nml__obj, file, errmsg) result(nml__status)
    class(nml_run_t), intent(inout) :: nml__obj !< namelist instance
    character(len=*), intent(in) :: file !< path to namelist file
    character(len=*), intent(out), optional :: errmsg !< error message for non-OK status values

    nml__status = nml_run_read__from_file(nml__obj, file, errmsg)
  end function nml_run_from_file

  integer function nml_run_read__from_file(nml__obj, nml__file, errmsg) &
    result(nml__status)
    class(nml_run_t), intent(inout) :: nml__obj
    character(len=*), intent(in) :: nml__file
    character(len=*), intent(out), optional :: errmsg
    ! namelist variables
    character(len=label_len) :: label
    integer(i4) :: steps
    real(dp), allocatable, dimension(:) :: station_weights
    character(len=label_len) :: method
    real(dp) :: relaxation
    ! locals
    type(nml_file_t) :: nml__reader
    integer :: nml__iostat
    integer :: nml__close_status
    character(len=nml_line_buffer) :: nml__iomsg

    namelist /run/ &
      label, &
      steps, &
      station_weights, &
      method, &
      relaxation

    nml__status = nml__obj%init(errmsg=errmsg)
    if (nml__status /= NML_OK) return
    ! allocate local namelist variables matching runtime-sized fields
    if (allocated(station_weights)) deallocate(station_weights)
    allocate(station_weights(nml__obj%dims%n_stations))
    label = nml__obj%data%label
    steps = nml__obj%data%steps
    station_weights = nml__obj%data%station_weights
    method = nml__obj%data%method
    relaxation = nml__obj%data%relaxation

    nml__status = nml__reader%open(nml__file, errmsg=errmsg)
    if (nml__status /= NML_OK) return

    nml__status = nml__reader%find("run", errmsg=errmsg)
    if (nml__status /= NML_OK) then
      nml__close_status = nml__reader%close()
      return
    end if

    ! read namelist
    read(nml__reader%unit, nml=run, iostat=nml__iostat, iomsg=nml__iomsg)
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
    nml__obj%data%label = label
    nml__obj%data%steps = steps
    nml__obj%data%station_weights = station_weights
    nml__obj%data%method = method
    nml__obj%data%relaxation = relaxation

    ! mark as configured
    nml__obj%is_configured = .true.
    nml__status = NML_OK
  end function nml_run_read__from_file

  !> \brief Set run values
  integer function nml_run_set(nml__obj, &
    steps, &
    label, &
    station_weights, &
    method, &
    relaxation, &
    errmsg) result(nml__status)

    class(nml_run_t), intent(inout) :: nml__obj !< namelist instance
    character(len=*), intent(out), optional :: errmsg !< error message for non-OK status values
    integer(i4), intent(in) :: steps !< Simulation steps
    character(len=*), intent(in), optional :: label !< Run label
    real(dp), dimension(:), intent(in), optional :: station_weights !< Station weights
    character(len=*), intent(in), optional :: method !< Time integration method
    real(dp), intent(in), optional :: relaxation !< Relaxation factor
    nml__status = nml__obj%init(errmsg=errmsg)
    if (nml__status /= NML_OK) return

    ! required parameters
    nml__obj%data%steps = steps
    ! override with provided values
    if (present(label)) nml__obj%data%label = label
    if (present(station_weights)) then
      if (size(station_weights, 1) > size(nml__obj%data%station_weights, 1)) then
        nml__status = NML_ERR_INVALID_INDEX
        if (present(errmsg)) errmsg = "dimension 1 exceeds bounds for 'station_weights'"
        return
      end if
      nml__obj%data%station_weights( &
        1:size(station_weights, 1)) = station_weights
    end if
    if (present(method)) nml__obj%data%method = method
    if (present(relaxation)) nml__obj%data%relaxation = relaxation

    ! mark as configured
    nml__obj%is_configured = .true.
    nml__status = NML_OK
  end function nml_run_set

  !> \brief Check whether a namelist value was set
  integer function nml_run_is_set(nml__obj, name, idx, errmsg) result(nml__status)
    class(nml_run_t), intent(in) :: nml__obj !< namelist instance
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
    case ("label")
      if (present(idx)) then
        nml__status = NML_ERR_INVALID_INDEX
        if (present(errmsg)) errmsg = "index not supported for 'label'"
        return
      end if
    case ("steps")
      if (present(idx)) then
        nml__status = NML_ERR_INVALID_INDEX
        if (present(errmsg)) errmsg = "index not supported for 'steps'"
        return
      end if
      if (nml__obj%data%steps == -huge(nml__obj%data%steps)) nml__status = NML_ERR_NOT_SET
    case ("station_weights")
      if (.not. allocated(nml__obj%data%station_weights)) then
        nml__status = NML_ERR_NOT_SET
        return
      end if
      if (present(idx)) then
        nml__status = idx__check(idx, shape(nml__obj%data%station_weights), &
          "station_weights", errmsg)
        if (nml__status /= NML_OK) return
      else
      end if
    case ("method")
      if (present(idx)) then
        nml__status = NML_ERR_INVALID_INDEX
        if (present(errmsg)) errmsg = "index not supported for 'method'"
        return
      end if
    case ("relaxation")
      if (present(idx)) then
        nml__status = NML_ERR_INVALID_INDEX
        if (present(errmsg)) errmsg = "index not supported for 'relaxation'"
        return
      end if
    case default
      nml__status = NML_ERR_INVALID_NAME
      if (present(errmsg)) errmsg = "unknown field: " // trim(name)
    end select
    if (nml__status == NML_ERR_NOT_SET .and. present(errmsg)) then
      if (len_trim(errmsg) == 0) errmsg = "field not set: " // trim(name)
    end if
  end function nml_run_is_set

  !> \brief Validate required values and constraints
  integer function nml_run_is_valid(nml__obj, errmsg) result(nml__status)
    class(nml_run_t), intent(in) :: nml__obj !< namelist instance
    character(len=*), intent(out), optional :: errmsg !< error message for non-OK status values
    integer :: nml__istat

    nml__status = NML_OK
    if (present(errmsg)) errmsg = ""
    if (.not. nml__obj%is_configured) then
      nml__status = NML_ERR_NOT_SET
      if (present(errmsg)) errmsg = "namelist not configured; call set or from_file"
      return
    end if

    ! required parameters
    nml__istat = nml__obj%is_set("steps", errmsg=errmsg)
    if (nml__istat == NML_ERR_NOT_SET) then
      nml__status = NML_ERR_REQUIRED
      if (present(errmsg)) then
        if (len_trim(errmsg) == 0) then
          errmsg = "field not set: steps"
        end if
        errmsg = "required " // trim(errmsg)
      end if
      return
    end if
    if (nml__istat /= NML_OK) then
      nml__status = nml__istat
      return
    end if
    ! enum constraints
    nml__istat = nml__obj%is_set("method", errmsg=errmsg)
    if (nml__istat == NML_OK) then
      if (.not. method__in_enum(nml__obj%data%method)) then
        nml__status = NML_ERR_ENUM
        if (present(errmsg)) errmsg = "enum constraint failed: method"
        return
      end if
    else if (nml__istat /= NML_ERR_NOT_SET) then
      nml__status = nml__istat
      return
    end if
    ! bounds constraints
    nml__istat = nml__obj%is_set("steps", errmsg=errmsg)
    if (nml__istat == NML_OK) then
      if (.not. steps__in_bounds(nml__obj%data%steps)) then
        nml__status = NML_ERR_BOUNDS
        if (present(errmsg)) errmsg = "bounds constraint failed: steps"
        return
      end if
    else if (nml__istat /= NML_ERR_NOT_SET) then
      nml__status = nml__istat
      return
    end if
    if (allocated(nml__obj%data%station_weights)) then
    if (.not. all(station_weights__in_bounds(nml__obj%data%station_weights, allow_missing=.true.))) then
      nml__status = NML_ERR_BOUNDS
      if (present(errmsg)) errmsg = "bounds constraint failed: station_weights"
      return
    end if
    end if
    nml__istat = nml__obj%is_set("relaxation", errmsg=errmsg)
    if (nml__istat == NML_OK) then
      if (.not. relaxation__in_bounds(nml__obj%data%relaxation)) then
        nml__status = NML_ERR_BOUNDS
        if (present(errmsg)) errmsg = "bounds constraint failed: relaxation"
        return
      end if
    else if (nml__istat /= NML_ERR_NOT_SET) then
      nml__status = nml__istat
      return
    end if
  end function nml_run_is_valid

end module nml_run
