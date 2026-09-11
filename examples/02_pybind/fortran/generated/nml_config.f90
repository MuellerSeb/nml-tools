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
    n_weights__dim_default
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
  use ieee_arithmetic, only: nml__ieee_value => ieee_value, &
    nml__ieee_quiet_nan => ieee_quiet_nan, nml__ieee_is_nan => ieee_is_nan
  ! kind specifiers listed in the nml-tools configuration file
  use iso_fortran_env, only: &
    i4=>int32, &
    dp=>real64
  use iso_c_binding, only: c_f_pointer, c_intptr_t, c_null_ptr, c_ptr

  implicit none

  ! default values
  character(len=str_len), parameter, public :: name__default = "pybind-example"
  logical, parameter, public :: enabled__default = .false.
  real(dp), parameter, public :: weights__default = 1.0_dp

  ! bounds values
  integer(i4), parameter, public :: iterations__min = 1_i4
  real(dp), parameter, public :: tolerance__min_excl = 0.0_dp

  private :: nml_config_read__from_file
  private :: nml__achar, nml__all, nml__allocated, nml__any, nml__huge, nml__len, &
    nml__len_trim, nml__minval, nml__present, nml__reshape, nml__shape, nml__size, &
    nml__trim
  private :: nml__ieee_value, nml__ieee_quiet_nan, nml__ieee_is_nan

  !> \class nml_config_data_t
  !> \brief Schema-backed values for config
  type, public :: nml_config_data_t
    character(len=str_len) :: name !< Config name
    integer(i4) :: iterations !< Iterations
    real(dp) :: tolerance !< Tolerance
    logical :: enabled !< Enabled
    real(dp), allocatable, dimension(:) :: weights !< Weights
  end type nml_config_data_t

  !> \class nml_config_dims_t
  !> \brief Runtime dimensions for config
  type, public :: nml_config_dims_t
    integer :: n_weights = n_weights__dim_default !< runtime dimension for n_weights
  end type nml_config_dims_t

  !> \class nml_config_t
  !> \brief Python binding config
  !> \details Minimal namelist used by the pybind example.
  !!
  !! The generated f2py wrapper configures a persistent Fortran target instance
  !! through an opaque integer handle.
  !!
  type, public :: nml_config_t
    type(nml_config_data_t) :: data !< schema-backed namelist values
    type(nml_config_dims_t) :: dims !< runtime array dimensions
    logical :: is_configured = .false. !< whether the namelist has been configured
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
  elemental logical function iterations__in_bounds(val, allow_missing) result(in_bounds)
    integer(i4), intent(in) :: val !< value to check
    logical, intent(in), optional :: allow_missing !< allow sentinel values as valid

    if (nml__present(allow_missing)) then
      if (allow_missing) then
        if (val == -nml__huge(val)) then
          in_bounds = .true.
          return
        end if
      end if
    end if

    in_bounds = .true.
    if (val < iterations__min) in_bounds = .false.
  end function iterations__in_bounds

  !> \brief Check whether a value is within bounds
  elemental logical function tolerance__in_bounds(val, allow_missing) result(in_bounds)
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
    if (val <= tolerance__min_excl) in_bounds = .false.
  end function tolerance__in_bounds

  !> \brief Resolve an opaque C pointer handle to a nml_config_t pointer
  subroutine nml_config_resolve_handle(handle, nml__obj, nml__status, errmsg)
    integer(c_intptr_t), intent(in) :: handle !< opaque handle to a nml_config_t instance
    type(nml_config_t), pointer :: nml__obj !< resolved namelist pointer
    integer, intent(out) :: nml__status !< nml-tools status code
    character(len=*), intent(out), optional :: errmsg !< error message for non-OK status values
    type(c_ptr) :: ptr

    if (nml__present(errmsg)) errmsg = ""
    nullify(nml__obj)
    if (handle == 0_c_intptr_t) then
      nml__status = NML_ERR_INVALID_HANDLE
      if (nml__present(errmsg)) errmsg = "zero handle"
      return
    end if
    ptr = transfer(handle, c_null_ptr)
    call c_f_pointer(ptr, nml__obj)
    nml__status = NML_OK
  end subroutine nml_config_resolve_handle

  !> \brief Initialize defaults and sentinels for config
  integer function nml_config_init(nml__obj, errmsg) result(nml__status)
    class(nml_config_t), intent(inout) :: nml__obj !< namelist instance
    character(len=*), intent(out), optional :: errmsg !< error message for non-OK status values

    nml__status = NML_OK
    if (nml__present(errmsg)) errmsg = ""
    nml__obj%is_configured = .false.

    ! allocate runtime-sized fields
    if (nml__allocated(nml__obj%data%weights)) deallocate(nml__obj%data%weights)
    allocate(nml__obj%data%weights(nml__obj%dims%n_weights))

    ! sentinel values for required/optional parameters
    nml__obj%data%iterations = -nml__huge(nml__obj%data%iterations) ! sentinel for required integer
    nml__obj%data%tolerance = nml__ieee_value(nml__obj%data%tolerance, nml__ieee_quiet_nan) ! sentinel for required real
    ! default values
    nml__obj%data%name = name__default
    nml__obj%data%enabled = enabled__default ! bool values always need a default
    nml__obj%data%weights = weights__default
  end function nml_config_init

  !> \brief Reset runtime dimensions for config
  integer function nml_config_set_dims(nml__obj, &
    n_weights, &
    errmsg) result(nml__status)
    class(nml_config_t), intent(inout) :: nml__obj !< namelist instance
    integer, intent(in), optional :: n_weights !< runtime dimension override for n_weights
    integer :: candidate__n_weights
    character(len=*), intent(out), optional :: errmsg !< error message for non-OK status values

    nml__status = NML_OK
    if (nml__present(errmsg)) errmsg = ""
    if (nml__present(n_weights)) then
      candidate__n_weights = n_weights
    else
      candidate__n_weights = n_weights__dim_default
    end if
    if (candidate__n_weights <= 0) then
      nml__status = NML_ERR_INVALID_INDEX
      if (nml__present(errmsg)) errmsg = "dimension 'n_weights' must be positive"
      return
    end if
    nml__obj%dims%n_weights = candidate__n_weights

    ! deallocate runtime-sized fields; init/set/from_file allocate them again
    if (nml__allocated(nml__obj%data%weights)) deallocate(nml__obj%data%weights)
    nml__obj%is_configured = .false.
  end function nml_config_set_dims


  !> \brief Read config namelist from file
  integer function nml_config_from_file(nml__obj, file, errmsg) result(nml__status)
    class(nml_config_t), intent(inout) :: nml__obj !< namelist instance
    character(len=*), intent(in) :: file !< path to namelist file
    character(len=*), intent(out), optional :: errmsg !< error message for non-OK status values

    nml__status = nml_config_read__from_file(nml__obj, file, errmsg)
  end function nml_config_from_file

  integer function nml_config_read__from_file(nml__obj, nml__file, errmsg) &
    result(nml__status)
    class(nml_config_t), intent(inout) :: nml__obj
    character(len=*), intent(in) :: nml__file
    character(len=*), intent(out), optional :: errmsg
    ! namelist variables
    character(len=str_len) :: name
    integer(i4) :: iterations
    real(dp) :: tolerance
    logical :: enabled
    real(dp), allocatable, dimension(:) :: weights
    ! locals
    type(nml_file_t) :: nml__reader
    integer :: nml__iostat
    integer :: nml__close_status
    character(len=nml_line_buffer) :: nml__iomsg

    namelist /config/ &
      name, &
      iterations, &
      tolerance, &
      enabled, &
      weights

    nml__status = nml__obj%init(errmsg=errmsg)
    if (nml__status /= NML_OK) return
    ! allocate local namelist variables matching runtime-sized fields
    if (nml__allocated(weights)) deallocate(weights)
    allocate(weights(nml__obj%dims%n_weights))
    name = nml__obj%data%name
    iterations = nml__obj%data%iterations
    tolerance = nml__obj%data%tolerance
    enabled = nml__obj%data%enabled
    weights = nml__obj%data%weights

    nml__status = nml__reader%open(nml__file, errmsg=errmsg)
    if (nml__status /= NML_OK) return

    nml__status = nml__reader%find("config", errmsg=errmsg)
    if (nml__status /= NML_OK) then
      nml__close_status = nml__reader%close()
      return
    end if

    ! read namelist
    read(nml__reader%unit, nml=config, iostat=nml__iostat, iomsg=nml__iomsg)
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
    nml__obj%data%name = name
    nml__obj%data%iterations = iterations
    nml__obj%data%tolerance = tolerance
    nml__obj%data%enabled = enabled
    nml__obj%data%weights = weights

    ! mark as configured
    nml__obj%is_configured = .true.
    nml__status = NML_OK
  end function nml_config_read__from_file

  !> \brief Set config values
  integer function nml_config_set(nml__obj, &
    iterations, &
    tolerance, &
    name, &
    enabled, &
    weights, &
    errmsg) result(nml__status)

    class(nml_config_t), intent(inout) :: nml__obj !< namelist instance
    character(len=*), intent(out), optional :: errmsg !< error message for non-OK status values
    integer(i4), intent(in) :: iterations !< Iterations
    real(dp), intent(in) :: tolerance !< Tolerance
    character(len=*), intent(in), optional :: name !< Config name
    logical, intent(in), optional :: enabled !< Enabled
    real(dp), dimension(:), intent(in), optional :: weights !< Weights
    nml__status = nml__obj%init(errmsg=errmsg)
    if (nml__status /= NML_OK) return

    ! required parameters
    nml__obj%data%iterations = iterations
    nml__obj%data%tolerance = tolerance
    ! override with provided values
    if (nml__present(name)) nml__obj%data%name = name
    if (nml__present(enabled)) nml__obj%data%enabled = enabled
    if (nml__present(weights)) then
      if (nml__size(weights, 1) > nml__size(nml__obj%data%weights, 1)) then
        nml__status = NML_ERR_INVALID_INDEX
        if (nml__present(errmsg)) errmsg = "dimension 1 exceeds bounds for 'weights'"
        return
      end if
      nml__obj%data%weights( &
        1:nml__size(weights, 1)) = weights
    end if

    ! mark as configured
    nml__obj%is_configured = .true.
    nml__status = NML_OK
  end function nml_config_set

  !> \brief Check whether a namelist value was set
  integer function nml_config_is_set(nml__obj, name, idx, errmsg) result(nml__status)
    class(nml_config_t), intent(in) :: nml__obj !< namelist instance
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
    case ("name")
      if (nml__present(idx)) then
        nml__status = NML_ERR_INVALID_INDEX
        if (nml__present(errmsg)) errmsg = "index not supported for 'name'"
        return
      end if
    case ("iterations")
      if (nml__present(idx)) then
        nml__status = NML_ERR_INVALID_INDEX
        if (nml__present(errmsg)) errmsg = "index not supported for 'iterations'"
        return
      end if
      if (nml__obj%data%iterations == -nml__huge(nml__obj%data%iterations)) nml__status = NML_ERR_NOT_SET
    case ("tolerance")
      if (nml__present(idx)) then
        nml__status = NML_ERR_INVALID_INDEX
        if (nml__present(errmsg)) errmsg = "index not supported for 'tolerance'"
        return
      end if
      if (nml__ieee_is_nan(nml__obj%data%tolerance)) nml__status = NML_ERR_NOT_SET
    case ("enabled")
      if (nml__present(idx)) then
        nml__status = NML_ERR_INVALID_INDEX
        if (nml__present(errmsg)) errmsg = "index not supported for 'enabled'"
        return
      end if
    case ("weights")
      if (.not. nml__allocated(nml__obj%data%weights)) then
        nml__status = NML_ERR_NOT_SET
        return
      end if
      if (nml__present(idx)) then
        nml__status = idx_check(idx, nml__shape(nml__obj%data%weights), &
          "weights", errmsg)
        if (nml__status /= NML_OK) return
      else
      end if
    case default
      nml__status = NML_ERR_INVALID_NAME
      if (nml__present(errmsg)) errmsg = "unknown field: " // nml__trim(name)
    end select
    if (nml__status == NML_ERR_NOT_SET .and. nml__present(errmsg)) then
      if (nml__len_trim(errmsg) == 0) errmsg = "field not set: " // nml__trim(name)
    end if
  end function nml_config_is_set

  !> \brief Validate required values and constraints
  integer function nml_config_is_valid(nml__obj, errmsg) result(nml__status)
    class(nml_config_t), intent(in) :: nml__obj !< namelist instance
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
    nml__istat = nml__obj%is_set("iterations", errmsg=errmsg)
    if (nml__istat == NML_ERR_NOT_SET) then
      nml__status = NML_ERR_REQUIRED
      if (nml__present(errmsg)) then
        if (nml__len_trim(errmsg) == 0) then
          errmsg = "field not set: iterations"
        end if
        errmsg = "required " // nml__trim(errmsg)
      end if
      return
    end if
    if (nml__istat /= NML_OK) then
      nml__status = nml__istat
      return
    end if
    nml__istat = nml__obj%is_set("tolerance", errmsg=errmsg)
    if (nml__istat == NML_ERR_NOT_SET) then
      nml__status = NML_ERR_REQUIRED
      if (nml__present(errmsg)) then
        if (nml__len_trim(errmsg) == 0) then
          errmsg = "field not set: tolerance"
        end if
        errmsg = "required " // nml__trim(errmsg)
      end if
      return
    end if
    if (nml__istat /= NML_OK) then
      nml__status = nml__istat
      return
    end if
    ! bounds constraints
    nml__istat = nml__obj%is_set("iterations", errmsg=errmsg)
    if (nml__istat == NML_OK) then
      if (.not. iterations__in_bounds(nml__obj%data%iterations)) then
        nml__status = NML_ERR_BOUNDS
        if (nml__present(errmsg)) errmsg = "bounds constraint failed: iterations"
        return
      end if
    else if (nml__istat /= NML_ERR_NOT_SET) then
      nml__status = nml__istat
      return
    end if
    nml__istat = nml__obj%is_set("tolerance", errmsg=errmsg)
    if (nml__istat == NML_OK) then
      if (.not. tolerance__in_bounds(nml__obj%data%tolerance)) then
        nml__status = NML_ERR_BOUNDS
        if (nml__present(errmsg)) errmsg = "bounds constraint failed: tolerance"
        return
      end if
    else if (nml__istat /= NML_ERR_NOT_SET) then
      nml__status = nml__istat
      return
    end if
  end function nml_config_is_valid

end module nml_config
