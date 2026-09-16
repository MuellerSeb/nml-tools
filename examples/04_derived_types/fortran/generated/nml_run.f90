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
    idx__check, &
    to__lower, &
    NML_ERR_INVALID_HANDLE, &
    period_t, &
    period_label_len, &
    n_periods__dim_default, &
    station_label_len
  ! kind specifiers listed in the nml-tools configuration file
  use iso_fortran_env, only: &
    i4=>int32
  use application_types, only: station_t
  use iso_c_binding, only: c_f_pointer, c_intptr_t, c_null_ptr, c_ptr

  implicit none

  ! bounds values
  integer(i4), parameter, public :: period__start_year__min = 1800_i4
  integer(i4), parameter, public :: period__start_year__max = 2200_i4
  integer(i4), parameter, public :: periods__start_year__min = 1800_i4
  integer(i4), parameter, public :: periods__start_year__max = 2200_i4
  integer(i4), parameter, public :: station__code__min = 1_i4

  private :: nml_run_read__from_file

  !> \class nml_run_data_t
  !> \brief Schema-backed values for run
  type, public :: nml_run_data_t
    type(period_t) :: period !< Main simulation period
    type(period_t), allocatable, dimension(:) :: periods !< Comparison periods
    type(station_t) :: station !< Selected station
  end type nml_run_data_t

  !> \class nml_run_dims_t
  !> \brief Runtime dimensions for run
  type, public :: nml_run_dims_t
    integer :: n_periods = n_periods__dim_default !< runtime dimension for n_periods
  end type nml_run_dims_t

  !> \class nml_run_t
  !> \brief Derived-type configuration
  !> \details Demonstrates referenced reusable and inline imported derived types.
  type, public :: nml_run_t
    type(nml_run_data_t) :: data !< schema-backed namelist values
    type(nml_run_dims_t) :: dims !< runtime array dimensions
    logical :: is_configured = .false. !< whether the namelist has been configured
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
  elemental logical function period__start_year__in_bounds(val, allow_missing) result(in_bounds)
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
    if (val < period__start_year__min) in_bounds = .false.
    if (val > period__start_year__max) in_bounds = .false.
  end function period__start_year__in_bounds

  !> \brief Check whether a value is within bounds
  elemental logical function periods__start_year__in_bounds(val, allow_missing) result(in_bounds)
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
    if (val < periods__start_year__min) in_bounds = .false.
    if (val > periods__start_year__max) in_bounds = .false.
  end function periods__start_year__in_bounds

  !> \brief Check whether a value is within bounds
  elemental logical function station__code__in_bounds(val, allow_missing) result(in_bounds)
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
    if (val < station__code__min) in_bounds = .false.
  end function station__code__in_bounds

  !> \brief Resolve an opaque C pointer handle to a nml_run_t pointer
  subroutine nml_run_resolve_handle(nml__handle, nml__obj, nml__status, errmsg)
    integer(c_intptr_t), intent(in) :: nml__handle !< opaque handle to a nml_run_t instance
    type(nml_run_t), pointer :: nml__obj !< resolved namelist pointer
    integer, intent(out) :: nml__status !< nml-tools status code
    character(len=*), intent(out), optional :: errmsg !< error message for non-OK status values
    type(c_ptr) :: nml__ptr

    if (present(errmsg)) errmsg = ""
    nullify(nml__obj)
    if (nml__handle == 0_c_intptr_t) then
      nml__status = NML_ERR_INVALID_HANDLE
      if (present(errmsg)) errmsg = "zero handle"
      return
    end if
    nml__ptr = transfer(nml__handle, c_null_ptr)
    call c_f_pointer(nml__ptr, nml__obj)
    nml__status = NML_OK
  end subroutine nml_run_resolve_handle

  !> \brief Initialize defaults and sentinels for run
  integer function nml_run_init(nml__obj, errmsg) result(nml__status)
    class(nml_run_t), intent(inout) :: nml__obj !< namelist instance
    character(len=*), intent(out), optional :: errmsg !< error message for non-OK status values

    nml__status = NML_OK
    if (present(errmsg)) errmsg = ""
    nml__obj%is_configured = .false.

    ! derived values
    nml__status = nml__obj%init_type( &
      period=nml__obj%data%period, &
      periods=nml__obj%data%periods, &
      station=nml__obj%data%station, &
      errmsg=errmsg)
    if (nml__status /= NML_OK) return
  end function nml_run_init

  !> \brief Initialize derived values with their field-specific defaults
  integer function nml_run_init_type(nml__obj, &
    period, &
    periods, &
    station, &
    errmsg) result(nml__status)
    class(nml_run_t), intent(in) :: nml__obj !< parent namelist instance
    type(period_t), intent(inout), optional :: period !< Main simulation period
    type(period_t), dimension(:), allocatable, intent(inout), optional :: periods !< Comparison periods
    type(station_t), intent(inout), optional :: station !< Selected station
    character(len=*), intent(out), optional :: errmsg !< error message for non-OK status values

    nml__status = NML_OK
    if (present(errmsg)) errmsg = ""
    if (present(period)) then
      period%start_year = -huge(period%start_year) ! sentinel for derived component start_year
      period%end_year = -huge(period%end_year) ! sentinel for derived component end_year
      period%label = "main"
      period%start_year = 2000_i4
    end if
    if (present(periods)) then
      if (allocated(periods)) deallocate(periods)
      allocate(periods(nml__obj%dims%n_periods))
      periods%start_year = -huge(periods%start_year) ! sentinel for derived component start_year
      periods%end_year = -huge(periods%end_year) ! sentinel for derived component end_year
      periods%label = "period"
      periods%start_year = 1980_i4
      periods%end_year = 1999_i4
    end if
    if (present(station)) then
      station%code = -huge(station%code) ! sentinel for derived component code
      if (len(station%label) /= station_label_len) then
        nml__status = NML_ERR_BOUNDS
        if (present(errmsg)) errmsg = "imported string storage length mismatch: station%label"
        return
      end if
      station%label = "unknown"
    end if
  end function nml_run_init_type

  !> \brief Reset runtime dimensions for run
  integer function nml_run_set_dims(nml__obj, &
    n_periods, &
    errmsg) result(nml__status)
    class(nml_run_t), intent(inout) :: nml__obj !< namelist instance
    integer, intent(in), optional :: n_periods !< runtime dimension override for n_periods
    integer :: candidate__n_periods
    character(len=*), intent(out), optional :: errmsg !< error message for non-OK status values

    nml__status = NML_OK
    if (present(errmsg)) errmsg = ""
    if (present(n_periods)) then
      candidate__n_periods = n_periods
    else
      candidate__n_periods = n_periods__dim_default
    end if
    if (candidate__n_periods <= 0) then
      nml__status = NML_ERR_INVALID_INDEX
      if (present(errmsg)) errmsg = "dimension 'n_periods' must be positive"
      return
    end if
    nml__obj%dims%n_periods = candidate__n_periods

    ! deallocate runtime-sized fields; init/set/from_file allocate them again
    if (allocated(nml__obj%data%periods)) deallocate(nml__obj%data%periods)
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
    type(period_t) :: period
    type(period_t), allocatable, dimension(:) :: periods
    type(station_t) :: station
    ! locals
    type(nml_file_t) :: nml__reader
    integer :: nml__iostat
    integer :: nml__close_status
    character(len=nml_line_buffer) :: nml__iomsg

    namelist /run/ &
      period, &
      periods, &
      station

    nml__status = nml__obj%init(errmsg=errmsg)
    if (nml__status /= NML_OK) return
    ! allocate local namelist variables matching runtime-sized fields
    if (allocated(periods)) deallocate(periods)
    allocate(periods(nml__obj%dims%n_periods))
    period = nml__obj%data%period
    periods = nml__obj%data%periods
    station = nml__obj%data%station

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
    nml__obj%data%period = period
    nml__obj%data%periods = periods
    nml__obj%data%station = station

    ! mark as configured
    nml__obj%is_configured = .true.
    nml__status = NML_OK
  end function nml_run_read__from_file

  !> \brief Set run values
  integer function nml_run_set(nml__obj, &
    period, &
    periods, &
    station, &
    errmsg) result(nml__status)

    class(nml_run_t), intent(inout) :: nml__obj !< namelist instance
    character(len=*), intent(out), optional :: errmsg !< error message for non-OK status values
    type(period_t), intent(in) :: period !< Main simulation period
    type(station_t), intent(in) :: station !< Selected station
    type(period_t), dimension(:), intent(in), optional :: periods !< Comparison periods
    nml__status = nml__obj%init(errmsg=errmsg)
    if (nml__status /= NML_OK) return

    ! required parameters
    nml__obj%data%period = period
    nml__obj%data%station = station
    ! override with provided values
    if (present(periods)) then
      if (size(periods, 1) > size(nml__obj%data%periods, 1)) then
        nml__status = NML_ERR_INVALID_INDEX
        if (present(errmsg)) errmsg = "dimension 1 exceeds bounds for 'periods'"
        return
      end if
      nml__obj%data%periods( &
        1:size(periods, 1)) = periods
    end if

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
    case ("period%start_year")
      if (present(idx)) then
        nml__status = NML_ERR_INVALID_INDEX
        if (present(errmsg)) errmsg = "index not supported for 'period'"
        return
      end if
    case ("period%end_year")
      if (present(idx)) then
        nml__status = NML_ERR_INVALID_INDEX
        if (present(errmsg)) errmsg = "index not supported for 'period'"
        return
      end if
      if (nml__obj%data%period%end_year == -huge(nml__obj%data%period%end_year)) nml__status = NML_ERR_NOT_SET
    case ("period%label")
      if (present(idx)) then
        nml__status = NML_ERR_INVALID_INDEX
        if (present(errmsg)) errmsg = "index not supported for 'period'"
        return
      end if
    case ("period")
      if (present(idx)) then
        nml__status = NML_ERR_INVALID_INDEX
        if (present(errmsg)) errmsg = "index not supported for 'period'"
        return
      end if
      if (nml__obj%data%period%end_year == -huge(nml__obj%data%period%end_year)) then
        nml__status = NML_ERR_NOT_SET
      end if
    case ("periods%start_year")
      if (.not. allocated(nml__obj%data%periods)) then
        nml__status = NML_ERR_NOT_SET
        return
      end if
      if (present(idx)) then
        nml__status = idx__check(idx, shape(nml__obj%data%periods), &
          "periods", errmsg)
        if (nml__status /= NML_OK) return
      end if
    case ("periods%end_year")
      if (.not. allocated(nml__obj%data%periods)) then
        nml__status = NML_ERR_NOT_SET
        return
      end if
      if (present(idx)) then
        nml__status = idx__check(idx, shape(nml__obj%data%periods), &
          "periods", errmsg)
        if (nml__status /= NML_OK) return
      end if
    case ("periods%label")
      if (.not. allocated(nml__obj%data%periods)) then
        nml__status = NML_ERR_NOT_SET
        return
      end if
      if (present(idx)) then
        nml__status = idx__check(idx, shape(nml__obj%data%periods), &
          "periods", errmsg)
        if (nml__status /= NML_OK) return
      end if
    case ("periods")
      if (.not. allocated(nml__obj%data%periods)) then
        nml__status = NML_ERR_NOT_SET
        return
      end if
      if (present(idx)) then
        nml__status = idx__check(idx, shape(nml__obj%data%periods), &
          "periods", errmsg)
        if (nml__status /= NML_OK) return
      end if
    case ("station%code")
      if (present(idx)) then
        nml__status = NML_ERR_INVALID_INDEX
        if (present(errmsg)) errmsg = "index not supported for 'station'"
        return
      end if
      if (nml__obj%data%station%code == -huge(nml__obj%data%station%code)) nml__status = NML_ERR_NOT_SET
    case ("station%label")
      if (present(idx)) then
        nml__status = NML_ERR_INVALID_INDEX
        if (present(errmsg)) errmsg = "index not supported for 'station'"
        return
      end if
    case ("station")
      if (present(idx)) then
        nml__status = NML_ERR_INVALID_INDEX
        if (present(errmsg)) errmsg = "index not supported for 'station'"
        return
      end if
      if (nml__obj%data%station%code == -huge(nml__obj%data%station%code)) then
        nml__status = NML_ERR_NOT_SET
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
    nml__istat = nml__obj%is_set("period", errmsg=errmsg)
    if (nml__istat == NML_ERR_NOT_SET) then
      nml__status = NML_ERR_REQUIRED
      if (present(errmsg)) then
        if (len_trim(errmsg) == 0) then
          errmsg = "field not set: period"
        end if
        errmsg = "required " // trim(errmsg)
      end if
      return
    end if
    if (nml__istat /= NML_OK) then
      nml__status = nml__istat
      return
    end if
    nml__istat = nml__obj%is_set("station", errmsg=errmsg)
    if (nml__istat == NML_ERR_NOT_SET) then
      nml__status = NML_ERR_REQUIRED
      if (present(errmsg)) then
        if (len_trim(errmsg) == 0) then
          errmsg = "field not set: station"
        end if
        errmsg = "required " // trim(errmsg)
      end if
      return
    end if
    if (nml__istat /= NML_OK) then
      nml__status = nml__istat
      return
    end if
    ! bounds constraints
    nml__istat = nml__obj%is_set("period%start_year", errmsg=errmsg)
    if (nml__istat == NML_OK) then
      if (.not. period__start_year__in_bounds(nml__obj%data%period%start_year)) then
        nml__status = NML_ERR_BOUNDS
        if (present(errmsg)) errmsg = "bounds constraint failed: period%start_year"
        return
      end if
    else if (nml__istat /= NML_ERR_NOT_SET) then
      nml__status = nml__istat
      return
    end if
    if (allocated(nml__obj%data%periods)) then
    if (.not. all(periods__start_year__in_bounds(nml__obj%data%periods%start_year, allow_missing=.true.))) then
      nml__status = NML_ERR_BOUNDS
      if (present(errmsg)) errmsg = "bounds constraint failed: periods%start_year"
      return
    end if
    end if
    nml__istat = nml__obj%is_set("station%code", errmsg=errmsg)
    if (nml__istat == NML_OK) then
      if (.not. station__code__in_bounds(nml__obj%data%station%code)) then
        nml__status = NML_ERR_BOUNDS
        if (present(errmsg)) errmsg = "bounds constraint failed: station%code"
        return
      end if
    else if (nml__istat /= NML_ERR_NOT_SET) then
      nml__status = nml__istat
      return
    end if
  end function nml_run_is_valid

end module nml_run
