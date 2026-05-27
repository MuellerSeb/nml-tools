!> \file nml_run.f90
!> \copydoc nml_run

!> \brief Derived-type configuration
!> \details Demonstrates referenced reusable and inline imported derived types.
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
    NML_ERR_INVALID_HANDLE, &
    period_t, &
    period_label_len, &
    n_periods_default=>n_periods, &
    station_label_len, &
    NML_ERR_PARTLY_SET
  ! kind specifiers listed in the nml-tools configuration file
  use iso_fortran_env, only: &
    i4=>int32
  use application_types, only: station_t
  use iso_c_binding, only: c_f_pointer, c_intptr_t, c_null_ptr, c_ptr

  implicit none

  ! bounds values
  integer(i4), parameter, public :: period_start_year_min = 1800_i4
  integer(i4), parameter, public :: period_start_year_max = 2200_i4
  integer(i4), parameter, public :: periods_start_year_min = 1800_i4
  integer(i4), parameter, public :: periods_start_year_max = 2200_i4
  integer(i4), parameter, public :: station_code_min = 1_i4

  !> \class nml_run_t
  !> \brief Derived-type configuration
  !> \details Demonstrates referenced reusable and inline imported derived types.
  type, public :: nml_run_t
    logical :: is_configured = .false. !< whether the namelist has been configured
    integer :: dim_n_periods = n_periods_default !< runtime dimension for n_periods
    type(period_t) :: period !< Main simulation period
    type(period_t), allocatable, dimension(:) :: periods !< Comparison periods
    type(station_t) :: station !< Selected station
  contains
    procedure :: init => nml_run_init
    procedure :: init_type => nml_run_init_type
    procedure :: set_dims => nml_run_set_dims
    procedure :: from_file => nml_run_from_file
    procedure :: set => nml_run_set
    procedure :: is_set => nml_run_is_set
    procedure :: is_valid => nml_run_is_valid
  end type nml_run_t

