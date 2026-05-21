!> \file nml_optimization.f90
!> \copydoc nml_optimization

!> \brief MHM optimization namelist
!> \details All relevant configurations for the optimization parameters of MHM.
!! This namelist corresponds to the `optimization` section in the MHM configuration.
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
    max_iter_default=>max_iter
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
  real(dp), parameter, public :: mcmc_error_params_default(4) = [0.01_dp, 0.6_dp, 0.2_dp, 0.3_dp]

  !> \class nml_optimization_t
  !> \brief MHM optimization namelist
  !> \details All relevant configurations for the optimization parameters of MHM.
  !! This namelist corresponds to the `optimization` section in the MHM configuration.
  type, public :: nml_optimization_t
    logical :: is_configured = .false. !< whether the namelist has been configured
    integer :: dim_max_iter = max_iter_default !< runtime dimension for max_iter
    character(len=buf) :: name !< Optimization name
    integer :: niterations !< Number of iterations
    real :: tolerance !< Convergence tolerance
    integer(i4) :: seed !< Random seed
    real(dp) :: dds_r !< DDS perturbation rate
    logical :: mcmc_opti !< MCMC optimization
    real(dp), allocatable, dimension(:, :, :) :: mcmc_error_params !< MCMC error parameters per domain
  contains
    procedure :: init => nml_optimization_init
    procedure :: set_dims => nml_optimization_set_dims
    procedure :: from_file => nml_optimization_from_file
    procedure :: set => nml_optimization_set
    procedure :: is_set => nml_optimization_is_set
    procedure :: is_valid => nml_optimization_is_valid
  end type nml_optimization_t

contains

  !> \brief Initialize defaults and sentinels for optimization
  integer function nml_optimization_init(this, errmsg) result(status)
    class(nml_optimization_t), intent(inout) :: this !< namelist instance
    character(len=*), intent(out), optional :: errmsg !< error message for non-OK status values

    status = NML_OK
    if (present(errmsg)) errmsg = ""
    this%is_configured = .false.

    ! allocate runtime-sized fields
    if (allocated(this%mcmc_error_params)) deallocate(this%mcmc_error_params)
    allocate(this%mcmc_error_params(3, 2, this%dim_max_iter))

    ! sentinel values for required/optional parameters
    this%name = achar(0) ! sentinel for optional string
    this%niterations = -huge(this%niterations) ! sentinel for required integer
    this%tolerance = ieee_value(this%tolerance, ieee_quiet_nan) ! sentinel for required real
    ! default values
    this%seed = seed_default
    this%dds_r = dds_r_default
    this%mcmc_opti = mcmc_opti_default ! bool values always need a default
    this%mcmc_error_params = reshape( &
      mcmc_error_params_default, &
      shape=[3, 2, this%dim_max_iter], &
      order=[3, 2, 1], &
      pad=mcmc_error_params_default)
  end function nml_optimization_init

  !> \brief Reset runtime dimensions for optimization
  integer function nml_optimization_set_dims(this, &
    max_iter, &
    errmsg) result(status)
    class(nml_optimization_t), intent(inout) :: this !< namelist instance
    integer, intent(in), optional :: max_iter !< runtime dimension override for max_iter
    integer :: candidate_max_iter
    character(len=*), intent(out), optional :: errmsg !< error message for non-OK status values

    status = NML_OK
    if (present(errmsg)) errmsg = ""
    if (present(max_iter)) then
      candidate_max_iter = max_iter
    else
      candidate_max_iter = max_iter_default
    end if
    if (candidate_max_iter <= 0) then
      status = NML_ERR_INVALID_INDEX
      if (present(errmsg)) errmsg = "dimension 'max_iter' must be positive"
      return
    end if
    if ((3 * 2 * candidate_max_iter) < 4) then
      status = NML_ERR_INVALID_INDEX
      if (present(errmsg)) errmsg = "shape constants for 'mcmc_error_params' must allow at least 4 default values"
      return
    end if
    this%dim_max_iter = candidate_max_iter

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
    integer :: niterations
    real :: tolerance
    integer(i4) :: seed
    real(dp) :: dds_r
    logical :: mcmc_opti
    real(dp), allocatable, dimension(:, :, :) :: mcmc_error_params
    ! locals
    type(nml_file_t) :: nml
    integer :: iostat
    integer :: close_status
    character(len=nml_line_buffer) :: iomsg

    namelist /optimization/ &
      name, &
      niterations, &
      tolerance, &
      seed, &
      dds_r, &
      mcmc_opti, &
      mcmc_error_params

    status = this%init(errmsg=errmsg)
    if (status /= NML_OK) return
    ! allocate local namelist variables matching runtime-sized fields
    if (allocated(mcmc_error_params)) deallocate(mcmc_error_params)
    allocate(mcmc_error_params(3, 2, this%dim_max_iter))
    name = this%name
    niterations = this%niterations
    tolerance = this%tolerance
    seed = this%seed
    dds_r = this%dds_r
    mcmc_opti = this%mcmc_opti
    mcmc_error_params = this%mcmc_error_params

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
    this%niterations = niterations
    this%tolerance = tolerance
    this%seed = seed
    this%dds_r = dds_r
    this%mcmc_opti = mcmc_opti
    this%mcmc_error_params = mcmc_error_params

    ! mark as configured
    this%is_configured = .true.
    status = NML_OK
  end function nml_optimization_from_file

  !> \brief Set optimization values
  integer function nml_optimization_set(this, &
    niterations, &
    tolerance, &
    name, &
    seed, &
    dds_r, &
    mcmc_opti, &
    mcmc_error_params, &
    errmsg) result(status)

    class(nml_optimization_t), intent(inout) :: this !< namelist instance
    character(len=*), intent(out), optional :: errmsg !< error message for non-OK status values
    integer, intent(in) :: niterations !< Number of iterations
    real, intent(in) :: tolerance !< Convergence tolerance
    character(len=*), intent(in), optional :: name !< Optimization name
    integer(i4), intent(in), optional :: seed !< Random seed
    real(dp), intent(in), optional :: dds_r !< DDS perturbation rate
    logical, intent(in), optional :: mcmc_opti !< MCMC optimization
    real(dp), dimension(:, :, :), intent(in), optional :: mcmc_error_params !< MCMC error parameters per domain
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
    this%niterations = niterations
    this%tolerance = tolerance
    ! override with provided values
    if (present(name)) this%name = name
    if (present(seed)) this%seed = seed
    if (present(dds_r)) this%dds_r = dds_r
    if (present(mcmc_opti)) this%mcmc_opti = mcmc_opti
    if (present(mcmc_error_params)) then
      if (size(mcmc_error_params, 1) > size(this%mcmc_error_params, 1)) then
        status = NML_ERR_INVALID_INDEX
        if (present(errmsg)) errmsg = "dimension 1 exceeds bounds for 'mcmc_error_params'"
        return
      end if
      lb_1 = lbound(this%mcmc_error_params, 1)
      ub_1 = lb_1 + size(mcmc_error_params, 1) - 1
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
      this%mcmc_error_params(lb_1:ub_1, lb_2:ub_2, lb_3:ub_3) = mcmc_error_params
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
        return
      end if
      if (present(idx)) then
        status = idx_check(idx, lbound(this%mcmc_error_params), ubound(this%mcmc_error_params), &
          "mcmc_error_params", errmsg)
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
  end function nml_optimization_is_valid

end module nml_optimization
