!> \file nml_config.f90
!> \copydoc nml_config

!> \brief Python binding config
!> \details Minimal namelist used by the pybind example.
!!
!! The generated f2py wrapper configures a persistent Fortran target instance
!! through an opaque integer handle.
!!
module nml_config
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
    str_len, &
    n_weights_default=>n_weights
  use ieee_arithmetic, only: ieee_value, ieee_quiet_nan, ieee_is_nan
  ! kind specifiers listed in the nml-tools configuration file
  use iso_fortran_env, only: &
    i4=>int32, &
    dp=>real64
  use iso_c_binding, only: c_f_pointer, c_intptr_t, c_null_ptr, c_ptr

  implicit none

  ! default values
  character(len=str_len), parameter, public :: name_default = "pybind-example"
  logical, parameter, public :: enabled_default = .false.
  real(dp), parameter, public :: weights_default = 1.0_dp

  ! bounds values
  integer(i4), parameter, public :: iterations_min = 1_i4
  real(dp), parameter, public :: tolerance_min_excl = 0.0_dp

  !> \class nml_config_t
  !> \brief Python binding config
  !> \details Minimal namelist used by the pybind example.
  !!
  !! The generated f2py wrapper configures a persistent Fortran target instance
  !! through an opaque integer handle.
  !!
  type, public :: nml_config_t
    logical :: is_configured = .false. !< whether the namelist has been configured
    integer :: dim_n_weights = n_weights_default !< runtime dimension for n_weights
    character(len=str_len) :: name !< Config name
    integer(i4) :: iterations !< Iterations
    real(dp) :: tolerance !< Tolerance
    logical :: enabled !< Enabled
    real(dp), allocatable, dimension(:) :: weights !< Weights
  contains
    procedure :: init => nml_config_init
    procedure :: set_dims => nml_config_set_dims
    procedure :: from_file => nml_config_from_file
    procedure :: set => nml_config_set
    procedure :: is_set => nml_config_is_set
    procedure :: is_valid => nml_config_is_valid
  end type nml_config_t