contains

  !> \brief Check whether a value is within bounds
  elemental logical function period_start_year_in_bounds(val, allow_missing) result(in_bounds)
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
    if (val < period_start_year_min) in_bounds = .false.
    if (val > period_start_year_max) in_bounds = .false.
  end function period_start_year_in_bounds

  !> \brief Check whether a value is within bounds
  elemental logical function periods_start_year_in_bounds(val, allow_missing) result(in_bounds)
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
    if (val < periods_start_year_min) in_bounds = .false.
    if (val > periods_start_year_max) in_bounds = .false.
  end function periods_start_year_in_bounds

  !> \brief Check whether a value is within bounds
  elemental logical function station_code_in_bounds(val, allow_missing) result(in_bounds)
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
    if (val < station_code_min) in_bounds = .false.
  end function station_code_in_bounds

  !> \brief Resolve an opaque C pointer handle to a nml_run_t pointer
  subroutine nml_run_resolve_handle(handle, this, status, errmsg)
    integer(c_intptr_t), intent(in) :: handle !< opaque handle to a nml_run_t instance
    type(nml_run_t), pointer :: this !< resolved namelist pointer
    integer, intent(out) :: status !< nml-tools status code
    character(len=*), intent(out), optional :: errmsg !< error message for non-OK status values
    type(c_ptr) :: ptr

    if (present(errmsg)) errmsg = ""
    nullify(this)
    if (handle == 0_c_intptr_t) then
      status = NML_ERR_INVALID_HANDLE
      if (present(errmsg)) errmsg = "zero handle"
      return
    end if
    ptr = transfer(handle, c_null_ptr)
    call c_f_pointer(ptr, this)
    status = NML_OK
  end subroutine nml_run_resolve_handle

  !> \brief Initialize defaults and sentinels for run
  integer function nml_run_init(this, errmsg) result(status)
    class(nml_run_t), intent(inout) :: this !< namelist instance
    character(len=*), intent(out), optional :: errmsg !< error message for non-OK status values

    status = NML_OK
    if (present(errmsg)) errmsg = ""
    this%is_configured = .false.

    ! allocate runtime-sized fields
    if (allocated(this%periods)) deallocate(this%periods)
    allocate(this%periods(this%dim_n_periods))

    ! sentinel values for required/optional parameters
    this%period%start_year = -huge(this%period%start_year) ! sentinel for derived component start_year
    this%period%end_year = -huge(this%period%end_year) ! sentinel for derived component end_year
    this%period%label = "period"
    this%periods%start_year = -huge(this%periods%start_year) ! sentinel for derived component start_year
    this%periods%end_year = -huge(this%periods%end_year) ! sentinel for derived component end_year
    this%periods%label = "period"
    this%station%code = -huge(this%station%code) ! sentinel for derived component code
    this%station%label = "unknown"
  end function nml_run_init

  !> \brief Initialize one concrete derived value with its field-specific defaults
  integer function nml_run_init_type(this, &
    period, &
    periods, &
    station, &
    errmsg) result(status)
    class(nml_run_t), intent(in) :: this !< parent namelist instance
    type(period_t), intent(inout), optional :: period !< Main simulation period
    type(period_t), dimension(:), allocatable, intent(inout), optional :: periods !< Comparison periods
    type(station_t), intent(inout), optional :: station !< Selected station
    character(len=*), intent(out), optional :: errmsg !< error message for non-OK status values
    integer :: selected

    status = NML_OK
    if (present(errmsg)) errmsg = ""
    selected = 0
    if (present(period)) selected = selected + 1
    if (present(periods)) selected = selected + 1
    if (present(station)) selected = selected + 1
    if (selected /= 1) then
      status = NML_ERR_INVALID_NAME
      if (present(errmsg)) errmsg = "init_type requires exactly one derived field argument"
      return
    end if
    if (present(period)) then
      period%start_year = -huge(period%start_year) ! sentinel for derived component start_year
      period%end_year = -huge(period%end_year) ! sentinel for derived component end_year
      period%label = "period"
    end if
    if (present(periods)) then
      if (allocated(periods)) deallocate(periods)
      allocate(periods(this%dim_n_periods))
      periods%start_year = -huge(periods%start_year) ! sentinel for derived component start_year
      periods%end_year = -huge(periods%end_year) ! sentinel for derived component end_year
      periods%label = "period"
    end if
    if (present(station)) then
      station%code = -huge(station%code) ! sentinel for derived component code
      station%label = "unknown"
    end if
  end function nml_run_init_type

  !> \brief Reset runtime dimensions for run
  integer function nml_run_set_dims(this, &
    n_periods, &
    errmsg) result(status)
    class(nml_run_t), intent(inout) :: this !< namelist instance
    integer, intent(in), optional :: n_periods !< runtime dimension override for n_periods
    integer :: candidate_n_periods
    character(len=*), intent(out), optional :: errmsg !< error message for non-OK status values

    status = NML_OK
    if (present(errmsg)) errmsg = ""
    if (present(n_periods)) then
      candidate_n_periods = n_periods
    else
      candidate_n_periods = n_periods_default
    end if
    if (candidate_n_periods <= 0) then
      status = NML_ERR_INVALID_INDEX
      if (present(errmsg)) errmsg = "dimension 'n_periods' must be positive"
      return
    end if
    this%dim_n_periods = candidate_n_periods

    ! deallocate runtime-sized fields; init/set/from_file allocate them again
    if (allocated(this%periods)) deallocate(this%periods)
    this%is_configured = .false.
  end function nml_run_set_dims


  !> \brief Read run namelist from file
  integer function nml_run_from_file(this, file, errmsg) result(status)
    class(nml_run_t), intent(inout) :: this !< namelist instance
    character(len=*), intent(in) :: file !< path to namelist file
    character(len=*), intent(out), optional :: errmsg !< error message for non-OK status values
    ! namelist variables
    type(period_t) :: period
    type(period_t), allocatable, dimension(:) :: periods
    type(station_t) :: station
    ! locals
    type(nml_file_t) :: nml
    integer :: iostat
    integer :: close_status
    character(len=nml_line_buffer) :: iomsg

    namelist /run/ &
      period, &
      periods, &
      station

    status = this%init(errmsg=errmsg)
    if (status /= NML_OK) return
    ! allocate local namelist variables matching runtime-sized fields
    if (allocated(periods)) deallocate(periods)
    allocate(periods(this%dim_n_periods))
    period = this%period
    periods = this%periods
    station = this%station

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
    this%period = period
    this%periods = periods
    this%station = station
    ! validate and canonicalize imported character components
    if (len(this%station%label) < station_label_len) then
      status = NML_ERR_BOUNDS
      if (present(errmsg)) errmsg = "imported string storage too short: station%label"
      return
    end if
    if (len(this%station%label) > station_label_len) this%station%label(station_label_len + 1:) = ""

    ! mark as configured
    this%is_configured = .true.
    status = NML_OK
  end function nml_run_from_file

  !> \brief Set run values
  integer function nml_run_set(this, &
    period, &
    periods, &
    station, &
    errmsg) result(status)

    class(nml_run_t), intent(inout) :: this !< namelist instance
    character(len=*), intent(out), optional :: errmsg !< error message for non-OK status values
    type(period_t), intent(in) :: period !< Main simulation period
    type(period_t), dimension(:), intent(in) :: periods !< Comparison periods
    type(station_t), intent(in) :: station !< Selected station
    integer :: &
      lb_1, &
      ub_1

    status = this%init(errmsg=errmsg)
    if (status /= NML_OK) return

    ! required parameters
    this%period = period
    if (size(periods, 1) > size(this%periods, 1)) then
      status = NML_ERR_INVALID_INDEX
      if (present(errmsg)) errmsg = "dimension 1 exceeds bounds for 'periods'"
      return
    end if
    lb_1 = lbound(this%periods, 1)
    ub_1 = lb_1 + size(periods, 1) - 1
    this%periods(lb_1:ub_1) = periods
    this%station = station
    ! validate and canonicalize imported character components
    if (len(this%station%label) < station_label_len) then
      status = NML_ERR_BOUNDS
      if (present(errmsg)) errmsg = "imported string storage too short: station%label"
      return
    end if
    if (len(this%station%label) > station_label_len) this%station%label(station_label_len + 1:) = ""

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
    case ("period%start_year")
      if (present(idx)) then
        status = NML_ERR_INVALID_INDEX
        if (present(errmsg)) errmsg = "index not supported for 'period'"
        return
      end if
      if (this%period%start_year == -huge(this%period%start_year)) status = NML_ERR_NOT_SET
    case ("period%end_year")
      if (present(idx)) then
        status = NML_ERR_INVALID_INDEX
        if (present(errmsg)) errmsg = "index not supported for 'period'"
        return
      end if
      if (this%period%end_year == -huge(this%period%end_year)) status = NML_ERR_NOT_SET
    case ("period%label")
      if (present(idx)) then
        status = NML_ERR_INVALID_INDEX
        if (present(errmsg)) errmsg = "index not supported for 'period'"
        return
      end if
    case ("period")
      if (present(idx)) then
        status = NML_ERR_INVALID_INDEX
        if (present(errmsg)) errmsg = "index not supported for 'period'"
        return
      end if
      if (this%period%start_year == -huge(this%period%start_year) .and. &
            this%period%end_year == -huge(this%period%end_year)) then
        status = NML_ERR_NOT_SET
      else if (this%period%start_year == -huge(this%period%start_year) .or. &
                 this%period%end_year == -huge(this%period%end_year)) then
        status = NML_ERR_PARTLY_SET
      end if
    case ("periods%start_year")
      if (.not. allocated(this%periods)) then
        status = NML_ERR_NOT_SET
        return
      end if
      if (present(idx)) then
        status = idx_check(idx, lbound(this%periods), ubound(this%periods), &
          "periods", errmsg)
        if (status /= NML_OK) return
        if (this%periods(idx(1))%start_year == -huge(this%periods(idx(1))%start_year)) status = NML_ERR_NOT_SET
      else
        if (all(this%periods%start_year == -huge(this%periods%start_year))) status = NML_ERR_NOT_SET
      end if
    case ("periods%end_year")
      if (.not. allocated(this%periods)) then
        status = NML_ERR_NOT_SET
        return
      end if
      if (present(idx)) then
        status = idx_check(idx, lbound(this%periods), ubound(this%periods), &
          "periods", errmsg)
        if (status /= NML_OK) return
        if (this%periods(idx(1))%end_year == -huge(this%periods(idx(1))%end_year)) status = NML_ERR_NOT_SET
      else
        if (all(this%periods%end_year == -huge(this%periods%end_year))) status = NML_ERR_NOT_SET
      end if
    case ("periods%label")
      if (.not. allocated(this%periods)) then
        status = NML_ERR_NOT_SET
        return
      end if
      if (present(idx)) then
        status = idx_check(idx, lbound(this%periods), ubound(this%periods), &
          "periods", errmsg)
        if (status /= NML_OK) return
      else
      end if
    case ("periods")
      if (.not. allocated(this%periods)) then
        status = NML_ERR_NOT_SET
        return
      end if
      if (present(idx)) then
        status = idx_check(idx, lbound(this%periods), ubound(this%periods), &
          "periods", errmsg)
        if (status /= NML_OK) return
        if (this%periods(idx(1))%start_year == -huge(this%periods(idx(1))%start_year) .and. &
              this%periods(idx(1))%end_year == -huge(this%periods(idx(1))%end_year)) then
          status = NML_ERR_NOT_SET
        else if (this%periods(idx(1))%start_year == -huge(this%periods(idx(1))%start_year) .or. &
                   this%periods(idx(1))%end_year == -huge(this%periods(idx(1))%end_year)) then
          status = NML_ERR_PARTLY_SET
        end if
      else
        if (all(this%periods%start_year == -huge(this%periods%start_year) .and. &
                  this%periods%end_year == -huge(this%periods%end_year))) then
          status = NML_ERR_NOT_SET
        else if (any(this%periods%start_year == -huge(this%periods%start_year) .or. &
                       this%periods%end_year == -huge(this%periods%end_year))) then
          status = NML_ERR_PARTLY_SET
        end if
      end if
    case ("station%code")
      if (present(idx)) then
        status = NML_ERR_INVALID_INDEX
        if (present(errmsg)) errmsg = "index not supported for 'station'"
        return
      end if
      if (this%station%code == -huge(this%station%code)) status = NML_ERR_NOT_SET
    case ("station%label")
      if (present(idx)) then
        status = NML_ERR_INVALID_INDEX
        if (present(errmsg)) errmsg = "index not supported for 'station'"
        return
      end if
    case ("station")
      if (present(idx)) then
        status = NML_ERR_INVALID_INDEX
        if (present(errmsg)) errmsg = "index not supported for 'station'"
        return
      end if
      if (this%station%code == -huge(this%station%code)) then
        status = NML_ERR_NOT_SET
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
    istat = this%is_set("period", errmsg=errmsg)
    if (istat == NML_ERR_NOT_SET) then
      status = NML_ERR_REQUIRED
      if (present(errmsg)) then
        if (len_trim(errmsg) == 0) then
          errmsg = "field not set: period"
        end if
        errmsg = "required " // trim(errmsg)
      end if
      return
    end if
    if (istat /= NML_OK) then
      status = istat
      return
    end if
    istat = this%is_set("periods", errmsg=errmsg)
    if (istat == NML_ERR_NOT_SET) then
      status = NML_ERR_REQUIRED
      if (present(errmsg)) then
        if (len_trim(errmsg) == 0) then
          errmsg = "field not set: periods"
        end if
        errmsg = "required " // trim(errmsg)
      end if
      return
    end if
    if (istat /= NML_OK) then
      status = istat
      return
    end if
    istat = this%is_set("station", errmsg=errmsg)
    if (istat == NML_ERR_NOT_SET) then
      status = NML_ERR_REQUIRED
      if (present(errmsg)) then
        if (len_trim(errmsg) == 0) then
          errmsg = "field not set: station"
        end if
        errmsg = "required " // trim(errmsg)
      end if
      return
    end if
    if (istat /= NML_OK) then
      status = istat
      return
    end if
    ! required derived values
    istat = this%is_set("period", errmsg=errmsg)
    if (istat == NML_ERR_NOT_SET) then
      status = NML_ERR_REQUIRED
      if (present(errmsg)) errmsg = "required field not set: period"
      return
    else if (istat /= NML_OK) then
      status = istat
      return
    end if
    istat = this%is_set("periods", errmsg=errmsg)
    if (istat == NML_ERR_NOT_SET) then
      status = NML_ERR_REQUIRED
      if (present(errmsg)) errmsg = "required field not set: periods"
      return
    else if (istat /= NML_OK) then
      status = istat
      return
    end if
    istat = this%is_set("station", errmsg=errmsg)
    if (istat == NML_ERR_NOT_SET) then
      status = NML_ERR_REQUIRED
      if (present(errmsg)) errmsg = "required field not set: station"
      return
    else if (istat /= NML_OK) then
      status = istat
      return
    end if
    ! bounds constraints
    istat = this%is_set("period%start_year", errmsg=errmsg)
    if (istat == NML_OK) then
      if (.not. period_start_year_in_bounds(this%period%start_year)) then
        status = NML_ERR_BOUNDS
        if (present(errmsg)) errmsg = "bounds constraint failed: period%start_year"
        return
      end if
    else if (istat /= NML_ERR_NOT_SET) then
      status = istat
      return
    end if
    if (allocated(this%periods)) then
    if (.not. all(periods_start_year_in_bounds(this%periods%start_year, allow_missing=.true.))) then
      status = NML_ERR_BOUNDS
      if (present(errmsg)) errmsg = "bounds constraint failed: periods%start_year"
      return
    end if
    end if
    istat = this%is_set("station%code", errmsg=errmsg)
    if (istat == NML_OK) then
      if (.not. station_code_in_bounds(this%station%code)) then
        status = NML_ERR_BOUNDS
        if (present(errmsg)) errmsg = "bounds constraint failed: station%code"
        return
      end if
    else if (istat /= NML_ERR_NOT_SET) then
      status = istat
      return
    end if
  end function nml_run_is_valid

end module nml_run
