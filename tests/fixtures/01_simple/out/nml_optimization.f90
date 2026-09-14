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
    idx__check, &
    to__lower, &
    buf, &
    max_iter__dim_default
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
  real(dp), parameter, public :: mcmc_error_params__default(4) = [0.01_dp, 0.6_dp, 0.2_dp, 0.3_dp]

  private :: nml_optimization_read__from_file
  private :: nml__ieee_value, nml__ieee_quiet_nan, nml__ieee_is_nan

  !> \class nml_optimization_data_t
  !> \brief Schema-backed values for optimization
  type, public :: nml_optimization_data_t
    character(len=buf) :: name !< Optimization name
    integer :: niterations !< Number of iterations
    real :: tolerance !< Convergence tolerance
    integer(i4) :: seed !< Random seed
    real(dp) :: dds_r !< DDS perturbation rate
    logical :: mcmc_opti !< MCMC optimization
    real(dp), allocatable, dimension(:, :, :) :: mcmc_error_params !< MCMC error parameters per domain
  end type nml_optimization_data_t

  !> \class nml_optimization_dims_t
  !> \brief Runtime dimensions for optimization
  type, public :: nml_optimization_dims_t
    integer :: max_iter = max_iter__dim_default !< runtime dimension for max_iter
  end type nml_optimization_dims_t

  !> \class nml_optimization_t
  !> \brief MHM optimization namelist
  !> \details All relevant configurations for the optimization parameters of MHM.
  !! This namelist corresponds to the `optimization` section in the MHM configuration.
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
    procedure :: is_valid => nml_optimization_is_valid
  end type nml_optimization_t

contains

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
    nml__obj%data%niterations = -huge(nml__obj%data%niterations) ! sentinel for required integer
    nml__obj%data%tolerance = nml__ieee_value(nml__obj%data%tolerance, nml__ieee_quiet_nan) ! sentinel for required real
    ! default values
    nml__obj%data%seed = seed__default
    nml__obj%data%dds_r = dds_r__default
    nml__obj%data%mcmc_opti = mcmc_opti__default ! bool values always need a default
    nml__obj%data%mcmc_error_params = reshape( &
      mcmc_error_params__default, &
      shape=[3, 2, nml__obj%dims%max_iter], &
      order=[3, 2, 1], &
      pad=mcmc_error_params__default)
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
    if ((3 * 2 * candidate__max_iter) < 4) then
      nml__status = NML_ERR_INVALID_INDEX
      if (present(errmsg)) errmsg = "shape constants for 'mcmc_error_params' must allow at least 4 default values"
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
    integer :: niterations
    real :: tolerance
    integer(i4) :: seed
    real(dp) :: dds_r
    logical :: mcmc_opti
    real(dp), allocatable, dimension(:, :, :) :: mcmc_error_params
    ! locals
    type(nml_file_t) :: nml__reader
    integer :: nml__iostat
    integer :: nml__close_status
    character(len=nml_line_buffer) :: nml__iomsg

    namelist /optimization/ &
      name, &
      niterations, &
      tolerance, &
      seed, &
      dds_r, &
      mcmc_opti, &
      mcmc_error_params

    nml__status = nml__obj%init(errmsg=errmsg)
    if (nml__status /= NML_OK) return
    ! allocate local namelist variables matching runtime-sized fields
    if (allocated(mcmc_error_params)) deallocate(mcmc_error_params)
    allocate(mcmc_error_params(3, 2, nml__obj%dims%max_iter))
    name = nml__obj%data%name
    niterations = nml__obj%data%niterations
    tolerance = nml__obj%data%tolerance
    seed = nml__obj%data%seed
    dds_r = nml__obj%data%dds_r
    mcmc_opti = nml__obj%data%mcmc_opti
    mcmc_error_params = nml__obj%data%mcmc_error_params

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
    nml__obj%data%niterations = niterations
    nml__obj%data%tolerance = tolerance
    nml__obj%data%seed = seed
    nml__obj%data%dds_r = dds_r
    nml__obj%data%mcmc_opti = mcmc_opti
    nml__obj%data%mcmc_error_params = mcmc_error_params

    ! mark as configured
    nml__obj%is_configured = .true.
    nml__status = NML_OK
  end function nml_optimization_read__from_file

  !> \brief Set optimization values
  integer function nml_optimization_set(nml__obj, &
    niterations, &
    tolerance, &
    name, &
    seed, &
    dds_r, &
    mcmc_opti, &
    mcmc_error_params, &
    errmsg) result(nml__status)

    class(nml_optimization_t), intent(inout) :: nml__obj !< namelist instance
    character(len=*), intent(out), optional :: errmsg !< error message for non-OK status values
    integer, intent(in) :: niterations !< Number of iterations
    real, intent(in) :: tolerance !< Convergence tolerance
    character(len=*), intent(in), optional :: name !< Optimization name
    integer(i4), intent(in), optional :: seed !< Random seed
    real(dp), intent(in), optional :: dds_r !< DDS perturbation rate
    logical, intent(in), optional :: mcmc_opti !< MCMC optimization
    real(dp), dimension(:, :, :), intent(in), optional :: mcmc_error_params !< MCMC error parameters per domain
    nml__status = nml__obj%init(errmsg=errmsg)
    if (nml__status /= NML_OK) return

    ! required parameters
    nml__obj%data%niterations = niterations
    nml__obj%data%tolerance = tolerance
    ! override with provided values
    if (present(name)) nml__obj%data%name = name
    if (present(seed)) nml__obj%data%seed = seed
    if (present(dds_r)) nml__obj%data%dds_r = dds_r
    if (present(mcmc_opti)) nml__obj%data%mcmc_opti = mcmc_opti
    if (present(mcmc_error_params)) then
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

  !> \brief Validate required values and constraints
  integer function nml_optimization_is_valid(nml__obj, errmsg) result(nml__status)
    class(nml_optimization_t), intent(in) :: nml__obj !< namelist instance
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
  end function nml_optimization_is_valid

end module nml_optimization
