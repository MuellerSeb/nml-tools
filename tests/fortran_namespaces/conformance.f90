program conformance
  use iso_c_binding, only: c_intptr_t, c_loc
  use iso_fortran_env, only: int16, int64
  use nml_helper, only: NML_ERR_BOUNDS, NML_ERR_ENUM, NML_ERR_INVALID_INDEX, NML_OK
  use nml_namespaces, only: nml_namespaces_t
  use nml_constraints, only: nml_constraints_t
  use nml_wrapper_status, only: nml_wrapper_status_t
  use f2py_wrapper_status, only: wrapper_status_set_wrapper, wrapper_status_is_valid_wrapper
  use nml_c_bindings, only: nml_c_bindings_t
  use f2py_c_bindings, only: c_bindings_from_file_wrapper, c_bindings_set_dims_wrapper

  implicit none

  type(nml_namespaces_t) :: config
  type(nml_constraints_t) :: constraints
  type(nml_wrapper_status_t), target :: wrapped
  type(nml_c_bindings_t), target :: c_config
  integer(c_intptr_t) :: handle
  character(len=256) :: root
  character(len=1024) :: errmsg
  integer :: source(0:1)
  integer :: status

  call get_command_argument(1, root)
  if (len_trim(root) == 0) error stop "fixture directory argument is required"

  status = config%set_dims(status=3, set_dims=2, errmsg=errmsg)
  call expect_status(status, NML_OK, "set dimensions")
  if (config%dims%status /= 3) error stop "dimension was not stored below dims"
  if (config%dims%set_dims /= 2) error stop "operation-named dimension mismatch"

  source = [7, 8]
  status = config%set(status=42, set_dims=6, values=source, errmsg=errmsg)
  call expect_status(status, NML_OK, "set values")
  if (config%data%status /= 42) error stop "status property mismatch"
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
  status = config%is_valid(errmsg=errmsg)
  call expect_status(status, NML_OK, "validate")

  handle = transfer(c_loc(wrapped), handle)
  call wrapper_status_set_wrapper(handle, has__state=.true., state__code=42, &
    has__state__code=.true., has__pointer_state=.false., pointer_state__code=0, &
    has__pointer_state__code=.false., nml__status=status, nml__errmsg=errmsg)
  call expect_status(status, NML_OK, "call wrapper with imported type(status)")
  if (wrapped%data%state%code /= 42) error stop "wrapper did not set derived leaf"
  call wrapper_status_is_valid_wrapper(handle, status, errmsg)
  call expect_status(status, NML_OK, "validate wrapped derived value")
  if (wrapped%data%pointer_state%code /= 0) error stop "application c_ptr default mismatch"

  status = c_config%set(c_intptr_t=1, c_ptr=2, c_null_ptr=3, c_f_pointer=4, &
    values=[5, 6], errmsg=errmsg)
  call expect_status(status, NML_OK, "native C-binding-named fields")
  if (c_config%data%c_intptr_t /= 1 .or. c_config%data%c_ptr /= 2) then
    error stop "native C-binding fields mismatch"
  end if
  handle = transfer(c_loc(c_config), handle)
  call c_bindings_set_dims_wrapper(handle, 3, .true., status, errmsg)
  call expect_status(status, NML_OK, "C-binding-named wrapper dimension")
  call c_bindings_from_file_wrapper(handle, trim(root) // "/c_bindings.nml", status, errmsg)
  call expect_status(status, NML_OK, "read C-binding-named fields through wrapper")
  if (c_config%dims%c_intptr_t /= 3 .or. c_config%data%c_intptr_t /= 17) then
    error stop "C-binding property/dimension overlap mismatch"
  end if
  if (c_config%data%c_ptr /= 18 .or. c_config%data%c_null_ptr /= 19 &
    .or. c_config%data%c_f_pointer /= 20) error stop "C-binding namelist fields mismatch"
  if (any(c_config%data%values /= [7, 8, 9])) error stop "C-binding dimension allocation mismatch"
  status = c_config%is_valid(errmsg=errmsg)
  call expect_status(status, NML_OK, "validate C-binding-named configuration")

  status = constraints%set(choice=2, limit=0_int16, upper=4_int64, errmsg=errmsg)
  call expect_status(status, NML_OK, "constraint setter")
  status = constraints%is_valid(errmsg=errmsg)
  call expect_status(status, NML_OK, "validate kind aliases matching old constraint locals")
  constraints%data%choice = 3
  status = constraints%is_valid(errmsg=errmsg)
  call expect_status(status, NML_ERR_ENUM, "enum error")
  if (index(errmsg, "choice") == 0) error stop "enum error message lost field name"
  constraints%data%choice = 1
  constraints%data%limit = -1
  status = constraints%is_valid(errmsg=errmsg)
  call expect_status(status, NML_ERR_BOUNDS, "bounds error")
  if (index(errmsg, "limit") == 0) error stop "bounds error message lost field name"

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
