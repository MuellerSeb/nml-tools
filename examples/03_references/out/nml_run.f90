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
    idx_check, &
    to_lower, &
    label_len, &
    n_stations_default=>n_stations
  use ieee_arithmetic, only: ieee_value, ieee_quiet_nan, ieee_is_nan
  ! kind specifiers listed in the nml-tools configuration file
  use iso_fortran_env, only: &
    i4=>int32, &
    dp=>real64

  implicit none

  ! default values
  character(len=label_len), parameter, public :: label_default = "reference-example"
  real(dp), parameter, public :: station_weights_default(2) = [0.5_dp, 1.0_dp]
  character(len=label_len), parameter, public :: method_default = "RK2"
  real(dp), parameter, public :: relaxation_default = 0.25_dp

  ! enum values
  character(len=label_len), parameter, public :: &
    method_enum_values(3) = [character(len=label_len) :: "Euler", "RK2", "RK4"]

  ! bounds values
  integer(i4), parameter, public :: steps_min = 1_i4
  integer(i4), parameter, public :: steps_max = 10000_i4
  real(dp), parameter, public :: station_weights_min = 0.0_dp
  real(dp), parameter, public :: relaxation_min_excl = 0.0_dp
  real(dp), parameter, public :: relaxation_max = 0.5_dp

  !> \class nml_run_t
  !> \brief Reference-driven run configuration
  !> \details Configuration composed from a reusable root schema and local fields.
  type, public :: nml_run_t
    logical :: is_configured = .false. !< whether the namelist has been configured
    integer :: dim_n_stations = n_stations_default !< runtime dimension for n_stations
    character(len=label_len) :: label !< Run label
    integer(i4) :: steps !< Simulation steps
    real(dp), allocatable, dimension(:) :: station_weights !< Station weights
    character(len=label_len) :: method !< Time integration method
    real(dp) :: relaxation !< Relaxation factor
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
  elemental logical function method_in_enum(val, allow_missing) result(in_enum)
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
    in_enum = any(trim(val) == method_enum_values)
  end function method_in_enum

  !> \brief Check whether a value is within bounds
  elemental logical function steps_in_bounds(val, allow_missing) result(in_bounds)
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
    if (val < steps_min) in_bounds = .false.
    if (val > steps_max) in_bounds = .false.
  end function steps_in_bounds

  !> \brief Check whether a value is within bounds
  elemental logical function station_weights_in_bounds(val, allow_missing) result(in_bounds)
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
    if (val < station_weights_min) in_bounds = .false.
  end function station_weights_in_bounds

  !> \brief Check whether a value is within bounds
  elemental logical function relaxation_in_bounds(val, allow_missing) result(in_bounds)
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
    if (val <= relaxation_min_excl) in_bounds = .false.
    if (val > relaxation_max) in_bounds = .false.
  end function relaxation_in_bounds

  !> \brief Initialize defaults and sentinels for run
  integer function nml_run_init(this, errmsg) result(status)
    class(nml_run_t), intent(inout) :: this !< namelist instance
    character(len=*), intent(out), optional :: errmsg !< error message for non-OK status values

    status = NML_OK
    if (present(errmsg)) errmsg = ""
    this%is_configured = .false.

    ! allocate runtime-sized fields
    if (allocated(this%station_weights)) deallocate(this%station_weights)
    allocate(this%station_weights(this%dim_n_stations))

    ! sentinel values for required/optional parameters
    this%steps = -huge(this%steps) ! sentinel for required integer
    ! default values
    this%label = label_default
    this%station_weights = reshape( &
      station_weights_default, &
      shape=[this%dim_n_stations], &
      pad=station_weights_default)
    this%method = method_default
    this%relaxation = relaxation_default
  end function nml_run_init

  !> \brief Reset runtime dimensions for run
  integer function nml_run_set_dims(this, &
    n_stations, &
    errmsg) result(status)
    class(nml_run_t), intent(inout) :: this !< namelist instance
    integer, intent(in), optional :: n_stations !< runtime dimension override for n_stations
    integer :: candidate_n_stations
    character(len=*), intent(out), optional :: errmsg !< error message for non-OK status values

    status = NML_OK
    if (present(errmsg)) errmsg = ""
    if (present(n_stations)) then
      candidate_n_stations = n_stations
    else
      candidate_n_stations = n_stations_default
    end if
    if (candidate_n_stations <= 0) then
      status = NML_ERR_INVALID_INDEX
      if (present(errmsg)) errmsg = "dimension 'n_stations' must be positive"
      return
    end if
    if (candidate_n_stations < 2) then
      status = NML_ERR_INVALID_INDEX
      if (present(errmsg)) errmsg = "shape constants for 'station_weights' must allow at least 2 default values"
      return
    end if
    this%dim_n_stations = candidate_n_stations

    ! deallocate runtime-sized fields; init/set/from_file allocate them again
    if (allocated(this%station_weights)) deallocate(this%station_weights)
    this%is_configured = .false.
  end function nml_run_set_dims


  !> \brief Read run namelist from file
  integer function nml_run_from_file(this, file, errmsg) result(status)
    class(nml_run_t), intent(inout) :: this !< namelist instance
    character(len=*), intent(in) :: file !< path to namelist file
    character(len=*), intent(out), optional :: errmsg !< error message for non-OK status values
    ! namelist variables
    character(len=label_len) :: label
    integer(i4) :: steps
    real(dp), allocatable, dimension(:) :: station_weights
    character(len=label_len) :: method
    real(dp) :: relaxation
    ! locals
    type(nml_file_t) :: nml
    integer :: iostat
    integer :: close_status
    character(len=nml_line_buffer) :: iomsg

    namelist /run/ &
      label, &
      steps, &
      station_weights, &
      method, &
      relaxation

    status = this%init(errmsg=errmsg)
    if (status /= NML_OK) return
    ! allocate local namelist variables matching runtime-sized fields
    if (allocated(station_weights)) deallocate(station_weights)
    allocate(station_weights(this%dim_n_stations))
    label = this%label
    steps = this%steps
    station_weights = this%station_weights
    method = this%method
    relaxation = this%relaxation

    status = nml%open(file, errmsg=errmsg)
    if (status /= NML_OK) return

    status = nml%find("run", errmsg=errmsg)
    if (status /= NML_OK) then
      close_status = nml%close()
      return
    end if

    ! read namelist
    read(nml%unit, nml=run, iostat=iostat, iomsg=iomsg)
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
    this%steps = steps
    this%station_weights = station_weights
    this%method = method
    this%relaxation = relaxation

    ! mark as configured
    this%is_configured = .true.
    status = NML_OK
  end function nml_run_from_file

  !> \brief Set run values
  integer function nml_run_set(this, &
    steps, &
    label, &
    station_weights, &
    method, &
    relaxation, &
    errmsg) result(status)

    class(nml_run_t), intent(inout) :: this !< namelist instance
    character(len=*), intent(out), optional :: errmsg !< error message for non-OK status values
    integer(i4), intent(in) :: steps !< Simulation steps
    character(len=*), intent(in), optional :: label !< Run label
    real(dp), dimension(:), intent(in), optional :: station_weights !< Station weights
    character(len=*), intent(in), optional :: method !< Time integration method
    real(dp), intent(in), optional :: relaxation !< Relaxation factor
    integer :: &
      lb_1, &
      ub_1

    status = this%init(errmsg=errmsg)
    if (status /= NML_OK) return

    ! required parameters
    this%steps = steps
    ! override with provided values
    if (present(label)) this%label = label
    if (present(station_weights)) then
      if (size(station_weights, 1) > size(this%station_weights, 1)) then
        status = NML_ERR_INVALID_INDEX
        if (present(errmsg)) errmsg = "dimension 1 exceeds bounds for 'station_weights'"
        return
      end if
      lb_1 = lbound(this%station_weights, 1)
      ub_1 = lb_1 + size(station_weights, 1) - 1
      this%station_weights(lb_1:ub_1) = station_weights
    end if
    if (present(method)) this%method = method
    if (present(relaxation)) this%relaxation = relaxation

    ! mark as configured
    this%is_configured = .true.
    status = NML_OK
  end function nml_run_set

  !> \brief Check whether a namelist value was set
  integer function nml_run_is_set(this, name, idx, errmsg) result(status)
    class(nml_run_t), intent(in) :: this !< namelist instance
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
    case ("steps")
      if (present(idx)) then
        status = NML_ERR_INVALID_INDEX
        if (present(errmsg)) errmsg = "index not supported for 'steps'"
        return
      end if
      if (this%steps == -huge(this%steps)) status = NML_ERR_NOT_SET
    case ("station_weights")
      if (.not. allocated(this%station_weights)) then
        status = NML_ERR_NOT_SET
        return
      end if
      if (present(idx)) then
        status = idx_check(idx, lbound(this%station_weights), ubound(this%station_weights), &
          "station_weights", errmsg)
        if (status /= NML_OK) return
      else
      end if
    case ("method")
      if (present(idx)) then
        status = NML_ERR_INVALID_INDEX
        if (present(errmsg)) errmsg = "index not supported for 'method'"
        return
      end if
    case ("relaxation")
      if (present(idx)) then
        status = NML_ERR_INVALID_INDEX
        if (present(errmsg)) errmsg = "index not supported for 'relaxation'"
        return
      end if
    case default
      status = NML_ERR_INVALID_NAME
      if (present(errmsg)) errmsg = "unknown field: " // trim(name)
    end select
    if (status == NML_ERR_NOT_SET .and. present(errmsg)) then
      if (len_trim(errmsg) == 0) errmsg = "field not set: " // trim(name)
    end if
  end function nml_run_is_set

  !> \brief Validate required values and constraints
  integer function nml_run_is_valid(this, errmsg) result(status)
    class(nml_run_t), intent(in) :: this !< namelist instance
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
    istat = this%is_set("steps", errmsg=errmsg)
    if (istat == NML_ERR_NOT_SET) then
      status = NML_ERR_REQUIRED
      if (present(errmsg)) then
        if (len_trim(errmsg) == 0) then
          errmsg = "field not set: steps"
        end if
        errmsg = "required " // trim(errmsg)
      end if
      return
    end if
    if (istat /= NML_OK) then
      status = istat
      return
    end if
    ! enum constraints
    istat = this%is_set("method", errmsg=errmsg)
    if (istat == NML_OK) then
      if (.not. method_in_enum(this%method)) then
        status = NML_ERR_ENUM
        if (present(errmsg)) errmsg = "enum constraint failed: method"
        return
      end if
    else if (istat /= NML_ERR_NOT_SET) then
      status = istat
      return
    end if
    ! bounds constraints
    istat = this%is_set("steps", errmsg=errmsg)
    if (istat == NML_OK) then
      if (.not. steps_in_bounds(this%steps)) then
        status = NML_ERR_BOUNDS
        if (present(errmsg)) errmsg = "bounds constraint failed: steps"
        return
      end if
    else if (istat /= NML_ERR_NOT_SET) then
      status = istat
      return
    end if
    if (allocated(this%station_weights)) then
    if (.not. all(station_weights_in_bounds(this%station_weights, allow_missing=.true.))) then
      status = NML_ERR_BOUNDS
      if (present(errmsg)) errmsg = "bounds constraint failed: station_weights"
      return
    end if
    end if
    istat = this%is_set("relaxation", errmsg=errmsg)
    if (istat == NML_OK) then
      if (.not. relaxation_in_bounds(this%relaxation)) then
        status = NML_ERR_BOUNDS
        if (present(errmsg)) errmsg = "bounds constraint failed: relaxation"
        return
      end if
    else if (istat /= NML_ERR_NOT_SET) then
      status = istat
      return
    end if
  end function nml_run_is_valid

end module nml_run
