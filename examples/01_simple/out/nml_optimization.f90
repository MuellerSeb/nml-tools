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
    buf, &
    max_iter, &
    NML_ERR_PARTLY_SET
  use ieee_arithmetic, only: ieee_value, ieee_quiet_nan, ieee_is_nan
  ! kind specifiers listed in the nml-tools configuration file
  use iso_fortran_env, only: &
    i4=>int32, &
    dp=>real64

  implicit none

  ! default values
  integer(i4), parameter, public :: seed_default = -9_i4
  real(dp), parameter, public :: dds_r_default = 0.2_dp
  logical, parameter, public :: mcmc_opti_default = .true.
  logical, parameter, public :: include_parameters_default = .true.

  ! enum values
  character(len=buf), parameter, public :: &
    method_enum_values(3) = [character(len=buf) :: "DDS", "MCMC", "SCE"]
  character(len=buf), parameter, public :: &
    try_methods_enum_values(3) = [character(len=buf) :: "DDS", "MCMC", "SCE"]
  integer(i4), parameter, public :: complex_sizes_enum_values(5) = [5_i4, 10_i4, 15_i4, 20_i4, 30_i4]

  ! bounds values
  integer(i4), parameter, public :: niterations_min = 10_i4
  real(dp), parameter, public :: tolerance_min_excl = 0.0_dp
  real(dp), parameter, public :: dds_r_min_excl = 0.0_dp
  real(dp), parameter, public :: mcmc_error_params_min = 0.0_dp

  !> \class nml_optimization_t
  !> \brief Optimization configurations
  !> \details All relevant configurations for the optimization parameters.
  type, public :: nml_optimization_t
    logical :: is_configured = .false. !< whether the namelist has been configured
    character(len=buf) :: name !< Optimization name
    character(len=buf) :: method !< Optimization method
    character(len=buf), dimension(3) :: try_methods !< Try alternative methods
    integer(i4), dimension(3) :: complex_sizes !< Complex sizes for SCE
    integer(i4) :: niterations !< Number of iterations
    real(dp) :: tolerance !< Convergence tolerance
    integer(i4) :: seed !< Random seed
    real(dp) :: dds_r !< DDS perturbation rate
    logical :: mcmc_opti !< MCMC optimization
    real(dp), dimension(3, 2, max_iter) :: mcmc_error_params !< MCMC error parameters per iteration
    logical, dimension(3) :: include_parameters !< Include parameters
  contains
    procedure :: init => nml_optimization_init
    procedure :: from_file => nml_optimization_from_file
    procedure :: set => nml_optimization_set
    procedure :: is_set => nml_optimization_is_set
    procedure :: filled_shape => nml_optimization_filled_shape
    procedure :: is_valid => nml_optimization_is_valid
  end type nml_optimization_t

