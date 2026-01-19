program main
  use iso_fortran_env, only: error_unit, int32, real64
  use nml_helper, only: buf, max_iter
  use nml_optimization, only: nml_optimization_t

  implicit none

  type(nml_optimization_t) :: cfg
  character(len=256) :: file
  logical :: found
  logical :: ok

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
  if (len_trim(file) == 0) then
    file = "out/optimization.nml"
  end if

  call cfg%from_file(trim(file), nml_found=found)
  if (.not. found) then
    write(error_unit, '(a)') "namelist not found: " // trim(file)
    stop 1
  end if

  ok = cfg%is_valid()
  if (.not. ok) then
    write(error_unit, '(a)') "namelist validation failed"
    stop 2
  end if

  allocate(try_methods(size(cfg%try_methods)))
  allocate(complex_sizes(size(cfg%complex_sizes)))
  allocate(mcmc_error_params( &
    size(cfg%mcmc_error_params, 1), &
    size(cfg%mcmc_error_params, 2), &
    size(cfg%mcmc_error_params, 3)))

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