contains

  !> \brief Check whether a value is within bounds
  elemental logical function iterations_in_bounds(val, allow_missing) result(in_bounds)
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
    if (val < iterations_min) in_bounds = .false.
  end function iterations_in_bounds

  !> \brief Check whether a value is within bounds
  elemental logical function tolerance_in_bounds(val, allow_missing) result(in_bounds)
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
    if (val <= tolerance_min_excl) in_bounds = .false.
  end function tolerance_in_bounds

  !> \brief Resolve an opaque C pointer handle to a nml_config_t pointer
  subroutine nml_config_resolve_handle(handle, this, status, errmsg)
    integer(c_intptr_t), intent(in) :: handle !< opaque handle to a nml_config_t instance
    type(nml_config_t), pointer :: this !< resolved namelist pointer
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
  end subroutine nml_config_resolve_handle

  !> \brief Initialize defaults and sentinels for config
  integer function nml_config_init(this, errmsg) result(status)
    class(nml_config_t), intent(inout) :: this !< namelist instance
    character(len=*), intent(out), optional :: errmsg !< error message for non-OK status values

    status = NML_OK
    if (present(errmsg)) errmsg = ""
    this%is_configured = .false.

    ! allocate runtime-sized fields
    if (allocated(this%weights)) deallocate(this%weights)
    allocate(this%weights(this%dim_n_weights))

    ! sentinel values for required/optional parameters
    this%iterations = -huge(this%iterations) ! sentinel for required integer
    this%tolerance = ieee_value(this%tolerance, ieee_quiet_nan) ! sentinel for required real
    ! default values
    this%name = name_default
    this%enabled = enabled_default ! bool values always need a default
    this%weights = weights_default
  end function nml_config_init

  !> \brief Reset runtime dimensions for config
  integer function nml_config_set_dims(this, &
    n_weights, &
    errmsg) result(status)
    class(nml_config_t), intent(inout) :: this !< namelist instance
    integer, intent(in), optional :: n_weights !< runtime dimension override for n_weights
    integer :: candidate_n_weights
    character(len=*), intent(out), optional :: errmsg !< error message for non-OK status values

    status = NML_OK
    if (present(errmsg)) errmsg = ""
    if (present(n_weights)) then
      candidate_n_weights = n_weights
    else
      candidate_n_weights = n_weights_default
    end if
    if (candidate_n_weights <= 0) then
      status = NML_ERR_INVALID_INDEX
      if (present(errmsg)) errmsg = "dimension 'n_weights' must be positive"
      return
    end if
    this%dim_n_weights = candidate_n_weights

    ! deallocate runtime-sized fields; init/set/from_file allocate them again
    if (allocated(this%weights)) deallocate(this%weights)
    this%is_configured = .false.
  end function nml_config_set_dims


  !> \brief Read config namelist from file
  integer function nml_config_from_file(this, file, errmsg) result(status)
    class(nml_config_t), intent(inout) :: this !< namelist instance
    character(len=*), intent(in) :: file !< path to namelist file
    character(len=*), intent(out), optional :: errmsg !< error message for non-OK status values
    ! namelist variables
    character(len=str_len) :: name
    integer(i4) :: iterations
    real(dp) :: tolerance
    logical :: enabled
    real(dp), allocatable, dimension(:) :: weights
    ! locals
    type(nml_file_t) :: nml
    integer :: iostat
    integer :: close_status
    character(len=nml_line_buffer) :: iomsg

    namelist /config/ &
      name, &
      iterations, &
      tolerance, &
      enabled, &
      weights

    status = this%init(errmsg=errmsg)
    if (status /= NML_OK) return
    ! allocate local namelist variables matching runtime-sized fields
    if (allocated(weights)) deallocate(weights)
    allocate(weights(this%dim_n_weights))
    name = this%name
    iterations = this%iterations
    tolerance = this%tolerance
    enabled = this%enabled
    weights = this%weights

    status = nml%open(file, errmsg=errmsg)
    if (status /= NML_OK) return

    status = nml%find("config", errmsg=errmsg)
    if (status /= NML_OK) then
      close_status = nml%close()
      return
    end if

    ! read namelist
    read(nml%unit, nml=config, iostat=iostat, iomsg=iomsg)
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
    this%name = name
    this%iterations = iterations
    this%tolerance = tolerance
    this%enabled = enabled
    this%weights = weights

    ! mark as configured
    this%is_configured = .true.
    status = NML_OK
  end function nml_config_from_file

  !> \brief Set config values
  integer function nml_config_set(this, &
    iterations, &
    tolerance, &
    name, &
    enabled, &
    weights, &
    errmsg) result(status)

    class(nml_config_t), intent(inout) :: this !< namelist instance
    character(len=*), intent(out), optional :: errmsg !< error message for non-OK status values
    integer(i4), intent(in) :: iterations !< Iterations
    real(dp), intent(in) :: tolerance !< Tolerance
    character(len=*), intent(in), optional :: name !< Config name
    logical, intent(in), optional :: enabled !< Enabled
    real(dp), dimension(:), intent(in), optional :: weights !< Weights
    integer :: &
      lb_1, &
      ub_1

    status = this%init(errmsg=errmsg)
    if (status /= NML_OK) return

    ! required parameters
    this%iterations = iterations
    this%tolerance = tolerance
    ! override with provided values
    if (present(name)) this%name = name
    if (present(enabled)) this%enabled = enabled
    if (present(weights)) then
      if (size(weights, 1) > size(this%weights, 1)) then
        status = NML_ERR_INVALID_INDEX
        if (present(errmsg)) errmsg = "dimension 1 exceeds bounds for 'weights'"
        return
      end if
      lb_1 = lbound(this%weights, 1)
      ub_1 = lb_1 + size(weights, 1) - 1
      this%weights(lb_1:ub_1) = weights
    end if

    ! mark as configured
    this%is_configured = .true.
    status = NML_OK
  end function nml_config_set

  !> \brief Check whether a namelist value was set
  integer function nml_config_is_set(this, name, idx, errmsg) result(status)
    class(nml_config_t), intent(in) :: this !< namelist instance
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
    case ("name")
      if (present(idx)) then
        status = NML_ERR_INVALID_INDEX
        if (present(errmsg)) errmsg = "index not supported for 'name'"
        return
      end if
    case ("iterations")
      if (present(idx)) then
        status = NML_ERR_INVALID_INDEX
        if (present(errmsg)) errmsg = "index not supported for 'iterations'"
        return
      end if
      if (this%iterations == -huge(this%iterations)) status = NML_ERR_NOT_SET
    case ("tolerance")
      if (present(idx)) then
        status = NML_ERR_INVALID_INDEX
        if (present(errmsg)) errmsg = "index not supported for 'tolerance'"
        return
      end if
      if (ieee_is_nan(this%tolerance)) status = NML_ERR_NOT_SET
    case ("enabled")
      if (present(idx)) then
        status = NML_ERR_INVALID_INDEX
        if (present(errmsg)) errmsg = "index not supported for 'enabled'"
        return
      end if
    case ("weights")
      if (.not. allocated(this%weights)) then
        status = NML_ERR_NOT_SET
        return
      end if
      if (present(idx)) then
        status = idx_check(idx, lbound(this%weights), ubound(this%weights), &
          "weights", errmsg)
        if (status /= NML_OK) return
      else
      end if
    case default
      status = NML_ERR_INVALID_NAME
      if (present(errmsg)) errmsg = "unknown field: " // trim(name)
    end select
    if (status == NML_ERR_NOT_SET .and. present(errmsg)) then
      if (len_trim(errmsg) == 0) errmsg = "field not set: " // trim(name)
    end if
  end function nml_config_is_set

  !> \brief Validate required values and constraints
  integer function nml_config_is_valid(this, errmsg) result(status)
    class(nml_config_t), intent(in) :: this !< namelist instance
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
    istat = this%is_set("iterations", errmsg=errmsg)
    if (istat == NML_ERR_NOT_SET) then
      status = NML_ERR_REQUIRED
      if (present(errmsg)) then
        if (len_trim(errmsg) == 0) then
          errmsg = "field not set: iterations"
        end if
        errmsg = "required " // trim(errmsg)
      end if
      return
    end if
    if (istat /= NML_OK) then
      status = istat
      return
    end if
    istat = this%is_set("tolerance", errmsg=errmsg)
    if (istat == NML_ERR_NOT_SET) then
      status = NML_ERR_REQUIRED
      if (present(errmsg)) then
        if (len_trim(errmsg) == 0) then
          errmsg = "field not set: tolerance"
        end if
        errmsg = "required " // trim(errmsg)
      end if
      return
    end if
    if (istat /= NML_OK) then
      status = istat
      return
    end if
    ! bounds constraints
    istat = this%is_set("iterations", errmsg=errmsg)
    if (istat == NML_OK) then
      if (.not. iterations_in_bounds(this%iterations)) then
        status = NML_ERR_BOUNDS
        if (present(errmsg)) errmsg = "bounds constraint failed: iterations"
        return
      end if
    else if (istat /= NML_ERR_NOT_SET) then
      status = istat
      return
    end if
    istat = this%is_set("tolerance", errmsg=errmsg)
    if (istat == NML_OK) then
      if (.not. tolerance_in_bounds(this%tolerance)) then
        status = NML_ERR_BOUNDS
        if (present(errmsg)) errmsg = "bounds constraint failed: tolerance"
        return
      end if
    else if (istat /= NML_ERR_NOT_SET) then
      status = istat
      return
    end if
  end function nml_config_is_valid

end module nml_config