contains

  !> \brief Check whether a value is part of an enum
  elemental logical function method_in_enum(val, allow_missing) result(in_enum)
    character(len=*), intent(in) :: val
    logical, intent(in), optional :: allow_missing

    if (present(allow_missing)) then
      if (allow_missing) then
        if (val == repeat(achar(0), len(val))) then
          in_enum = .true.
          return
        end if
      end if
    end if
    in_enum = any(trim(val) == method_enum_values)
  end function method_in_enum

  !> \brief Check whether a value is part of an enum
  elemental logical function try_methods_in_enum(val, allow_missing) result(in_enum)
    character(len=*), intent(in) :: val
    logical, intent(in), optional :: allow_missing

    if (present(allow_missing)) then
      if (allow_missing) then
        if (val == repeat(achar(0), len(val))) then
          in_enum = .true.
          return
        end if
      end if
    end if
    in_enum = any(trim(val) == try_methods_enum_values)
  end function try_methods_in_enum

  !> \brief Check whether a value is part of an enum
  elemental logical function complex_sizes_in_enum(val, allow_missing) result(in_enum)
    integer(i4), intent(in) :: val
    logical, intent(in), optional :: allow_missing

    if (present(allow_missing)) then
      if (allow_missing) then
        if (val == -huge(val)) then
          in_enum = .true.
          return
        end if
      end if
    end if
    in_enum = any(val == complex_sizes_enum_values)
  end function complex_sizes_in_enum

  !> \brief Check whether a value is within bounds
  elemental logical function niterations_in_bounds(val, allow_missing) result(in_bounds)
    integer(i4), intent(in) :: val
    logical, intent(in), optional :: allow_missing

    if (present(allow_missing)) then
      if (allow_missing) then
        if (val == -huge(val)) then
          in_bounds = .true.
          return
        end if
      end if
    end if

    in_bounds = .true.
    if (val < niterations_min) in_bounds = .false.
  end function niterations_in_bounds

  !> \brief Check whether a value is within bounds
  elemental logical function tolerance_in_bounds(val, allow_missing) result(in_bounds)
    real(dp), intent(in) :: val
    logical, intent(in), optional :: allow_missing

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

  !> \brief Check whether a value is within bounds
  elemental logical function dds_r_in_bounds(val, allow_missing) result(in_bounds)
    real(dp), intent(in) :: val
    logical, intent(in), optional :: allow_missing

    if (present(allow_missing)) then
      if (allow_missing) then
        if (ieee_is_nan(val)) then
          in_bounds = .true.
          return
        end if
      end if
    end if

    in_bounds = .true.
    if (val <= dds_r_min_excl) in_bounds = .false.
  end function dds_r_in_bounds

  !> \brief Check whether a value is within bounds
  elemental logical function mcmc_error_params_in_bounds(val, allow_missing) result(in_bounds)
    real(dp), intent(in) :: val
    logical, intent(in), optional :: allow_missing

    if (present(allow_missing)) then
      if (allow_missing) then
        if (ieee_is_nan(val)) then
          in_bounds = .true.
          return
        end if
      end if
    end if

    in_bounds = .true.
    if (val < mcmc_error_params_min) in_bounds = .false.
  end function mcmc_error_params_in_bounds

  !> \brief Initialize defaults and sentinels for optimization
  integer function nml_optimization_init(this, errmsg) result(status)
    class(nml_optimization_t), intent(inout) :: this
    character(len=*), intent(out), optional :: errmsg

    status = NML_OK
    if (present(errmsg)) errmsg = ""
    this%is_configured = .false.

    ! sentinel values for required/optional parameters
    this%name = repeat(achar(0), len(this%name)) ! sentinel for optional string
    this%method = repeat(achar(0), len(this%method)) ! NULL string as sentinel for required string
    this%try_methods = repeat(achar(0), len(this%try_methods)) ! sentinel for optional string array
    this%complex_sizes = -huge(this%complex_sizes) ! sentinel for optional integer array
    this%niterations = -huge(this%niterations) ! sentinel for required integer
    this%tolerance = ieee_value(this%tolerance, ieee_quiet_nan) ! sentinel for required real
    this%mcmc_error_params = ieee_value(this%mcmc_error_params, ieee_quiet_nan) ! sentinel for required real array
    ! default values
    this%seed = seed_default
    this%dds_r = dds_r_default
    this%mcmc_opti = mcmc_opti_default ! bool values always need a default
    this%include_parameters = include_parameters_default
  end function nml_optimization_init

  !> \brief Read optimization namelist from file
  integer function nml_optimization_from_file(this, file, errmsg) result(status)
    class(nml_optimization_t), intent(inout) :: this
    character(len=*), intent(in) :: file !< path to namelist file
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
    real(dp), dimension(3, 2, max_iter) :: mcmc_error_params
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
    mcmc_error_params, &
    name, &
    try_methods, &
    complex_sizes, &
    seed, &
    dds_r, &
    mcmc_opti, &
    include_parameters, &
    errmsg) result(status)

    class(nml_optimization_t), intent(inout) :: this
    character(len=*), intent(out), optional :: errmsg
    character(len=*), intent(in) :: method
    integer(i4), intent(in) :: niterations
    real(dp), intent(in) :: tolerance
    real(dp), dimension(:, :, :), intent(in) :: mcmc_error_params
    character(len=*), intent(in), optional :: name
    character(len=*), dimension(3), intent(in), optional :: try_methods
    integer(i4), dimension(3), intent(in), optional :: complex_sizes
    integer(i4), intent(in), optional :: seed
    real(dp), intent(in), optional :: dds_r
    logical, intent(in), optional :: mcmc_opti
    logical, dimension(:), intent(in), optional :: include_parameters
    integer :: &
      lb_1, &
      lb_2, &
      lb_3, &
      ub_1, &
      ub_2, &
      ub_3

    status = this%init(errmsg=errmsg)
    if (status /= NML_OK) return

    ! required parameters
    this%method = method
    this%niterations = niterations
    this%tolerance = tolerance
    if (size(mcmc_error_params, 1) /= size(this%mcmc_error_params, 1)) then
      status = NML_ERR_INVALID_INDEX
      if (present(errmsg)) errmsg = "dimension 1 mismatch for 'mcmc_error_params'"
      return
    end if
    if (size(mcmc_error_params, 2) > size(this%mcmc_error_params, 2)) then
      status = NML_ERR_INVALID_INDEX
      if (present(errmsg)) errmsg = "dimension 2 exceeds bounds for 'mcmc_error_params'"
      return
    end if
    lb_2 = lbound(this%mcmc_error_params, 2)
    ub_2 = lb_2 + size(mcmc_error_params, 2) - 1
    if (size(mcmc_error_params, 3) > size(this%mcmc_error_params, 3)) then
      status = NML_ERR_INVALID_INDEX
      if (present(errmsg)) errmsg = "dimension 3 exceeds bounds for 'mcmc_error_params'"
      return
    end if
    lb_3 = lbound(this%mcmc_error_params, 3)
    ub_3 = lb_3 + size(mcmc_error_params, 3) - 1
    this%mcmc_error_params(:, lb_2:ub_2, lb_3:ub_3) = mcmc_error_params
    ! override with provided values
    if (present(name)) this%name = name
    if (present(try_methods)) this%try_methods = try_methods
    if (present(complex_sizes)) this%complex_sizes = complex_sizes
    if (present(seed)) this%seed = seed
    if (present(dds_r)) this%dds_r = dds_r
    if (present(mcmc_opti)) this%mcmc_opti = mcmc_opti
    if (present(include_parameters)) then
      if (size(include_parameters, 1) > size(this%include_parameters, 1)) then
        status = NML_ERR_INVALID_INDEX
        if (present(errmsg)) errmsg = "dimension 1 exceeds bounds for 'include_parameters'"
        return
      end if
      lb_1 = lbound(this%include_parameters, 1)
      ub_1 = lb_1 + size(include_parameters, 1) - 1
      this%include_parameters(lb_1:ub_1) = include_parameters
    end if

    ! mark as configured
    this%is_configured = .true.
    status = NML_OK
  end function nml_optimization_set

  !> \brief Check whether a namelist value was set
  integer function nml_optimization_is_set(this, name, idx, errmsg) result(status)
    class(nml_optimization_t), intent(in) :: this
    character(len=*), intent(in) :: name
    integer, intent(in), optional :: idx(:)
    character(len=*), intent(out), optional :: errmsg

    status = NML_OK
    if (present(errmsg)) errmsg = ""
    select case (trim(name))
    case ("name")
      if (present(idx)) then
        status = NML_ERR_INVALID_INDEX
        if (present(errmsg)) errmsg = "index not supported for 'name'"
        return
      end if
      if (this%name == repeat(achar(0), len(this%name))) status = NML_ERR_NOT_SET
    case ("method")
      if (present(idx)) then
        status = NML_ERR_INVALID_INDEX
        if (present(errmsg)) errmsg = "index not supported for 'method'"
        return
      end if
      if (this%method == repeat(achar(0), len(this%method))) status = NML_ERR_NOT_SET
    case ("try_methods")
      if (present(idx)) then
        status = idx_check(idx, lbound(this%try_methods), ubound(this%try_methods), &
          "try_methods", errmsg)
        if (status /= NML_OK) return
        if (this%try_methods(idx(1)) == repeat(achar(0), len(this%try_methods))) status = NML_ERR_NOT_SET
      else
        if (all(this%try_methods == repeat(achar(0), len(this%try_methods)))) status = NML_ERR_NOT_SET
      end if
    case ("complex_sizes")
      if (present(idx)) then
        status = idx_check(idx, lbound(this%complex_sizes), ubound(this%complex_sizes), &
          "complex_sizes", errmsg)
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
      if (present(idx)) then
        status = idx_check(idx, lbound(this%mcmc_error_params), ubound(this%mcmc_error_params), &
          "mcmc_error_params", errmsg)
        if (status /= NML_OK) return
        if (ieee_is_nan(this%mcmc_error_params(idx(1), idx(2), idx(3)))) status = NML_ERR_NOT_SET
      else
        if (all(ieee_is_nan(this%mcmc_error_params))) status = NML_ERR_NOT_SET
      end if
    case ("include_parameters")
      if (present(idx)) then
        status = idx_check(idx, lbound(this%include_parameters), ubound(this%include_parameters), &
          "include_parameters", errmsg)
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
  end function nml_optimization_is_set

  !> \brief Determine the filled shape along flexible dimensions
  integer function nml_optimization_filled_shape(this, name, filled, errmsg) result(status)
    class(nml_optimization_t), intent(in) :: this
    character(len=*), intent(in) :: name
    integer, intent(out) :: filled(:)
    character(len=*), intent(out), optional :: errmsg
    integer :: idx
    integer :: dim
    integer :: &
      lb_1, &
      lb_2, &
      lb_3, &
      ub_1, &
      ub_2, &
      ub_3

    status = NML_OK
    if (present(errmsg)) errmsg = ""
    select case (trim(name))
    case ("mcmc_error_params")
      if (size(filled) /= 3) then
        status = NML_ERR_INVALID_INDEX
        if (present(errmsg)) errmsg = "shape rank mismatch for 'mcmc_error_params'"
        return
      end if
      do dim = 1, 3
        filled(dim) = size(this%mcmc_error_params, dim)
      end do
      filled(2) = 0
      do idx = ubound(this%mcmc_error_params, 2), &
        lbound(this%mcmc_error_params, 2), -1
        if (.not. (all(ieee_is_nan(this%mcmc_error_params(:, idx, :))))) then
          filled(2) = idx - lbound(this%mcmc_error_params, 2) + 1
          exit
        end if
      end do
      filled(3) = 0
      do idx = ubound(this%mcmc_error_params, 3), &
        lbound(this%mcmc_error_params, 3), -1
        if (.not. (all(ieee_is_nan(this%mcmc_error_params(:, :, idx))))) then
          filled(3) = idx - lbound(this%mcmc_error_params, 3) + 1
          exit
        end if
      end do
      if (minval(filled) > 0) then
        lb_2 = lbound(this%mcmc_error_params, 2)
        ub_2 = lb_2 + filled(2) - 1
        lb_3 = lbound(this%mcmc_error_params, 3)
        ub_3 = lb_3 + filled(3) - 1
        if (any(ieee_is_nan(this%mcmc_error_params(:, lb_2:ub_2, lb_3:ub_3)))) then
          status = NML_ERR_PARTLY_SET
          if (present(errmsg)) errmsg = "array partly set: mcmc_error_params"
          return
        end if
      end if
    case default
      status = NML_ERR_INVALID_NAME
      if (present(errmsg)) errmsg = "field is not a flexible array: " // trim(name)
    end select
  end function nml_optimization_filled_shape

  !> \brief Validate required values and constraints
  integer function nml_optimization_is_valid(this, errmsg) result(status)
    class(nml_optimization_t), intent(in) :: this
    character(len=*), intent(out), optional :: errmsg
    integer :: istat
    integer, allocatable :: filled(:)

    status = NML_OK
    if (present(errmsg)) errmsg = ""

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
    ! flexible arrays
    if (allocated(filled)) deallocate(filled)
    allocate(filled(3))
    istat = this%filled_shape("mcmc_error_params", filled, errmsg=errmsg)
    if (istat == NML_ERR_PARTLY_SET) then
      status = istat
      if (present(errmsg)) then
        if (len_trim(errmsg) == 0) errmsg = "array partly set: mcmc_error_params"
      end if
      return
    end if
    if (istat /= NML_OK) then
      status = istat
      return
    end if
    if (minval(filled) == 0) then
      status = NML_ERR_REQUIRED
      if (present(errmsg)) errmsg = "required field not set: mcmc_error_params"
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
    if (.not. all(try_methods_in_enum(this%try_methods, allow_missing=.true.))) then
      status = NML_ERR_ENUM
      if (present(errmsg)) errmsg = "enum constraint failed: try_methods"
      return
    end if
    if (.not. all(complex_sizes_in_enum(this%complex_sizes, allow_missing=.true.))) then
      status = NML_ERR_ENUM
      if (present(errmsg)) errmsg = "enum constraint failed: complex_sizes"
      return
    end if
    ! bounds constraints
    istat = this%is_set("niterations", errmsg=errmsg)
    if (istat == NML_OK) then
      if (.not. niterations_in_bounds(this%niterations)) then
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
      if (.not. tolerance_in_bounds(this%tolerance)) then
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
      if (.not. dds_r_in_bounds(this%dds_r)) then
        status = NML_ERR_BOUNDS
        if (present(errmsg)) errmsg = "bounds constraint failed: dds_r"
        return
      end if
    else if (istat /= NML_ERR_NOT_SET) then
      status = istat
      return
    end if
    if (.not. all(mcmc_error_params_in_bounds(this%mcmc_error_params, allow_missing=.true.))) then
      status = NML_ERR_BOUNDS
      if (present(errmsg)) errmsg = "bounds constraint failed: mcmc_error_params"
      return
    end if
  end function nml_optimization_is_valid

end module nml_optimization
