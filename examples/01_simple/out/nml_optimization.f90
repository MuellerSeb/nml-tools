!> \file nml_optimization.f90
!> \copydoc nml_optimization

!> \brief Optimization configurations
!> \details All relevant configurations for the optimization parameters.
!> \version 0.1
module nml_optimization
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
    buf, &
    max_iter__default, &
    NML_ERR_PARTLY_SET
  use ieee_arithmetic, only: ieee_value, ieee_quiet_nan, ieee_is_nan
  ! kind specifiers listed in the nml-tools configuration file
  use iso_fortran_env, only: &
    i4=>int32, &
    dp=>real64

  implicit none

  ! default values
  integer(i4), parameter, public :: seed__default = -9_i4
  real(dp), parameter, public :: dds_r__default = 0.2_dp
  logical, parameter, public :: mcmc_opti__default = .true.
  logical, parameter, public :: include_parameters__default = .true.

  ! enum values
  character(len=buf), parameter, public :: &
    method__enum_values(3) = [character(len=buf) :: "DDS", "MCMC", "SCE"]
  character(len=buf), parameter, public :: &
    try_methods__enum_values(3) = [character(len=buf) :: "DDS", "MCMC", "SCE"]
  integer(i4), parameter, public :: complex_sizes__enum_values(5) = [5_i4, 10_i4, 15_i4, 20_i4, 30_i4]

  ! bounds values
  integer(i4), parameter, public :: niterations__min = 10_i4
  real(dp), parameter, public :: tolerance__min_excl = 0.0_dp
  real(dp), parameter, public :: dds_r__min_excl = 0.0_dp
  real(dp), parameter, public :: mcmc_error_params__min = 0.0_dp

  !> \class nml_optimization_t
  !> \brief Optimization configurations
  !> \details All relevant configurations for the optimization parameters.
  type, public :: nml_optimization_t
    logical :: is_configured = .false. !< whether the namelist has been configured
    integer :: max_iter = max_iter__default !< runtime dimension for max_iter
    character(len=buf) :: name !< Optimization name
    character(len=buf) :: method !< Optimization method
    character(len=buf), dimension(3) :: try_methods !< Try alternative methods
    integer(i4), dimension(3) :: complex_sizes !< Complex sizes for SCE
    integer(i4) :: niterations !< Number of iterations
    real(dp) :: tolerance !< Convergence tolerance
    integer(i4) :: seed !< Random seed
    real(dp) :: dds_r !< DDS perturbation rate
    logical :: mcmc_opti !< MCMC optimization
    real(dp), allocatable, dimension(:, :, :) :: mcmc_error_params !< MCMC error parameters per iteration
    logical, dimension(3) :: include_parameters !< Include parameters
  contains
    procedure :: init => nml_optimization_init
    procedure :: set_dims => nml_optimization_set_dims
    procedure :: from_file => nml_optimization_from_file
    procedure :: set => nml_optimization_set
    procedure :: is_set => nml_optimization_is_set
    procedure, private :: set_mask__rank__1 => nml_optimization_set_mask__rank__1
    procedure, private :: set_mask__rank__3 => nml_optimization_set_mask__rank__3
    generic :: set_mask => &
      set_mask__rank__1, &
      set_mask__rank__3
    procedure :: filled_shape => nml_optimization_filled_shape
    procedure :: is_valid => nml_optimization_is_valid
  end type nml_optimization_t

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

  !> \brief Check whether a value is part of an enum
  elemental logical function try_methods__in_enum(val, allow_missing) result(in_enum)
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
    in_enum = any(trim(val) == try_methods__enum_values)
  end function try_methods__in_enum

  !> \brief Check whether a value is part of an enum
  elemental logical function complex_sizes__in_enum(val, allow_missing) result(in_enum)
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
    in_enum = any(val == complex_sizes__enum_values)
  end function complex_sizes__in_enum

  !> \brief Check whether a value is within bounds
  elemental logical function niterations__in_bounds(val, allow_missing) result(in_bounds)
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
    if (val < niterations__min) in_bounds = .false.
  end function niterations__in_bounds

  !> \brief Check whether a value is within bounds
  elemental logical function tolerance__in_bounds(val, allow_missing) result(in_bounds)
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
    if (val <= tolerance__min_excl) in_bounds = .false.
  end function tolerance__in_bounds

  !> \brief Check whether a value is within bounds
  elemental logical function dds_r__in_bounds(val, allow_missing) result(in_bounds)
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
    if (val <= dds_r__min_excl) in_bounds = .false.
  end function dds_r__in_bounds

  !> \brief Check whether a value is within bounds
  elemental logical function mcmc_error_params__in_bounds(val, allow_missing) result(in_bounds)
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
    if (val < mcmc_error_params__min) in_bounds = .false.
  end function mcmc_error_params__in_bounds

  !> \brief Initialize defaults and sentinels for optimization
  integer function nml_optimization_init(this, errmsg) result(status)
    class(nml_optimization_t), intent(inout) :: this !< namelist instance
    character(len=*), intent(out), optional :: errmsg !< error message for non-OK status values

    status = NML_OK
    if (present(errmsg)) errmsg = ""
    this%is_configured = .false.

    ! allocate runtime-sized fields
    if (allocated(this%mcmc_error_params)) deallocate(this%mcmc_error_params)
    allocate(this%mcmc_error_params(3, 2, this%max_iter))

    ! sentinel values for required/optional parameters
    this%name = achar(0) ! sentinel for optional string
    this%method = achar(0) ! NULL string as sentinel for required string
    this%try_methods = achar(0) ! sentinel for optional string array
    this%complex_sizes = -huge(this%complex_sizes) ! sentinel for optional integer array
    this%niterations = -huge(this%niterations) ! sentinel for required integer
    this%tolerance = ieee_value(this%tolerance, ieee_quiet_nan) ! sentinel for required real
    this%mcmc_error_params = ieee_value(this%mcmc_error_params, ieee_quiet_nan) ! sentinel for optional real array
    ! default values
    this%seed = seed__default
    this%dds_r = dds_r__default
    this%mcmc_opti = mcmc_opti__default ! bool values always need a default
    this%include_parameters = include_parameters__default
  end function nml_optimization_init

  !> \brief Reset runtime dimensions for optimization
  integer function nml_optimization_set_dims(this, &
    max_iter, &
    errmsg) result(status)
    class(nml_optimization_t), intent(inout) :: this !< namelist instance
    integer, intent(in), optional :: max_iter !< runtime dimension override for max_iter
    integer :: candidate__max_iter
    character(len=*), intent(out), optional :: errmsg !< error message for non-OK status values

    status = NML_OK
    if (present(errmsg)) errmsg = ""
    if (present(max_iter)) then
      candidate__max_iter = max_iter
    else
      candidate__max_iter = max_iter__default
    end if
    if (candidate__max_iter <= 0) then
      status = NML_ERR_INVALID_INDEX
      if (present(errmsg)) errmsg = "dimension 'max_iter' must be positive"
      return
    end if
    this%max_iter = candidate__max_iter

    ! deallocate runtime-sized fields; init/set/from_file allocate them again
    if (allocated(this%mcmc_error_params)) deallocate(this%mcmc_error_params)
    this%is_configured = .false.
  end function nml_optimization_set_dims


  !> \brief Read optimization namelist from file
  integer function nml_optimization_from_file(this, file, errmsg) result(status)
    class(nml_optimization_t), intent(inout) :: this !< namelist instance
    character(len=*), intent(in) :: file !< path to namelist file
    character(len=*), intent(out), optional :: errmsg !< error message for non-OK status values
    ! namelist variables
    character(len=buf) :: name
    character(len=buf) :: method
    character(len=buf), dimension(3) :: try_methods
    integer(i4), dimension(3) :: complex_sizes
    integer(i4) :: niterations
    real(dp) :: tolerance
    integer(i4) :: seed
    real(dp) :: dds_r
    logical :: mcmc_opti
    real(dp), allocatable, dimension(:, :, :) :: mcmc_error_params
    logical, dimension(3) :: include_parameters
    ! locals
    type(nml_file_t) :: nml
    integer :: iostat
    integer :: close_status
    character(len=nml_line_buffer) :: iomsg

    namelist /optimization/ &
      name, &
      method, &
      try_methods, &
      complex_sizes, &
      niterations, &
      tolerance, &
      seed, &
      dds_r, &
      mcmc_opti, &
      mcmc_error_params, &
      include_parameters

    status = this%init(errmsg=errmsg)
    if (status /= NML_OK) return
    ! allocate local namelist variables matching runtime-sized fields
    if (allocated(mcmc_error_params)) deallocate(mcmc_error_params)
    allocate(mcmc_error_params(3, 2, this%max_iter))
    name = this%name
    method = this%method
    try_methods = this%try_methods
    complex_sizes = this%complex_sizes
    niterations = this%niterations
    tolerance = this%tolerance
    seed = this%seed
    dds_r = this%dds_r
    mcmc_opti = this%mcmc_opti
    mcmc_error_params = this%mcmc_error_params
    include_parameters = this%include_parameters

    status = nml%open(file, errmsg=errmsg)
    if (status /= NML_OK) return

    status = nml%find("optimization", errmsg=errmsg)
    if (status /= NML_OK) then
      close_status = nml%close()
      return
    end if

    ! read namelist
    read(nml%unit, nml=optimization, iostat=iostat, iomsg=iomsg)
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
    this%method = method
    this%try_methods = try_methods
    this%complex_sizes = complex_sizes
    this%niterations = niterations
    this%tolerance = tolerance
    this%seed = seed
    this%dds_r = dds_r
    this%mcmc_opti = mcmc_opti
    this%mcmc_error_params = mcmc_error_params
    this%include_parameters = include_parameters

    ! mark as configured
    this%is_configured = .true.
    status = NML_OK
  end function nml_optimization_from_file

  !> \brief Set optimization values
  integer function nml_optimization_set(this, &
    method, &
    niterations, &
    tolerance, &
    name, &
    try_methods, &
    complex_sizes, &
    seed, &
    dds_r, &
    mcmc_opti, &
    mcmc_error_params, &
    include_parameters, &
    errmsg) result(status)

    class(nml_optimization_t), intent(inout) :: this !< namelist instance
    character(len=*), intent(out), optional :: errmsg !< error message for non-OK status values
    character(len=*), intent(in) :: method !< Optimization method
    integer(i4), intent(in) :: niterations !< Number of iterations
    real(dp), intent(in) :: tolerance !< Convergence tolerance
    character(len=*), intent(in), optional :: name !< Optimization name
    character(len=*), dimension(:), intent(in), optional :: try_methods !< Try alternative methods
    integer(i4), dimension(:), intent(in), optional :: complex_sizes !< Complex sizes for SCE
    integer(i4), intent(in), optional :: seed !< Random seed
    real(dp), intent(in), optional :: dds_r !< DDS perturbation rate
    logical, intent(in), optional :: mcmc_opti !< MCMC optimization
    real(dp), dimension(:, :, :), intent(in), optional :: mcmc_error_params !< MCMC error parameters per iteration
    logical, dimension(:), intent(in), optional :: include_parameters !< Include parameters

    status = this%init(errmsg=errmsg)
    if (status /= NML_OK) return

    ! required parameters
    this%method = method
    this%niterations = niterations
    this%tolerance = tolerance
    ! override with provided values
    if (present(name)) this%name = name
    if (present(try_methods)) then
      if (size(try_methods, 1) > size(this%try_methods, 1)) then
        status = NML_ERR_INVALID_INDEX
        if (present(errmsg)) errmsg = "dimension 1 exceeds bounds for 'try_methods'"
        return
      end if
      this%try_methods(1:size(try_methods, 1)) = try_methods
    end if
    if (present(complex_sizes)) then
      if (size(complex_sizes, 1) > size(this%complex_sizes, 1)) then
        status = NML_ERR_INVALID_INDEX
        if (present(errmsg)) errmsg = "dimension 1 exceeds bounds for 'complex_sizes'"
        return
      end if
      this%complex_sizes(1:size(complex_sizes, 1)) = complex_sizes
    end if
    if (present(seed)) this%seed = seed
    if (present(dds_r)) this%dds_r = dds_r
    if (present(mcmc_opti)) this%mcmc_opti = mcmc_opti
    if (present(mcmc_error_params)) then
      if (size(mcmc_error_params, 1) > size(this%mcmc_error_params, 1)) then
        status = NML_ERR_INVALID_INDEX
        if (present(errmsg)) errmsg = "dimension 1 exceeds bounds for 'mcmc_error_params'"
        return
      end if
      if (size(mcmc_error_params, 2) > size(this%mcmc_error_params, 2)) then
        status = NML_ERR_INVALID_INDEX
        if (present(errmsg)) errmsg = "dimension 2 exceeds bounds for 'mcmc_error_params'"
        return
      end if
      if (size(mcmc_error_params, 3) > size(this%mcmc_error_params, 3)) then
        status = NML_ERR_INVALID_INDEX
        if (present(errmsg)) errmsg = "dimension 3 exceeds bounds for 'mcmc_error_params'"
        return
      end if
      this%mcmc_error_params( &
        1:size(mcmc_error_params, 1), &
        1:size(mcmc_error_params, 2), &
        1:size(mcmc_error_params, 3) &
      ) = mcmc_error_params
    end if
    if (present(include_parameters)) then
      if (size(include_parameters, 1) > size(this%include_parameters, 1)) then
        status = NML_ERR_INVALID_INDEX
        if (present(errmsg)) errmsg = "dimension 1 exceeds bounds for 'include_parameters'"
        return
      end if
      this%include_parameters(1:size(include_parameters, 1)) = include_parameters
    end if

    ! mark as configured
    this%is_configured = .true.
    status = NML_OK
  end function nml_optimization_set

  !> \brief Check whether a namelist value was set
  integer function nml_optimization_is_set(this, name, idx, errmsg) result(status)
    class(nml_optimization_t), intent(in) :: this !< namelist instance
    character(len=*), intent(in) :: name !< field name
    integer, intent(in), optional :: idx(:) !< optional field index values
    character(len=*), intent(out), optional :: errmsg !< error message for non-OK status values
    intrinsic :: shape

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
      if (this%name == achar(0)) status = NML_ERR_NOT_SET
    case ("method")
      if (present(idx)) then
        status = NML_ERR_INVALID_INDEX
        if (present(errmsg)) errmsg = "index not supported for 'method'"
        return
      end if
      if (this%method == achar(0)) status = NML_ERR_NOT_SET
    case ("try_methods")
      if (present(idx)) then
        status = idx_check(idx, shape(this%try_methods), "try_methods", errmsg)
        if (status /= NML_OK) return
        if (this%try_methods(idx(1)) == achar(0)) status = NML_ERR_NOT_SET
      else
        if (all(this%try_methods == achar(0))) status = NML_ERR_NOT_SET
      end if
    case ("complex_sizes")
      if (present(idx)) then
        status = idx_check(idx, shape(this%complex_sizes), "complex_sizes", errmsg)
        if (status /= NML_OK) return
        if (this%complex_sizes(idx(1)) == -huge(this%complex_sizes(idx(1)))) status = NML_ERR_NOT_SET
      else
        if (all(this%complex_sizes == -huge(this%complex_sizes))) status = NML_ERR_NOT_SET
      end if
    case ("niterations")
      if (present(idx)) then
        status = NML_ERR_INVALID_INDEX
        if (present(errmsg)) errmsg = "index not supported for 'niterations'"
        return
      end if
      if (this%niterations == -huge(this%niterations)) status = NML_ERR_NOT_SET
    case ("tolerance")
      if (present(idx)) then
        status = NML_ERR_INVALID_INDEX
        if (present(errmsg)) errmsg = "index not supported for 'tolerance'"
        return
      end if
      if (ieee_is_nan(this%tolerance)) status = NML_ERR_NOT_SET
    case ("seed")
      if (present(idx)) then
        status = NML_ERR_INVALID_INDEX
        if (present(errmsg)) errmsg = "index not supported for 'seed'"
        return
      end if
    case ("dds_r")
      if (present(idx)) then
        status = NML_ERR_INVALID_INDEX
        if (present(errmsg)) errmsg = "index not supported for 'dds_r'"
        return
      end if
    case ("mcmc_opti")
      if (present(idx)) then
        status = NML_ERR_INVALID_INDEX
        if (present(errmsg)) errmsg = "index not supported for 'mcmc_opti'"
        return
      end if
    case ("mcmc_error_params")
      if (.not. allocated(this%mcmc_error_params)) then
        status = NML_ERR_NOT_SET
        if (present(errmsg)) errmsg = "array storage unavailable: mcmc_error_params"
        return
      end if
      if (present(idx)) then
        status = idx_check(idx, shape(this%mcmc_error_params), "mcmc_error_params", errmsg)
        if (status /= NML_OK) return
        if (ieee_is_nan(this%mcmc_error_params(idx(1), idx(2), idx(3)))) status = NML_ERR_NOT_SET
      else
        if (all(ieee_is_nan(this%mcmc_error_params))) status = NML_ERR_NOT_SET
      end if
    case ("include_parameters")
      if (present(idx)) then
        status = idx_check(idx, shape(this%include_parameters), "include_parameters", errmsg)
        if (status /= NML_OK) return
      end if
    case default
      status = NML_ERR_INVALID_NAME
      if (present(errmsg)) errmsg = "unknown field: " // trim(name)
    end select
    if (status == NML_ERR_NOT_SET .and. present(errmsg)) then
      if (len_trim(errmsg) == 0) errmsg = "field not set: " // trim(name)
    end if
  end function nml_optimization_is_set

  !> \brief Obtain the item presence mask with one field-name dispatch
  integer function nml_optimization_set_mask__rank__1(this, name, mask, errmsg) result(status)
    class(nml_optimization_t), intent(in) :: this !< namelist instance
    character(len=*), intent(in) :: name !< field or derived component path
    logical, allocatable, intent(out) :: mask(:) !< item presence
    character(len=*), intent(out), optional :: errmsg !< error message for non-OK status values
    integer :: idx__1

    status = NML_OK
    if (present(errmsg)) errmsg = ""
    if (.not. this%is_configured) then
      status = NML_ERR_NOT_SET
      if (present(errmsg)) errmsg = "namelist not configured; call set or from_file"
      return
    end if
    select case (to_lower(trim(name)))
    case ("name")
      status = NML_ERR_INVALID_INDEX
      if (present(errmsg)) errmsg = "array query not supported for scalar: name"
    case ("method")
      status = NML_ERR_INVALID_INDEX
      if (present(errmsg)) errmsg = "array query not supported for scalar: method"
    case ("try_methods")
      allocate(mask( &
        size(this%try_methods, 1)))
      do idx__1 = 1, size(this%try_methods, 1)
        if (this%try_methods(idx__1) == achar(0)) then
          mask(idx__1) = .false.
        else
          mask(idx__1) = .true.
        end if
      end do
    case ("complex_sizes")
      allocate(mask( &
        size(this%complex_sizes, 1)))
      do idx__1 = 1, size(this%complex_sizes, 1)
        if (this%complex_sizes(idx__1) == -huge(this%complex_sizes(idx__1))) then
          mask(idx__1) = .false.
        else
          mask(idx__1) = .true.
        end if
      end do
    case ("niterations")
      status = NML_ERR_INVALID_INDEX
      if (present(errmsg)) errmsg = "array query not supported for scalar: niterations"
    case ("tolerance")
      status = NML_ERR_INVALID_INDEX
      if (present(errmsg)) errmsg = "array query not supported for scalar: tolerance"
    case ("seed")
      status = NML_ERR_INVALID_INDEX
      if (present(errmsg)) errmsg = "array query not supported for scalar: seed"
    case ("dds_r")
      status = NML_ERR_INVALID_INDEX
      if (present(errmsg)) errmsg = "array query not supported for scalar: dds_r"
    case ("mcmc_opti")
      status = NML_ERR_INVALID_INDEX
      if (present(errmsg)) errmsg = "array query not supported for scalar: mcmc_opti"
    case ("mcmc_error_params")
      status = NML_ERR_INVALID_INDEX
      if (present(errmsg)) errmsg = "mask rank mismatch for 'mcmc_error_params'"
    case ("include_parameters")
      allocate(mask( &
        size(this%include_parameters, 1)))
      mask = .true.
    case default
      status = NML_ERR_INVALID_NAME
      if (present(errmsg)) errmsg = "unknown field: " // trim(name)
    end select
  end function nml_optimization_set_mask__rank__1

  !> \brief Obtain the item presence mask with one field-name dispatch
  integer function nml_optimization_set_mask__rank__3(this, name, mask, errmsg) result(status)
    class(nml_optimization_t), intent(in) :: this !< namelist instance
    character(len=*), intent(in) :: name !< field or derived component path
    logical, allocatable, intent(out) :: mask(:, :, :) !< item presence
    character(len=*), intent(out), optional :: errmsg !< error message for non-OK status values
    integer :: idx__1
    integer :: idx__2
    integer :: idx__3

    status = NML_OK
    if (present(errmsg)) errmsg = ""
    if (.not. this%is_configured) then
      status = NML_ERR_NOT_SET
      if (present(errmsg)) errmsg = "namelist not configured; call set or from_file"
      return
    end if
    select case (to_lower(trim(name)))
    case ("name")
      status = NML_ERR_INVALID_INDEX
      if (present(errmsg)) errmsg = "array query not supported for scalar: name"
    case ("method")
      status = NML_ERR_INVALID_INDEX
      if (present(errmsg)) errmsg = "array query not supported for scalar: method"
    case ("try_methods")
      status = NML_ERR_INVALID_INDEX
      if (present(errmsg)) errmsg = "mask rank mismatch for 'try_methods'"
    case ("complex_sizes")
      status = NML_ERR_INVALID_INDEX
      if (present(errmsg)) errmsg = "mask rank mismatch for 'complex_sizes'"
    case ("niterations")
      status = NML_ERR_INVALID_INDEX
      if (present(errmsg)) errmsg = "array query not supported for scalar: niterations"
    case ("tolerance")
      status = NML_ERR_INVALID_INDEX
      if (present(errmsg)) errmsg = "array query not supported for scalar: tolerance"
    case ("seed")
      status = NML_ERR_INVALID_INDEX
      if (present(errmsg)) errmsg = "array query not supported for scalar: seed"
    case ("dds_r")
      status = NML_ERR_INVALID_INDEX
      if (present(errmsg)) errmsg = "array query not supported for scalar: dds_r"
    case ("mcmc_opti")
      status = NML_ERR_INVALID_INDEX
      if (present(errmsg)) errmsg = "array query not supported for scalar: mcmc_opti"
    case ("mcmc_error_params")
      if (.not. allocated(this%mcmc_error_params)) then
        status = NML_ERR_NOT_SET
        if (present(errmsg)) errmsg = "array storage unavailable: mcmc_error_params"
        return
      end if
      allocate(mask( &
        size(this%mcmc_error_params, 1), &
        size(this%mcmc_error_params, 2), &
        size(this%mcmc_error_params, 3)))
      do idx__3 = 1, size(this%mcmc_error_params, 3)
        do idx__2 = 1, size(this%mcmc_error_params, 2)
          do idx__1 = 1, size(this%mcmc_error_params, 1)
            if (ieee_is_nan(this%mcmc_error_params(idx__1, idx__2, idx__3))) then
              mask(idx__1, idx__2, idx__3) = .false.
            else
              mask(idx__1, idx__2, idx__3) = .true.
            end if
          end do
        end do
      end do
    case ("include_parameters")
      status = NML_ERR_INVALID_INDEX
      if (present(errmsg)) errmsg = "mask rank mismatch for 'include_parameters'"
    case default
      status = NML_ERR_INVALID_NAME
      if (present(errmsg)) errmsg = "unknown field: " // trim(name)
    end select
  end function nml_optimization_set_mask__rank__3

  !> \brief Determine the smallest complete populated prefix starting at index 1
  integer function nml_optimization_filled_shape(this, name, filled, errmsg) result(status)
    class(nml_optimization_t), intent(in) :: this !< namelist instance
    character(len=*), intent(in) :: name !< field or derived component path
    integer, intent(out) :: filled(:) !< prefix extents, retained when the prefix has holes
    character(len=*), intent(out), optional :: errmsg !< error message for non-OK status values
    integer :: idx__1
    integer :: idx__2
    integer :: idx__3

    filled = 0
    status = NML_OK
    if (present(errmsg)) errmsg = ""
    if (.not. this%is_configured) then
      status = NML_ERR_NOT_SET
      if (present(errmsg)) errmsg = "namelist not configured; call set or from_file"
      return
    end if
    select case (to_lower(trim(name)))
    case ("name")
      status = NML_ERR_INVALID_INDEX
      if (present(errmsg)) errmsg = "array query not supported for scalar: name"
    case ("method")
      status = NML_ERR_INVALID_INDEX
      if (present(errmsg)) errmsg = "array query not supported for scalar: method"
    case ("try_methods")
      if (size(filled) /= 1) then
        status = NML_ERR_INVALID_INDEX
        if (present(errmsg)) errmsg = "shape rank mismatch for 'try_methods'"
        return
      end if
      do idx__1 = 1, size(this%try_methods, 1)
        if (this%try_methods(idx__1) == achar(0)) cycle
        if (idx__1 > filled(1)) filled(1) = idx__1
      end do
      do idx__1 = 1, filled(1)
        if (this%try_methods(idx__1) == achar(0)) then
          status = NML_ERR_PARTLY_SET
          if (present(errmsg)) errmsg = "array partly set: try_methods"
          return
        end if
      end do
    case ("complex_sizes")
      if (size(filled) /= 1) then
        status = NML_ERR_INVALID_INDEX
        if (present(errmsg)) errmsg = "shape rank mismatch for 'complex_sizes'"
        return
      end if
      do idx__1 = 1, size(this%complex_sizes, 1)
        if (this%complex_sizes(idx__1) == -huge(this%complex_sizes(idx__1))) cycle
        if (idx__1 > filled(1)) filled(1) = idx__1
      end do
      do idx__1 = 1, filled(1)
        if (this%complex_sizes(idx__1) == -huge(this%complex_sizes(idx__1))) then
          status = NML_ERR_PARTLY_SET
          if (present(errmsg)) errmsg = "array partly set: complex_sizes"
          return
        end if
      end do
    case ("niterations")
      status = NML_ERR_INVALID_INDEX
      if (present(errmsg)) errmsg = "array query not supported for scalar: niterations"
    case ("tolerance")
      status = NML_ERR_INVALID_INDEX
      if (present(errmsg)) errmsg = "array query not supported for scalar: tolerance"
    case ("seed")
      status = NML_ERR_INVALID_INDEX
      if (present(errmsg)) errmsg = "array query not supported for scalar: seed"
    case ("dds_r")
      status = NML_ERR_INVALID_INDEX
      if (present(errmsg)) errmsg = "array query not supported for scalar: dds_r"
    case ("mcmc_opti")
      status = NML_ERR_INVALID_INDEX
      if (present(errmsg)) errmsg = "array query not supported for scalar: mcmc_opti"
    case ("mcmc_error_params")
      if (size(filled) /= 3) then
        status = NML_ERR_INVALID_INDEX
        if (present(errmsg)) errmsg = "shape rank mismatch for 'mcmc_error_params'"
        return
      end if
      if (.not. allocated(this%mcmc_error_params)) then
        status = NML_ERR_NOT_SET
        if (present(errmsg)) errmsg = "array storage unavailable: mcmc_error_params"
        return
      end if
      do idx__3 = 1, size(this%mcmc_error_params, 3)
        do idx__2 = 1, size(this%mcmc_error_params, 2)
          do idx__1 = 1, size(this%mcmc_error_params, 1)
            if (ieee_is_nan(this%mcmc_error_params(idx__1, idx__2, idx__3))) cycle
            if (idx__1 > filled(1)) filled(1) = idx__1
            if (idx__2 > filled(2)) filled(2) = idx__2
            if (idx__3 > filled(3)) filled(3) = idx__3
          end do
        end do
      end do
      do idx__3 = 1, filled(3)
        do idx__2 = 1, filled(2)
          do idx__1 = 1, filled(1)
            if (ieee_is_nan(this%mcmc_error_params(idx__1, idx__2, idx__3))) then
              status = NML_ERR_PARTLY_SET
              if (present(errmsg)) errmsg = "array partly set: mcmc_error_params"
              return
            end if
          end do
        end do
      end do
    case ("include_parameters")
      if (size(filled) /= 1) then
        status = NML_ERR_INVALID_INDEX
        if (present(errmsg)) errmsg = "shape rank mismatch for 'include_parameters'"
        return
      end if
      filled(1) = size(this%include_parameters, 1)
    case default
      status = NML_ERR_INVALID_NAME
      if (present(errmsg)) errmsg = "unknown field: " // trim(name)
    end select
  end function nml_optimization_filled_shape

  !> \brief Validate required values and constraints
  integer function nml_optimization_is_valid(this, errmsg) result(status)
    class(nml_optimization_t), intent(in) :: this !< namelist instance
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
    istat = this%is_set("method", errmsg=errmsg)
    if (istat == NML_ERR_NOT_SET) then
      status = NML_ERR_REQUIRED
      if (present(errmsg)) then
        if (len_trim(errmsg) == 0) then
          errmsg = "field not set: method"
        end if
        errmsg = "required " // trim(errmsg)
      end if
      return
    end if
    if (istat /= NML_OK) then
      status = istat
      return
    end if
    istat = this%is_set("niterations", errmsg=errmsg)
    if (istat == NML_ERR_NOT_SET) then
      status = NML_ERR_REQUIRED
      if (present(errmsg)) then
        if (len_trim(errmsg) == 0) then
          errmsg = "field not set: niterations"
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
    ! enum constraints
    istat = this%is_set("method", errmsg=errmsg)
    if (istat == NML_OK) then
      if (.not. method__in_enum(this%method)) then
        status = NML_ERR_ENUM
        if (present(errmsg)) errmsg = "enum constraint failed: method"
        return
      end if
    else if (istat /= NML_ERR_NOT_SET) then
      status = istat
      return
    end if
    if (.not. all(try_methods__in_enum(this%try_methods, allow_missing=.true.))) then
      status = NML_ERR_ENUM
      if (present(errmsg)) errmsg = "enum constraint failed: try_methods"
      return
    end if
    if (.not. all(complex_sizes__in_enum(this%complex_sizes, allow_missing=.true.))) then
      status = NML_ERR_ENUM
      if (present(errmsg)) errmsg = "enum constraint failed: complex_sizes"
      return
    end if
    ! bounds constraints
    istat = this%is_set("niterations", errmsg=errmsg)
    if (istat == NML_OK) then
      if (.not. niterations__in_bounds(this%niterations)) then
        status = NML_ERR_BOUNDS
        if (present(errmsg)) errmsg = "bounds constraint failed: niterations"
        return
      end if
    else if (istat /= NML_ERR_NOT_SET) then
      status = istat
      return
    end if
    istat = this%is_set("tolerance", errmsg=errmsg)
    if (istat == NML_OK) then
      if (.not. tolerance__in_bounds(this%tolerance)) then
        status = NML_ERR_BOUNDS
        if (present(errmsg)) errmsg = "bounds constraint failed: tolerance"
        return
      end if
    else if (istat /= NML_ERR_NOT_SET) then
      status = istat
      return
    end if
    istat = this%is_set("dds_r", errmsg=errmsg)
    if (istat == NML_OK) then
      if (.not. dds_r__in_bounds(this%dds_r)) then
        status = NML_ERR_BOUNDS
        if (present(errmsg)) errmsg = "bounds constraint failed: dds_r"
        return
      end if
    else if (istat /= NML_ERR_NOT_SET) then
      status = istat
      return
    end if
    if (allocated(this%mcmc_error_params)) then
    if (.not. all(mcmc_error_params__in_bounds(this%mcmc_error_params, allow_missing=.true.))) then
      status = NML_ERR_BOUNDS
      if (present(errmsg)) errmsg = "bounds constraint failed: mcmc_error_params"
      return
    end if
    end if
  end function nml_optimization_is_valid

end module nml_optimization
