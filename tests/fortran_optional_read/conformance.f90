program conformance
  use nml_helper, only: NML_ERR_FILE_NOT_FOUND, NML_ERR_NML_NOT_FOUND, NML_ERR_NOT_SET, &
    NML_ERR_READ, NML_OK
  use nml_optional, only: nml_optional_t
  use nml_required, only: nml_required_t

  implicit none

  type(nml_optional_t) :: optional
  type(nml_required_t) :: required
  character(len=256) :: root
  character(len=256) :: errmsg
  integer :: status

  call get_command_argument(1, root)
  if (len_trim(root) == 0) error stop "fixture directory argument is required"

  status = optional%from_file(join_path(root, "other.nml"), errmsg)
  call expect_status(status, NML_OK, "optional missing group")
  if (.not. optional%is_configured) error stop "optional missing group was not configured"
  if (optional%data%count /= 7) error stop "optional default was not retained"
  if (len_trim(errmsg) /= 0) error stop "optional missing group did not clear errmsg"

  status = optional%is_valid(errmsg=errmsg)
  call expect_status(status, NML_OK, "optional missing group validation")
  status = optional%is_set("label", errmsg=errmsg)
  call expect_status(status, NML_ERR_NOT_SET, "optional sentinel")

  status = required%from_file(join_path(root, "other.nml"), errmsg)
  call expect_status(status, NML_ERR_NML_NOT_FOUND, "required missing group")

  status = optional%from_file(join_path(root, "does-not-exist.nml"), errmsg)
  call expect_status(status, NML_ERR_FILE_NOT_FOUND, "missing file")

  status = optional%from_file(join_path(root, "malformed.nml"), errmsg)
  call expect_status(status, NML_ERR_READ, "malformed group")

contains

  function join_path(directory, name) result(path)
    character(len=*), intent(in) :: directory
    character(len=*), intent(in) :: name
    character(len=:), allocatable :: path

    path = trim(directory) // "/" // trim(name)
  end function join_path

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
