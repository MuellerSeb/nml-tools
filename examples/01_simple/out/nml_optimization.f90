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
    idx__check, &
    to__lower, &
    buf, &
    max_iter__dim_default, &
    NML_ERR_PARTLY_SET
  use ieee_arithmetic, only: nml__ieee_value => ieee_value, &
    nml__ieee_quiet_nan => ieee_quiet_nan, nml__ieee_is_nan => ieee_is_nan
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

  private :: nml_optimization_read__from_file

  !> \class nml_optimization_data_t
  !> \brief Schema-backed values for optimization
  type, public :: nml_optimization_data_t
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
  end type nml_optimization_data_t

  !> \class nml_optimization_dims_t
  !> \brief Runtime dimensions for optimization
  type, public :: nml_optimization_dims_t
    integer :: max_iter = max_iter__dim_default !< runtime dimension for max_iter
  end type nml_optimization_dims_t

  !> \class nml_optimization_t
  !> \brief Optimization configurations
  !> \details All relevant configurations for the optimization parameters.
  type, public :: nml_optimization_t
    type(nml_optimization_data_t) :: data !< schema-backed namelist values
    type(nml_optimization_dims_t) :: dims !< runtime array dimensions
    logical :: is_configured = .false. !< whether the namelist has been configured
  contains
    procedure :: init => nml_optimization_init
    procedure :: set_dims => nml_optimization_set_dims
    procedure :: from_file => nml_optimization_from_file
    procedure :: set => nml_optimization_set
    procedure :: is_set => nml_optimization_is_set
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
        if (nml__ieee_is_nan(val)) then
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
        if (nml__ieee_is_nan(val)) then
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
        if (nml__ieee_is_nan(val)) then
          in_bounds = .true.
          return
        end if
      end if
    end if

    in_bounds = .true.
    if (val < mcmc_error_params__min) in_bounds = .false.
  end function mcmc_error_params__in_bounds

  !> \brief Initialize defaults and sentinels for optimization
  integer function nml_optimization_init(nml__obj, errmsg) result(nml__status)
    class(nml_optimization_t), intent(inout) :: nml__obj !< namelist instance
    character(len=*), intent(out), optional :: errmsg !< error message for non-OK status values

    nml__status = NML_OK
    if (present(errmsg)) errmsg = ""
    nml__obj%is_configured = .false.

    ! allocate runtime-sized fields
    if (allocated(nml__obj%data%mcmc_error_params)) deallocate(nml__obj%data%mcmc_error_params)
    allocate(nml__obj%data%mcmc_error_params(3, 2, nml__obj%dims%max_iter))

    ! sentinel values for required/optional parameters
    nml__obj%data%name = achar(0) ! sentinel for optional string
    nml__obj%data%method = achar(0) ! NULL string as sentinel for required string
    nml__obj%data%try_methods = achar(0) ! sentinel for optional string array
    nml__obj%data%complex_sizes = -huge(nml__obj%data%complex_sizes) ! sentinel for optional integer array
    nml__obj%data%niterations = -huge(nml__obj%data%niterations) ! sentinel for required integer
    nml__obj%data%tolerance = nml__ieee_value(nml__obj%data%tolerance, nml__ieee_quiet_nan) ! sentinel for required real
    nml__obj%data%mcmc_error_params = nml__ieee_value(nml__obj%data%mcmc_error_params, nml__ieee_quiet_nan) ! sentinel for required real array
    ! default values
    nml__obj%data%seed = seed__default
    nml__obj%data%dds_r = dds_r__default
    nml__obj%data%mcmc_opti = mcmc_opti__default ! bool values always need a default
    nml__obj%data%include_parameters = include_parameters__default
  end function nml_optimization_init

  !> \brief Reset runtime dimensions for optimization
  integer function nml_optimization_set_dims(nml__obj, &
    max_iter, &
    errmsg) result(nml__status)
    class(nml_optimization_t), intent(inout) :: nml__obj !< namelist instance
    integer, intent(in), optional :: max_iter !< runtime dimension override for max_iter
    integer :: candidate__max_iter
    character(len=*), intent(out), optional :: errmsg !< error message for non-OK status values

    nml__status = NML_OK
    if (present(errmsg)) errmsg = ""
    if (present(max_iter)) then
      candidate__max_iter = max_iter
    else
      candidate__max_iter = max_iter__dim_default
    end if
    if (candidate__max_iter <= 0) then
      nml__status = NML_ERR_INVALID_INDEX
      if (present(errmsg)) errmsg = "dimension 'max_iter' must be positive"
      return
    end if
    nml__obj%dims%max_iter = candidate__max_iter

    ! deallocate runtime-sized fields; init/set/from_file allocate them again
    if (allocated(nml__obj%data%mcmc_error_params)) deallocate(nml__obj%data%mcmc_error_params)
    nml__obj%is_configured = .false.
  end function nml_optimization_set_dims


  !> \brief Read optimization namelist from file
  integer function nml_optimization_from_file(nml__obj, file, errmsg) result(nml__status)
    class(nml_optimization_t), intent(inout) :: nml__obj !< namelist instance
    character(len=*), intent(in) :: file !< path to namelist file
    character(len=*), intent(out), optional :: errmsg !< error message for non-OK status values

    nml__status = nml_optimization_read__from_file(nml__obj, file, errmsg)
  end function nml_optimization_from_file

  integer function nml_optimization_read__from_file(nml__obj, nml__file, errmsg) &
    result(nml__status)
    class(nml_optimization_t), intent(inout) :: nml__obj
    character(len=*), intent(in) :: nml__file
    character(len=*), intent(out), optional :: errmsg
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
    type(nml_file_t) :: nml__reader
    integer :: nml__iostat
    integer :: nml__close_status
    character(len=nml_line_buffer) :: nml__iomsg

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

    nml__status = nml__obj%init(errmsg=errmsg)
    if (nml__status /= NML_OK) return
    ! allocate local namelist variables matching runtime-sized fields
    if (allocated(mcmc_error_params)) deallocate(mcmc_error_params)
    allocate(mcmc_error_params(3, 2, nml__obj%dims%max_iter))
    name = nml__obj%data%name
    method = nml__obj%data%method
    try_methods = nml__obj%data%try_methods
    complex_sizes = nml__obj%data%complex_sizes
    niterations = nml__obj%data%niterations
    tolerance = nml__obj%data%tolerance
    seed = nml__obj%data%seed
    dds_r = nml__obj%data%dds_r
    mcmc_opti = nml__obj%data%mcmc_opti
    mcmc_error_params = nml__obj%data%mcmc_error_params
    include_parameters = nml__obj%data%include_parameters

    nml__status = nml__reader%open(nml__file, errmsg=errmsg)
    if (nml__status /= NML_OK) return

    nml__status = nml__reader%find("optimization", errmsg=errmsg)
    if (nml__status /= NML_OK) then
      nml__close_status = nml__reader%close()
      return
    end if

    ! read namelist
    read(nml__reader%unit, nml=optimization, iostat=nml__iostat, iomsg=nml__iomsg)
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
    nml__obj%data%name = name
    nml__obj%data%method = method
    nml__obj%data%try_methods = try_methods
    nml__obj%data%complex_sizes = complex_sizes
    nml__obj%data%niterations = niterations
    nml__obj%data%tolerance = tolerance
    nml__obj%data%seed = seed
    nml__obj%data%dds_r = dds_r
    nml__obj%data%mcmc_opti = mcmc_opti
    nml__obj%data%mcmc_error_params = mcmc_error_params
    nml__obj%data%include_parameters = include_parameters

    ! mark as configured
    nml__obj%is_configured = .true.
    nml__status = NML_OK
  end function nml_optimization_read__from_file

  !> \brief Set optimization values
  integer function nml_optimization_set(nml__obj, &
    method, &
    niterations, &
    tolerance, &
    mcmc_error_params, &
    name, &
    try_methods, &
    complex_sizes, &
    seed, &
    dds_r, &
    mcmc_opti, &
    include_parameters, &
    errmsg) result(nml__status)

    class(nml_optimization_t), intent(inout) :: nml__obj !< namelist instance
    character(len=*), intent(out), optional :: errmsg !< error message for non-OK status values
    character(len=*), intent(in) :: method !< Optimization method
    integer(i4), intent(in) :: niterations !< Number of iterations
    real(dp), intent(in) :: tolerance !< Convergence tolerance
    real(dp), dimension(:, :, :), intent(in) :: mcmc_error_params !< MCMC error parameters per iteration
    character(len=*), intent(in), optional :: name !< Optimization name
    character(len=*), dimension(:), intent(in), optional :: try_methods !< Try alternative methods
    integer(i4), dimension(:), intent(in), optional :: complex_sizes !< Complex sizes for SCE
    integer(i4), intent(in), optional :: seed !< Random seed
    real(dp), intent(in), optional :: dds_r !< DDS perturbation rate
    logical, intent(in), optional :: mcmc_opti !< MCMC optimization
    logical, dimension(:), intent(in), optional :: include_parameters !< Include parameters
    nml__status = nml__obj%init(errmsg=errmsg)
    if (nml__status /= NML_OK) return

    ! required parameters
    nml__obj%data%method = method
    nml__obj%data%niterations = niterations
    nml__obj%data%tolerance = tolerance
    if (size(mcmc_error_params, 1) > size(nml__obj%data%mcmc_error_params, 1)) then
      nml__status = NML_ERR_INVALID_INDEX
      if (present(errmsg)) errmsg = "dimension 1 exceeds bounds for 'mcmc_error_params'"
      return
    end if
    if (size(mcmc_error_params, 2) > size(nml__obj%data%mcmc_error_params, 2)) then
      nml__status = NML_ERR_INVALID_INDEX
      if (present(errmsg)) errmsg = "dimension 2 exceeds bounds for 'mcmc_error_params'"
      return
    end if
    if (size(mcmc_error_params, 3) > size(nml__obj%data%mcmc_error_params, 3)) then
      nml__status = NML_ERR_INVALID_INDEX
      if (present(errmsg)) errmsg = "dimension 3 exceeds bounds for 'mcmc_error_params'"
      return
    end if
    nml__obj%data%mcmc_error_params( &
      1:size(mcmc_error_params, 1), &
      1:size(mcmc_error_params, 2), &
      1:size(mcmc_error_params, 3)) = mcmc_error_params
    ! override with provided values
    if (present(name)) nml__obj%data%name = name
    if (present(try_methods)) then
      if (size(try_methods, 1) > size(nml__obj%data%try_methods, 1)) then
        nml__status = NML_ERR_INVALID_INDEX
        if (present(errmsg)) errmsg = "dimension 1 exceeds bounds for 'try_methods'"
        return
      end if
      nml__obj%data%try_methods( &
        1:size(try_methods, 1)) = try_methods
    end if
    if (present(complex_sizes)) then
      if (size(complex_sizes, 1) > size(nml__obj%data%complex_sizes, 1)) then
        nml__status = NML_ERR_INVALID_INDEX
        if (present(errmsg)) errmsg = "dimension 1 exceeds bounds for 'complex_sizes'"
        return
      end if
      nml__obj%data%complex_sizes( &
        1:size(complex_sizes, 1)) = complex_sizes
    end if
    if (present(seed)) nml__obj%data%seed = seed
    if (present(dds_r)) nml__obj%data%dds_r = dds_r
    if (present(mcmc_opti)) nml__obj%data%mcmc_opti = mcmc_opti
    if (present(include_parameters)) then
      if (size(include_parameters, 1) > size(nml__obj%data%include_parameters, 1)) then
        nml__status = NML_ERR_INVALID_INDEX
        if (present(errmsg)) errmsg = "dimension 1 exceeds bounds for 'include_parameters'"
        return
      end if
      nml__obj%data%include_parameters( &
        1:size(include_parameters, 1)) = include_parameters
    end if

    ! mark as configured
    nml__obj%is_configured = .true.
    nml__status = NML_OK
  end function nml_optimization_set

  !> \brief Check whether a namelist value was set
  integer function nml_optimization_is_set(nml__obj, name, idx, errmsg) result(nml__status)
    class(nml_optimization_t), intent(in) :: nml__obj !< namelist instance
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
    case ("name")
      if (present(idx)) then
        nml__status = NML_ERR_INVALID_INDEX
        if (present(errmsg)) errmsg = "index not supported for 'name'"
        return
      end if
      if (nml__obj%data%name == achar(0)) nml__status = NML_ERR_NOT_SET
    case ("method")
      if (present(idx)) then
        nml__status = NML_ERR_INVALID_INDEX
        if (present(errmsg)) errmsg = "index not supported for 'method'"
        return
      end if
      if (nml__obj%data%method == achar(0)) nml__status = NML_ERR_NOT_SET
    case ("try_methods")
      if (present(idx)) then
        nml__status = idx__check(idx, shape(nml__obj%data%try_methods), &
          "try_methods", errmsg)
        if (nml__status /= NML_OK) return
        if (nml__obj%data%try_methods(idx(1)) == achar(0)) nml__status = NML_ERR_NOT_SET
      else
        if (all(nml__obj%data%try_methods == achar(0))) nml__status = NML_ERR_NOT_SET
      end if
    case ("complex_sizes")
      if (present(idx)) then
        nml__status = idx__check(idx, shape(nml__obj%data%complex_sizes), &
          "complex_sizes", errmsg)
        if (nml__status /= NML_OK) return
        if (nml__obj%data%complex_sizes(idx(1)) == -huge(nml__obj%data%complex_sizes(idx(1)))) nml__status = NML_ERR_NOT_SET
      else
        if (all(nml__obj%data%complex_sizes == -huge(nml__obj%data%complex_sizes))) nml__status = NML_ERR_NOT_SET
      end if
    case ("niterations")
      if (present(idx)) then
        nml__status = NML_ERR_INVALID_INDEX
        if (present(errmsg)) errmsg = "index not supported for 'niterations'"
        return
      end if
      if (nml__obj%data%niterations == -huge(nml__obj%data%niterations)) nml__status = NML_ERR_NOT_SET
    case ("tolerance")
      if (present(idx)) then
        nml__status = NML_ERR_INVALID_INDEX
        if (present(errmsg)) errmsg = "index not supported for 'tolerance'"
        return
      end if
      if (nml__ieee_is_nan(nml__obj%data%tolerance)) nml__status = NML_ERR_NOT_SET
    case ("seed")
      if (present(idx)) then
        nml__status = NML_ERR_INVALID_INDEX
        if (present(errmsg)) errmsg = "index not supported for 'seed'"
        return
      end if
    case ("dds_r")
      if (present(idx)) then
        nml__status = NML_ERR_INVALID_INDEX
        if (present(errmsg)) errmsg = "index not supported for 'dds_r'"
        return
      end if
    case ("mcmc_opti")
      if (present(idx)) then
        nml__status = NML_ERR_INVALID_INDEX
        if (present(errmsg)) errmsg = "index not supported for 'mcmc_opti'"
        return
      end if
    case ("mcmc_error_params")
      if (.not. allocated(nml__obj%data%mcmc_error_params)) then
        nml__status = NML_ERR_NOT_SET
        return
      end if
      if (present(idx)) then
        nml__status = idx__check(idx, shape(nml__obj%data%mcmc_error_params), &
          "mcmc_error_params", errmsg)
        if (nml__status /= NML_OK) return
        if (nml__ieee_is_nan(nml__obj%data%mcmc_error_params(idx(1), idx(2), idx(3)))) nml__status = NML_ERR_NOT_SET
      else
        if (all(nml__ieee_is_nan(nml__obj%data%mcmc_error_params))) nml__status = NML_ERR_NOT_SET
      end if
    case ("include_parameters")
      if (present(idx)) then
        nml__status = idx__check(idx, shape(nml__obj%data%include_parameters), &
          "include_parameters", errmsg)
        if (nml__status /= NML_OK) return
      else
      end if
    case default
      nml__status = NML_ERR_INVALID_NAME
      if (present(errmsg)) errmsg = "unknown field: " // trim(name)
    end select
    if (nml__status == NML_ERR_NOT_SET .and. present(errmsg)) then
      if (len_trim(errmsg) == 0) errmsg = "field not set: " // trim(name)
    end if
  end function nml_optimization_is_set

  !> \brief Determine the filled shape along flexible dimensions
  integer function nml_optimization_filled_shape(nml__obj, name, filled, errmsg) result(nml__status)
    class(nml_optimization_t), intent(in) :: nml__obj !< namelist instance
    character(len=*), intent(in) :: name !< field name
    integer, intent(out) :: filled(:) !< filled shape of the requested field
    character(len=*), intent(out), optional :: errmsg !< error message for non-OK status values
    integer :: nml__idx
    integer :: nml__dim

    nml__status = NML_OK
    if (present(errmsg)) errmsg = ""
    select case (to__lower(trim(name)))
    case ("mcmc_error_params")
      if (size(filled) /= 3) then
        nml__status = NML_ERR_INVALID_INDEX
        if (present(errmsg)) errmsg = "shape rank mismatch for 'mcmc_error_params'"
        return
      end if
      if (.not. allocated(nml__obj%data%mcmc_error_params)) then
        filled = 0
        return
      end if
      do nml__dim = 1, 3
        filled(nml__dim) = size(nml__obj%data%mcmc_error_params, nml__dim)
      end do
      filled(2) = 0
      do nml__idx = size(nml__obj%data%mcmc_error_params, 2), 1, -1
        if (.not. (all(nml__ieee_is_nan(nml__obj%data%mcmc_error_params(:, nml__idx, :))))) then
          filled(2) = nml__idx
          exit
        end if
      end do
      filled(3) = 0
      do nml__idx = size(nml__obj%data%mcmc_error_params, 3), 1, -1
        if (.not. (all(nml__ieee_is_nan(nml__obj%data%mcmc_error_params(:, :, nml__idx))))) then
          filled(3) = nml__idx
          exit
        end if
      end do
      if (minval(filled) > 0) then
        if (any(nml__ieee_is_nan(nml__obj%data%mcmc_error_params(:, 1:filled(2), 1:filled(3))))) then
          nml__status = NML_ERR_PARTLY_SET
          if (present(errmsg)) errmsg = "array partly set: mcmc_error_params"
          return
        end if
      end if
    case default
      nml__status = NML_ERR_INVALID_NAME
      if (present(errmsg)) errmsg = "field is not a flexible array: " // trim(name)
    end select
  end function nml_optimization_filled_shape

  !> \brief Validate required values and constraints
  integer function nml_optimization_is_valid(nml__obj, errmsg) result(nml__status)
    class(nml_optimization_t), intent(in) :: nml__obj !< namelist instance
    character(len=*), intent(out), optional :: errmsg !< error message for non-OK status values
    integer :: nml__istat
    integer, allocatable :: nml__filled(:)

    nml__status = NML_OK
    if (present(errmsg)) errmsg = ""
    if (.not. nml__obj%is_configured) then
      nml__status = NML_ERR_NOT_SET
      if (present(errmsg)) errmsg = "namelist not configured; call set or from_file"
      return
    end if

    ! required parameters
    nml__istat = nml__obj%is_set("method", errmsg=errmsg)
    if (nml__istat == NML_ERR_NOT_SET) then
      nml__status = NML_ERR_REQUIRED
      if (present(errmsg)) then
        if (len_trim(errmsg) == 0) then
          errmsg = "field not set: method"
        end if
        errmsg = "required " // trim(errmsg)
      end if
      return
    end if
    if (nml__istat /= NML_OK) then
      nml__status = nml__istat
      return
    end if
    nml__istat = nml__obj%is_set("niterations", errmsg=errmsg)
    if (nml__istat == NML_ERR_NOT_SET) then
      nml__status = NML_ERR_REQUIRED
      if (present(errmsg)) then
        if (len_trim(errmsg) == 0) then
          errmsg = "field not set: niterations"
        end if
        errmsg = "required " // trim(errmsg)
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
      if (present(errmsg)) then
        if (len_trim(errmsg) == 0) then
          errmsg = "field not set: tolerance"
        end if
        errmsg = "required " // trim(errmsg)
      end if
      return
    end if
    if (nml__istat /= NML_OK) then
      nml__status = nml__istat
      return
    end if
    ! flexible arrays
    if (allocated(nml__filled)) deallocate(nml__filled)
    allocate(nml__filled(3))
    nml__istat = nml__obj%filled_shape( &
      "mcmc_error_params", nml__filled, errmsg=errmsg)
    if (nml__istat == NML_ERR_PARTLY_SET) then
      nml__status = nml__istat
      if (present(errmsg)) then
        if (len_trim(errmsg) == 0) errmsg = "array partly set: mcmc_error_params"
      end if
      return
    end if
    if (nml__istat /= NML_OK) then
      nml__status = nml__istat
      return
    end if
    if (minval(nml__filled) == 0) then
      nml__status = NML_ERR_REQUIRED
      if (present(errmsg)) errmsg = "required field not set: mcmc_error_params"
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
    if (.not. all(try_methods__in_enum(nml__obj%data%try_methods, allow_missing=.true.))) then
      nml__status = NML_ERR_ENUM
      if (present(errmsg)) errmsg = "enum constraint failed: try_methods"
      return
    end if
    if (.not. all(complex_sizes__in_enum(nml__obj%data%complex_sizes, allow_missing=.true.))) then
      nml__status = NML_ERR_ENUM
      if (present(errmsg)) errmsg = "enum constraint failed: complex_sizes"
      return
    end if
    ! bounds constraints
    nml__istat = nml__obj%is_set("niterations", errmsg=errmsg)
    if (nml__istat == NML_OK) then
      if (.not. niterations__in_bounds(nml__obj%data%niterations)) then
        nml__status = NML_ERR_BOUNDS
        if (present(errmsg)) errmsg = "bounds constraint failed: niterations"
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
        if (present(errmsg)) errmsg = "bounds constraint failed: tolerance"
        return
      end if
    else if (nml__istat /= NML_ERR_NOT_SET) then
      nml__status = nml__istat
      return
    end if
    nml__istat = nml__obj%is_set("dds_r", errmsg=errmsg)
    if (nml__istat == NML_OK) then
      if (.not. dds_r__in_bounds(nml__obj%data%dds_r)) then
        nml__status = NML_ERR_BOUNDS
        if (present(errmsg)) errmsg = "bounds constraint failed: dds_r"
        return
      end if
    else if (nml__istat /= NML_ERR_NOT_SET) then
      nml__status = nml__istat
      return
    end if
    if (allocated(nml__obj%data%mcmc_error_params)) then
    if (.not. all(mcmc_error_params__in_bounds(nml__obj%data%mcmc_error_params, allow_missing=.true.))) then
      nml__status = NML_ERR_BOUNDS
      if (present(errmsg)) errmsg = "bounds constraint failed: mcmc_error_params"
      return
    end if
    end if
  end function nml_optimization_is_valid

end module nml_optimization
