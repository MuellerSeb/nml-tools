!> \file nml_optimization.f90
!> \copydoc nml_optimization

!> \brief Optimization configurations
!> \details All relevant configurations for the optimization parameters.
!> \version 0.1
module nml_optimization
  use nml_helper, only: nml_file_t, buf, max_iter
  use ieee_arithmetic, only: ieee_value, ieee_quiet_nan, ieee_is_nan
  ! kind specifiers listed in the nml-tools configuration file
  use iso_fortran_env, only: i4=>int32, dp=>real64

  implicit none

  ! default values
  integer(i4), parameter, public :: seed_default = -9_i4
  real(dp), parameter, public :: dds_r_default = 0.2_dp
  logical, parameter, public :: mcmc_opti_default = .true.
  real(dp), parameter, public :: mcmc_error_params_default(4) = [0.01_dp, 0.6_dp, 0.2_dp, 0.3_dp]

  ! enum values
  character(len=buf), parameter, public :: method_enum_values(3) = [character(len=buf) :: 'DDS', 'MCMC', 'SCE']
  character(len=buf), parameter, public :: try_methods_enum_values(3) = [character(len=buf) :: 'DDS', 'MCMC', 'SCE']
  integer(i4), parameter, public :: complex_sizes_enum_values(5) = [5_i4, 10_i4, 15_i4, 20_i4, 30_i4]

  !> \class optimization_t
  !> \brief Optimization configurations
  !> \details All relevant configurations for the optimization parameters.
  type, public :: nml_optimization_t
    logical :: is_configured = .false. !< whether the namelist has been configured
    character(len=buf) :: name !< Optimization name
    character(len=buf) :: method !< Optimization method
    character(len=buf), dimension(3) :: try_methods !< Try alternative methods
    integer(i4), dimension(3) :: complex_sizes !< Complex sizes for SCE
    integer :: niterations !< Number of iterations
    real :: tolerance !< Convergence tolerance
    integer(i4) :: seed !< Random seed
    real(dp) :: dds_r !< DDS perturbation rate
    logical :: mcmc_opti !< MCMC optimization
    real(dp), dimension(3, 2, max_iter) :: mcmc_error_params !< MCMC error parameters per domain
  contains
    procedure :: init => nml_optimization_init
    procedure :: from_file => nml_optimization_from_file
    procedure :: set => nml_optimization_set
    procedure :: is_set => nml_optimization_is_set
    procedure :: is_valid => nml_optimization_is_valid
  end type nml_optimization_t

