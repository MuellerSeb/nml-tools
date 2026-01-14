module nml_optimization
  use nml_helper, only: nml_file_t
  use ieee_arithmetic, only: ieee_value, ieee_quiet_nan, ieee_is_nan
  ! kind specifiers listed in the nml-tools configuration file
  use iso_fortran_env, only: i4=>int32, dp=>real64

  implicit none

  !> \class optimization_t
  !> \brief MHM optimization schema
  !> \details All relevant configurations for the optimization parameters of MHM
  type, public :: nml_optimization_t
    logical :: is_configured = .false. !< whether the namelist has been configured
    character(len=50) :: name !< Optimization name
    integer(i4) :: niterations !< Number of iterations
    real(dp) :: tolerance !< Convergence tolerance
    integer(i4) :: seed !< Random seed
    real(dp) :: dds_r !< DDS perturbation rate
    logical :: mcmc_opti !< MCMC optimization
    real(dp), dimension(2, 3) :: mcmc_error_params !< MCMC error parameters per domain
  contains
    procedure :: init => nml_optimization_init
    procedure :: from_file => nml_optimization_from_file
    procedure :: set => nml_optimization_set
    procedure :: is_set => nml_optimization_is_set
  end type nml_optimization_t
contains

  !> \brief Initialize defaults and sentinels for optimization
  subroutine nml_optimization_init(this)
    class(nml_optimization_t), intent(inout) :: this

    this%is_configured = .false.

    ! sentinel values for required/optional parameters
    this%name = achar(0) ! sentinel for optional string
    this%niterations = -huge(this%niterations) ! sentinel for required integer
    this%tolerance = ieee_value(this%tolerance, ieee_quiet_nan) ! sentinel for required real
    ! default values
    this%seed = -9_i4
    this%dds_r = 0.2_dp
    this%mcmc_opti = .true. ! bool values always need a default
    this%mcmc_error_params = reshape([0.01_dp, 0.6_dp], shape=[2, 3], pad=[0.01_dp, 0.6_dp])
  end subroutine nml_optimization_init

  !> \brief Read optimization namelist from file
  subroutine nml_optimization_from_file(this, file, nml_found)
    class(nml_optimization_t), intent(inout) :: this
    character(len=*), intent(in) :: file !< path to namelist file
    !> whether namelist was found, if present this will prevent error raises, in case the namelist was not found
    logical, intent(out), optional :: nml_found
    ! namelist variables
    character(len=50) :: name
    integer(i4) :: niterations
    real(dp) :: tolerance
    integer(i4) :: seed
    real(dp) :: dds_r
    logical :: mcmc_opti
    real(dp), dimension(2, 3) :: mcmc_error_params
    ! locals
    type(nml_file_t) :: nml
    logical :: found
    namelist /optimization/ name, niterations, tolerance, seed, dds_r, mcmc_opti, mcmc_error_params

    call this%init()
    name = this%name
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
    this%niterations = niterations
    this%tolerance = tolerance
    this%seed = seed
    this%dds_r = dds_r
    this%mcmc_opti = mcmc_opti
    this%mcmc_error_params = mcmc_error_params

    ! check required parameters
    if (.not. this%is_set('niterations')) error stop "nml_optimization%from_file: 'niterations' is required"
    if (.not. this%is_set('tolerance')) error stop "nml_optimization%from_file: 'tolerance' is required"

    ! mark as configured
    this%is_configured = .true.
  end subroutine nml_optimization_from_file

  !> \brief Set optimization values
  subroutine nml_optimization_set(this, niterations, tolerance, name, seed, dds_r, mcmc_opti, mcmc_error_params)
    class(nml_optimization_t), intent(inout) :: this
    integer(i4), intent(in) :: niterations
    real(dp), intent(in) :: tolerance
    character(len=*), intent(in), optional :: name
    integer(i4), intent(in), optional :: seed
    real(dp), intent(in), optional :: dds_r
    logical, intent(in), optional :: mcmc_opti
    real(dp), dimension(2, 3), intent(in), optional :: mcmc_error_params

    call this%init()

    ! required parameters
    this%niterations = niterations
    this%tolerance = tolerance
    ! override with provided values
    if (present(name)) this%name = name
    if (present(seed)) this%seed = seed
    if (present(dds_r)) this%dds_r = dds_r
    if (present(mcmc_opti)) this%mcmc_opti = mcmc_opti
    if (present(mcmc_error_params)) this%mcmc_error_params = mcmc_error_params

    ! mark as configured
    this%is_configured = .true.
  end subroutine nml_optimization_set

  !> \brief Check whether a namelist value was set
  logical function nml_optimization_is_set(this, name) result(is_set)
    class(nml_optimization_t), intent(in) :: this
    character(len=*), intent(in) :: name

    select case (trim(name))
    case ("name")
      is_set = .not. (trim(this%name) == achar(0))
    case ("niterations")
      is_set = .not. (this%niterations == -huge(this%niterations))
    case ("tolerance")
      is_set = .not. (ieee_is_nan(this%tolerance))
    case ("seed")
      is_set = .true.
    case ("dds_r")
      is_set = .true.
    case ("mcmc_opti")
      is_set = .true.
    case ("mcmc_error_params")
      is_set = .true.
    case default
      error stop "nml_optimization%is_set: unknown field."
    end select
  end function nml_optimization_is_set

end module nml_optimization
