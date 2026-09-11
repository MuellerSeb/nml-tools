program conformance
  use nml_helper, only: NML_ERR_INVALID_INDEX, NML_OK
  use nml_namespaces, only: nml_namespaces_t

  implicit none

  type(nml_namespaces_t) :: config
  character(len=256) :: root
  character(len=256) :: errmsg
  integer :: source(0:1)
  integer :: status

  call get_command_argument(1, root)
  if (len_trim(root) == 0) error stop "fixture directory argument is required"

  status = config%set_dims(status=3, set_dims=2, errmsg=errmsg)
  call expect_status(status, NML_OK, "set dimensions")
  if (config%dims%status /= 3) error stop "dimension was not stored below dims"
  if (config%dims%set_dims /= 2) error stop "operation-named dimension mismatch"

  source = [7, 8]
  status = config%set(status=42, present=5, set_dims=6, values=source, errmsg=errmsg)
  call expect_status(status, NML_OK, "set values")
  if (config%data%status /= 42) error stop "status property mismatch"
  if (config%data%present /= 5) error stop "present property mismatch"
  if (config%data%set_dims /= 6) error stop "set_dims property mismatch"
  if (any(config%data%values /= [7, 8, 0])) error stop "partial array assignment mismatch"
  if (lbound(config%data%values, 1) /= 1) error stop "generated storage is not one-based"

  status = config%set_dims(status=0, errmsg=errmsg)
  call expect_status(status, NML_ERR_INVALID_INDEX, "invalid dimensions")
  if (config%dims%status /= 3) error stop "failed dimension update mutated dimensions"
  if (.not. allocated(config%data%values)) error stop "failed dimension update deallocated data"
  if (any(config%data%values /= [7, 8, 0])) error stop "failed dimension update mutated data"

  status = config%from_file(trim(root) // "/input.nml", errmsg=errmsg)
  call expect_status(status, NML_OK, "read flat namelist")
  if (config%data%file /= 19) error stop "file property mismatch"
  if (config%data%nml /= 20) error stop "nml property mismatch"
  if (config%data%iostat /= 21) error stop "iostat property mismatch"
  if (config%data%close_status /= 22) error stop "close_status property mismatch"
  if (config%data%data /= 23 .or. config%data%dims /= 24) then
    error stop "data/dims property mismatch"
  end if
  if (config%data%set /= 25 .or. config%data%init /= 26) then
    error stop "operation-named property mismatch"
  end if
  if (config%data%init_type /= 34) error stop "init_type property mismatch"
  if (config%data%set_dims /= 29) error stop "set_dims input property mismatch"
  if (config%data%from_file /= 30 .or. config%data%is_set /= 31) then
    error stop "reader/query-named property mismatch"
  end if
  if (config%data%is_valid /= 32 .or. config%data%filled_shape /= 33) then
    error stop "validation/shape-named property mismatch"
  end if
  if (config%data%is_configured /= 27) error stop "lifecycle-named property mismatch"
  if (config%data%size /= 28) error stop "intrinsic-named property mismatch"

  status = config%is_valid(errmsg=errmsg)
  call expect_status(status, NML_OK, "validate")

contains

  subroutine expect_status(actual, expected, label)
    integer, intent(in) :: actual
    integer, intent(in) :: expected
    character(len=*), intent(in) :: label

    if (actual /= expected) then
      write(*, '(a,1x,i0,1x,i0)') trim(label), actual, expected
      error stop "unexpected status"
    end if
  end subroutine expect_status

end program conformance