contains

  !> \brief Initialize defaults and sentinels for optimization
  subroutine nml_optimization_init(this)
    class(nml_optimization_t), intent(inout) :: this

    this%is_configured = .false.

    ! sentinel values for required/optional parameters
    this%name = repeat(achar(0), len(this%name)) ! sentinel for optional string
    this%method = repeat(achar(0), len(this%method)) ! NULL string as sentinel for required string
    this%try_methods = repeat(achar(0), len(this%try_methods)) ! sentinel for optional string array
    this%complex_sizes = -huge(this%complex_sizes) ! sentinel for optional integer array
    this%niterations = -huge(this%niterations) ! sentinel for required integer
    this%tolerance = ieee_value(this%tolerance, ieee_quiet_nan) ! sentinel for required real
    ! default values
    this%seed = seed_default
    this%dds_r = dds_r_default
    this%mcmc_opti = mcmc_opti_default ! bool values always need a default
    this%mcmc_error_params = reshape( &
      mcmc_error_params_default, &
      shape=[3, 2, max_iter], &
      order=[3, 2, 1], &
      pad=mcmc_error_params_default)
  end subroutine nml_optimization_init

  !> \brief Read optimization namelist from file
  subroutine nml_optimization_from_file(this, file, nml_found)
    class(nml_optimization_t), intent(inout) :: this
    character(len=*), intent(in) :: file !< path to namelist file
    !> whether namelist was found, if present this will prevent error raises, in case the namelist was not found
    logical, intent(out), optional :: nml_found
    ! namelist variables
    character(len=buf) :: name
    character(len=buf) :: method
    character(len=buf), dimension(3) :: try_methods
    integer(i4), dimension(3) :: complex_sizes
    integer :: niterations
    real :: tolerance
    integer(i4) :: seed
    real(dp) :: dds_r
    logical :: mcmc_opti
    real(dp), dimension(3, 2, max_iter) :: mcmc_error_params
    ! locals
    type(nml_file_t) :: nml
    logical :: found

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
      mcmc_error_params

    call this%init()
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

    call nml%open(file)
    if (present(nml_found)) nml_found = nml%is_open
    if (.not. nml%is_open) then
      if (present(nml_found)) return
      error stop "nml_optimization%from_file: could not open file"
    end if

    found = nml%find("optimization")
    if (present(nml_found)) nml_found = found
    if (.not. found) then
      call nml%close()
      if (present(nml_found)) return
      error stop "nml_optimization%from_file: namelist optimization not found"
    end if

    ! read namelist
    read(nml%unit, nml=optimization)
    call nml%close()

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

    ! mark as configured
    this%is_configured = .true.
  end subroutine nml_optimization_from_file

  !> \brief Set optimization values
  subroutine nml_optimization_set(this, &
    method, &
    niterations, &
    tolerance, &
    name, &
    try_methods, &
    complex_sizes, &
    seed, &
    dds_r, &
    mcmc_opti, &
    mcmc_error_params)

    class(nml_optimization_t), intent(inout) :: this
    character(len=*), intent(in) :: method
    integer, intent(in) :: niterations
    real, intent(in) :: tolerance
    character(len=*), intent(in), optional :: name
    character(len=*), dimension(3), intent(in), optional :: try_methods
    integer(i4), dimension(3), intent(in), optional :: complex_sizes
    integer(i4), intent(in), optional :: seed
    real(dp), intent(in), optional :: dds_r
    logical, intent(in), optional :: mcmc_opti
    real(dp), dimension(3, 2, max_iter), intent(in), optional :: mcmc_error_params

    call this%init()

    ! required parameters
    this%method = method
    this%niterations = niterations
    this%tolerance = tolerance
    ! override with provided values
    if (present(name)) this%name = name
    if (present(try_methods)) this%try_methods = try_methods
    if (present(complex_sizes)) this%complex_sizes = complex_sizes
    if (present(seed)) this%seed = seed
    if (present(dds_r)) this%dds_r = dds_r
    if (present(mcmc_opti)) this%mcmc_opti = mcmc_opti
    if (present(mcmc_error_params)) this%mcmc_error_params = mcmc_error_params

    ! mark as configured
    this%is_configured = .true.
  end subroutine nml_optimization_set

  !> \brief Check whether a namelist value was set
  logical function nml_optimization_is_set(this, name, idx) result(is_set)
    class(nml_optimization_t), intent(in) :: this
    character(len=*), intent(in) :: name
    integer, intent(in), optional :: idx(:)

    select case (trim(name))
    case ("name")
      if (present(idx)) then
        error stop "nml_optimization%is_set: index not supported for 'name'"
      end if
      is_set = .not. (this%name == repeat(achar(0), len(this%name)))
    case ("method")
      if (present(idx)) then
        error stop "nml_optimization%is_set: index not supported for 'method'"
      end if
      is_set = .not. (this%method == repeat(achar(0), len(this%method)))
    case ("try_methods")
      if (present(idx)) then
        if (size(idx) /= 1) then
          error stop "nml_optimization%is_set: index rank mismatch for 'try_methods'"
        end if
        if (any(idx < lbound(this%try_methods)) .or. any(idx > ubound(this%try_methods))) then
          error stop "nml_optimization%is_set: index out of bounds for 'try_methods'"
        end if
        is_set = .not. (this%try_methods(idx(1)) == repeat(achar(0), len(this%try_methods)))
      else
        is_set = .not. (all(this%try_methods == repeat(achar(0), len(this%try_methods))))
      end if
    case ("complex_sizes")
      if (present(idx)) then
        if (size(idx) /= 1) then
          error stop "nml_optimization%is_set: index rank mismatch for 'complex_sizes'"
        end if
        if (any(idx < lbound(this%complex_sizes)) .or. any(idx > ubound(this%complex_sizes))) then
          error stop "nml_optimization%is_set: index out of bounds for 'complex_sizes'"
        end if
        is_set = .not. (this%complex_sizes(idx(1)) == -huge(this%complex_sizes(idx(1))))
      else
        is_set = .not. (all(this%complex_sizes == -huge(this%complex_sizes)))
      end if
    case ("niterations")
      if (present(idx)) then
        error stop "nml_optimization%is_set: index not supported for 'niterations'"
      end if
      is_set = .not. (this%niterations == -huge(this%niterations))
    case ("tolerance")
      if (present(idx)) then
        error stop "nml_optimization%is_set: index not supported for 'tolerance'"
      end if
      is_set = .not. (ieee_is_nan(this%tolerance))
    case ("seed")
      if (present(idx)) then
        error stop "nml_optimization%is_set: index not supported for 'seed'"
      end if
      is_set = .true.
    case ("dds_r")
      if (present(idx)) then
        error stop "nml_optimization%is_set: index not supported for 'dds_r'"
      end if
      is_set = .true.
    case ("mcmc_opti")
      if (present(idx)) then
        error stop "nml_optimization%is_set: index not supported for 'mcmc_opti'"
      end if
      is_set = .true.
    case ("mcmc_error_params")
      if (present(idx)) then
        if (size(idx) /= 3) then
          error stop "nml_optimization%is_set: index rank mismatch for 'mcmc_error_params'"
        end if
        if (any(idx < lbound(this%mcmc_error_params)) .or. any(idx > ubound(this%mcmc_error_params))) then
          error stop "nml_optimization%is_set: index out of bounds for 'mcmc_error_params'"
        end if
        is_set = .true.
      else
        is_set = .true.
      end if
    case default
      error stop "nml_optimization%is_set: unknown field '" // trim(name) // "'"
    end select
  end function nml_optimization_is_set

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

  !> \brief Validate required values and constraints
  logical function nml_optimization_is_valid(this) result(is_valid)
    class(nml_optimization_t), intent(in) :: this

    is_valid = .true.

    ! required parameters
    if (.not. this%is_set("method")) then
      is_valid = .false.
      return
    end if
    if (.not. this%is_set("niterations")) then
      is_valid = .false.
      return
    end if
    if (.not. this%is_set("tolerance")) then
      is_valid = .false.
      return
    end if
    ! enum constraints
    if (this%is_set("method")) then
      if (.not. method_in_enum(this%method)) then
        is_valid = .false.
        return
      end if
    end if
    if (.not. all(try_methods_in_enum(this%try_methods, allow_missing=.true.))) then
      is_valid = .false.
      return
    end if
    if (.not. all(complex_sizes_in_enum(this%complex_sizes, allow_missing=.true.))) then
      is_valid = .false.
      return
    end if
  end function nml_optimization_is_valid

end module nml_optimization
