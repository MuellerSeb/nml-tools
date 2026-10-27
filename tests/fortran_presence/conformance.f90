program conformance
  use nml_helper, only: NML_OK, NML_ERR_NOT_SET, NML_ERR_INVALID_NAME, &
    NML_ERR_INVALID_INDEX, NML_ERR_PARTLY_SET, NML_ERR_REQUIRED
  use nml_presence, only: nml_presence_t
  use nml_records, only: nml_records_t
  use nml_required, only: nml_required_t
  use nml_long_nnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnn, only: &
    long_config_t => nml_long_nnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnn_t
  implicit none

  type(long_config_t) :: long_config
  type(nml_presence_t) :: cfg
  type(nml_records_t) :: records
  type(nml_required_t) :: required
  logical, allocatable :: mask1(:), mask2(:,:), mask3(:,:,:)
  integer :: status, filled1(1), filled2(2), filled3(3), i, j, k
  character(len=256) :: root, errmsg

  call get_command_argument(1, root)
  if (len_trim(root) == 0) error stop "fixture directory argument required"

  status = cfg%set_mask("counts", mask1, errmsg)
  call expect(status, NML_ERR_NOT_SET, "unconfigured mask")
  if (allocated(mask1)) error stop "error allocated mask"
  filled1 = -1
  status = cfg%filled_shape("counts", filled1, errmsg)
  call expect(status, NML_ERR_NOT_SET, "unconfigured filled shape")
  if (any(filled1 /= 0)) error stop "error did not clear filled"
  status = cfg%init(errmsg)
  call expect(status, NML_OK, "initialize")
  status = cfg%set_mask("runtime", mask2, errmsg)
  call expect(status, NML_ERR_NOT_SET, "init does not configure")

  status = cfg%set(errmsg=errmsg)
  call expect(status, NML_OK, "configure empty")
  call check1("counts")
  if (any(mask1)) error stop "empty mask"
  status = cfg%filled_shape("counts", filled1, errmsg)
  call expect(status, NML_OK, "empty filled shape")
  if (any(filled1 /= 0)) error stop "empty extents"
  call check2("matrix")
  call check3("cube")
  call check1("labels")
  call check1("defaulted")
  if (.not. all(mask1)) error stop "default presence"
  call check1("flags")
  if (.not. all(mask1)) error stop "logical presence"
  status = cfg%filled_shape("flags", filled1, errmsg)
  call expect(status, NML_OK, "logical filled shape")
  if (any(filled1 /= 3)) error stop "logical full extent"

  status = cfg%set(matrix=reshape([1., 2., 3., 4., 5., 6.], [3,2]), &
    counts=[1,2], defaulted=[-huge(0)], errmsg=errmsg)
  call expect(status, NML_OK, "partial set")
  call check1("defaulted")
  if (.not. all(mask1)) error stop "defaulted sentinel must remain present"
  call check2("matrix")
  if (.not. all(mask2(:,1:2)) .or. any(mask2(:,3:4))) error stop "matrix prefix mask"
  status = cfg%filled_shape("matrix", filled2, errmsg)
  call expect(status, NML_OK, "matrix prefix")
  if (any(filled2 /= [3,2])) error stop "matrix prefix extents"
  status = cfg%is_valid(errmsg)
  call expect(status, NML_OK, "optional prefix valid")

  status = cfg%set(matrix=reshape([1.,2.,3.,4.,5.,6.,7.,8.,9.,10.,11.,12.], [3,4]), errmsg=errmsg)
  call expect(status, NML_OK, "full matrix set")
  call check2("matrix")
  if (.not. all(mask2)) error stop "full matrix mask"
  status = cfg%filled_shape("matrix", filled2, errmsg)
  call expect(status, NML_OK, "full matrix")
  if (any(filled2 /= [3,4])) error stop "full matrix extents"

  status = cfg%from_file(trim(root) // "/sparse.nml", errmsg)
  call expect(status, NML_OK, "read sparse input")
  status = cfg%is_valid(errmsg)
  call expect(status, NML_OK, "optional holes valid")
  call check1("CoUnTs")
  if (any(mask1 .neqv. [.false.,.true.,.false.,.true.])) error stop "sparse count mask"
  status = cfg%filled_shape("counts", filled1, errmsg)
  call expect(status, NML_ERR_PARTLY_SET, "count holes")
  if (any(filled1 /= 4)) error stop "hole extents retained"
  call check2("matrix")
  status = cfg%filled_shape("matrix", filled2, errmsg)
  call expect(status, NML_ERR_PARTLY_SET, "matrix holes")
  if (any(filled2 /= [3,2])) error stop "matrix hole extents"
  call check3("cube")
  status = cfg%filled_shape("cube", filled3, errmsg)
  call expect(status, NML_OK, "prefix in every dimension")
  if (any(filled3 /= [2,1,2])) error stop "cube prefix extents"
  call check1("labels")
  if (any(mask1 .neqv. [.false.,.true.,.false.])) error stop "character mask"
  call check2("runtime")
  status = cfg%filled_shape("runtime", filled2, errmsg)
  call expect(status, NML_OK, "runtime prefix")
  if (any(filled2 /= [3,1])) error stop "runtime extents"

  status = cfg%set_mask("matrix", mask1, errmsg)
  call expect(status, NML_ERR_INVALID_INDEX, "mask rank mismatch")
  if (index(errmsg, "rank mismatch") == 0 .or. allocated(mask1)) error stop "rank error output"
  status = cfg%set_mask("scalar", mask1, errmsg)
  call expect(status, NML_ERR_INVALID_INDEX, "scalar mask")
  if (index(errmsg, "scalar") == 0) error stop "scalar diagnostic"
  status = cfg%set_mask("missing", mask1, errmsg)
  call expect(status, NML_ERR_INVALID_NAME, "unknown mask")
  status = cfg%filled_shape("matrix", filled1, errmsg)
  call expect(status, NML_ERR_INVALID_INDEX, "filled rank mismatch")
  if (any(filled1 /= 0)) error stop "rank mismatch extents"
  status = cfg%filled_shape("scalar", filled1, errmsg)
  call expect(status, NML_ERR_INVALID_INDEX, "scalar filled shape")
  status = cfg%filled_shape("missing", filled1, errmsg)
  call expect(status, NML_ERR_INVALID_NAME, "unknown filled shape")

  ! Force unavailable storage in a configured object to exercise the allocation guard.
  deallocate(cfg%runtime)
  status = cfg%set_mask("runtime", mask2, errmsg)
  call expect(status, NML_ERR_NOT_SET, "unavailable mask storage")
  if (allocated(mask2) .or. index(errmsg, "storage unavailable") == 0) error stop "storage diagnostic"
  status = cfg%filled_shape("runtime", filled2, errmsg)
  call expect(status, NML_ERR_NOT_SET, "unavailable filled storage")
  if (any(filled2 /= 0)) error stop "unavailable storage extents"
  status = cfg%set_dims(n=5, errmsg=errmsg)
  call expect(status, NML_OK, "change dimensions")
  status = cfg%set_mask("runtime", mask2, errmsg)
  call expect(status, NML_ERR_NOT_SET, "dimension update resets configuration")
  status = cfg%set(runtime=reshape([1.,2.,3.,4.], [2,2]), errmsg=errmsg)
  call expect(status, NML_OK, "set after dimension update")
  call check2("runtime")
  if (any(shape(mask2) /= [5,2])) error stop "new runtime mask shape"
  status = cfg%filled_shape("runtime", filled2, errmsg)
  call expect(status, NML_OK, "resized runtime prefix")
  if (any(filled2 /= [2,2])) error stop "resized prefix extents"

  status = required%set(values=[1,2], errmsg=errmsg)
  call expect(status, NML_OK, "partly set required array")
  status = required%is_valid(errmsg)
  call expect(status, NML_ERR_PARTLY_SET, "required array completeness retained")
  status = required%set_mask("values", mask1, errmsg)
  call expect(status, NML_OK, "required mask")
  if (any(mask1 .neqv. [.true.,.true.,.false.])) error stop "required mask values"
  status = required%filled_shape("values", filled1, errmsg)
  call expect(status, NML_OK, "required prefix query")
  if (any(filled1 /= 2)) error stop "required prefix extents"
  status = required%set(values=[-huge(0)], errmsg=errmsg)
  call expect(status, NML_OK, "empty required array")
  status = required%is_valid(errmsg)
  call expect(status, NML_ERR_REQUIRED, "required missing retained")

  status = records%from_file(trim(root) // "/sparse.nml", errmsg)
  call expect(status, NML_OK, "derived sparse read")
  status = records%set_mask("entries", mask2, errmsg)
  call expect(status, NML_ERR_PARTLY_SET, "incomplete derived element")
  if (allocated(mask2)) error stop "partial derived mask must be unallocated"
  status = records%filled_shape("entries", filled2, errmsg)
  call expect(status, NML_ERR_PARTLY_SET, "incomplete derived filled shape")
  if (any(filled2 /= 0)) error stop "incomplete derived extents must be zero"
  call check_records("EnTrIeS%LeFt")
  if (.not. all(mask2(:,1)) .or. any(mask2(:,2))) error stop "derived component mask"
  status = records%filled_shape("entries%left", filled2, errmsg)
  call expect(status, NML_OK, "derived component prefix")
  if (any(filled2 /= [2,1])) error stop "derived component extents"
  call check_records("entries%right")
  call check_records("entries%note")
  if (any(mask2)) error stop "absent derived character components"
  call check_records("entries%flag")
  if (.not. all(mask2)) error stop "derived default logical presence"

  records%entries(2,1)%right = 4
  call check_records("entries")
  if (.not. all(mask2(:,1)) .or. any(mask2(:,2))) error stop "derived root mask"
  status = records%filled_shape("entries", filled2, errmsg)
  call expect(status, NML_OK, "derived root prefix")
  if (any(filled2 /= [2,1])) error stop "derived root extents"
  records%entries(1,2)%left = 5
  records%entries(1,2)%right = 6
  status = records%filled_shape("entries", filled2, errmsg)
  call expect(status, NML_ERR_PARTLY_SET, "derived prefix hole")
  if (any(filled2 /= [2,2])) error stop "derived hole extents retained"
  status = records%set_mask("known", mask1, errmsg)
  call expect(status, NML_OK, "defaulted derived root")
  if (.not. all(mask1)) error stop "defaulted root mask"
  status = records%filled_shape("known", filled1, errmsg)
  call expect(status, NML_OK, "defaulted derived filled shape")
  if (any(filled1 /= 2)) error stop "defaulted derived extents"
  status = records%set_mask("context%value", mask1, errmsg)
  call expect(status, NML_ERR_INVALID_INDEX, "scalar derived component")

  status = long_config%set(values=[1,2], errmsg=errmsg)
  call expect(status, NML_OK, "long name set")
  status = long_config%set_mask("values", mask1, errmsg)
  call expect(status, NML_OK, "long name rank one mask")
  if (count(mask1) /= 2) error stop "long name mask values"
  status = long_config%filled_shape("values", filled1, errmsg)
  call expect(status, NML_OK, "long name prefix")
  if (any(filled1 /= 2)) error stop "long name prefix extents"
  status = long_config%set_mask("flags", mask2, errmsg)
  call expect(status, NML_OK, "long name rank two mask")
  if (.not. all(mask2)) error stop "long name logical mask"
  status = long_config%filled_shape("flags", filled2, errmsg)
  call expect(status, NML_OK, "long name full extents")
  if (any(filled2 /= [2,3])) error stop "long name shape"

contains

  subroutine expect(actual, expected, label)
    integer, intent(in) :: actual, expected
    character(len=*), intent(in) :: label
    if (actual /= expected) then
      write(*, '(a,2(1x,i0),1x,a)') label, actual, expected, trim(errmsg)
      error stop "unexpected status"
    end if
  end subroutine expect

  subroutine check1(name)
    character(len=*), intent(in) :: name
    status = cfg%set_mask(name, mask1, errmsg)
    call expect(status, NML_OK, "rank one mask: " // name)
    if (len_trim(errmsg) /= 0) error stop "success did not clear diagnostic"
    do i = 1, size(mask1)
      status = cfg%is_set(name, [i], errmsg)
      if (mask1(i) .neqv. (status == NML_OK)) error stop "rank one mask disagreement"
    end do
  end subroutine check1

  subroutine check2(name)
    character(len=*), intent(in) :: name
    status = cfg%set_mask(name, mask2, errmsg)
    call expect(status, NML_OK, "rank two mask: " // name)
    do j = 1, size(mask2,2)
      do i = 1, size(mask2,1)
        status = cfg%is_set(name, [i,j], errmsg)
        if (mask2(i,j) .neqv. (status == NML_OK)) error stop "rank two mask disagreement"
      end do
    end do
  end subroutine check2

  subroutine check3(name)
    character(len=*), intent(in) :: name
    status = cfg%set_mask(name, mask3, errmsg)
    call expect(status, NML_OK, "rank three mask: " // name)
    do k = 1, size(mask3,3)
      do j = 1, size(mask3,2)
        do i = 1, size(mask3,1)
          status = cfg%is_set(name, [i,j,k], errmsg)
          if (mask3(i,j,k) .neqv. (status == NML_OK)) error stop "rank three mask disagreement"
        end do
      end do
    end do
  end subroutine check3

  subroutine check_records(name)
    character(len=*), intent(in) :: name
    status = records%set_mask(name, mask2, errmsg)
    call expect(status, NML_OK, "derived mask: " // name)
    do j = 1, size(mask2,2)
      do i = 1, size(mask2,1)
        status = records%is_set(name, [i,j], errmsg)
        if (mask2(i,j) .neqv. (status == NML_OK)) error stop "derived mask disagreement"
      end do
    end do
  end subroutine check_records
end program conformance
