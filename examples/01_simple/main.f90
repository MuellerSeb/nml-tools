program main
  use iso_fortran_env, only: error_unit, int32, real64
  use nml_helper, only: buf, max_iter, NML_OK
  use nml_optimization, only: nml_optimization_t

  implicit none

  type(nml_optimization_t) :: cfg
  character(len=256) :: file
  integer :: status
  character(len=256) :: errmsg

  ! shorten string lengths for easier handling
  character(len=20) :: name
  character(len=20) :: method
  character(len=20), allocatable :: try_methods(:)
  integer(int32), allocatable :: complex_sizes(:)
  integer :: niterations
  real :: tolerance
  integer(int32) :: seed
  real(real64) :: dds_r
  logical :: mcmc_opti
  real(real64), allocatable :: mcmc_error_params(:,:,:)

  namelist /optimization/ name, method, try_methods, complex_sizes, niterations, tolerance, &
    seed, dds_r, mcmc_opti, mcmc_error_params

  call get_command_argument(1, file)
  if (len_trim(file) == 0) file = "out/optimization.nml"

  status = cfg%from_file(trim(file), errmsg=errmsg)
  if (status /= NML_OK) then
    write(error_unit, '(a)') "failed to read namelist: " // trim(errmsg)
    stop status
  end if

  status = cfg%is_valid(errmsg=errmsg)
  if (status /= NML_OK) then
    write(error_unit, '(a)') "namelist validation failed: " // trim(errmsg)
    stop status
  end if

  allocate(try_methods(size(cfg%try_methods)))
  allocate(complex_sizes(size(cfg%complex_sizes)))
  allocate(mcmc_error_params( &
    size(cfg%mcmc_error_params, 1), &
    size(cfg%mcmc_error_params, 2), &
    size(cfg%mcmc_error_params, 3)))

  status = cfg%is_set("mcmc_error_params", idx=[1,2,3], errmsg=errmsg)
  if (status /= NML_OK) then
    write(error_unit, '(a)') "field check failed: " // trim(errmsg)
    stop status
  end if

  name = cfg%name
  method = cfg%method
  try_methods = cfg%try_methods
  complex_sizes = cfg%complex_sizes
  niterations = cfg%niterations
  tolerance = cfg%tolerance
  seed = cfg%seed
  dds_r = cfg%dds_r
  mcmc_opti = cfg%mcmc_opti
  mcmc_error_params = cfg%mcmc_error_params

  write(*, nml=optimization)
end program main
