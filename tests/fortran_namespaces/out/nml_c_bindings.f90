!> \file nml_c_bindings.f90
!> \copydoc nml_c_bindings

!> \brief Resolver dependency isolation
!> \details Resolver dependency isolation
module nml_c_bindings
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
    NML_ERR_INVALID_HANDLE, &
    c_intptr_t__dim_default

  implicit none

  ! default values
  integer, parameter, public :: c_intptr_t__default = 0
  integer, parameter, public :: c_ptr__default = 0
  integer, parameter, public :: c_null_ptr__default = 0
  integer, parameter, public :: c_f_pointer__default = 0
  integer, parameter, public :: values__default = 0

  private :: nml_c_bindings_read__from_file

  !> \class nml_c_bindings_data_t
  !> \brief Schema-backed values for c_bindings
  type, public :: nml_c_bindings_data_t
    integer :: c_intptr_t !< c_intptr_t
    integer :: c_ptr !< c_ptr
    integer :: c_null_ptr !< c_null_ptr
    integer :: c_f_pointer !< c_f_pointer
    integer, allocatable, dimension(:) :: values !< values
  end type nml_c_bindings_data_t

  !> \class nml_c_bindings_dims_t
  !> \brief Runtime dimensions for c_bindings
  type, public :: nml_c_bindings_dims_t
    integer :: c_intptr_t = c_intptr_t__dim_default !< runtime dimension for c_intptr_t
  end type nml_c_bindings_dims_t

  !> \class nml_c_bindings_t
  !> \brief Resolver dependency isolation
  !> \details Resolver dependency isolation
  type, public :: nml_c_bindings_t
    type(nml_c_bindings_data_t) :: data !< schema-backed namelist values
    type(nml_c_bindings_dims_t) :: dims !< runtime array dimensions
    logical :: is_configured = .false. !< whether the namelist has been configured
  contains
    procedure :: init => nml_c_bindings_init
    procedure :: set_dims => nml_c_bindings_set_dims
    procedure :: from_file => nml_c_bindings_from_file
    procedure :: set => nml_c_bindings_set
    procedure :: is_set => nml_c_bindings_is_set
    procedure :: is_valid => nml_c_bindings_is_valid
  end type nml_c_bindings_t

contains

  !> \brief Resolve an opaque C pointer handle to a nml_c_bindings_t pointer
  subroutine nml_c_bindings_resolve_handle(nml__handle, nml__obj, nml__status, errmsg)
    use iso_c_binding, only: c_f_pointer, c_intptr_t, c_null_ptr, c_ptr
    integer(c_intptr_t), intent(in) :: nml__handle !< opaque handle to a nml_c_bindings_t instance
    type(nml_c_bindings_t), pointer :: nml__obj !< resolved namelist pointer
    integer, intent(out) :: nml__status !< nml-tools status code
    character(len=*), intent(out), optional :: errmsg !< error message for non-OK status values
    type(c_ptr) :: nml__ptr

    if (present(errmsg)) errmsg = ""
    nullify(nml__obj)
    if (nml__handle == 0_c_intptr_t) then
      nml__status = NML_ERR_INVALID_HANDLE
      if (present(errmsg)) errmsg = "zero handle"
      return
    end if
    nml__ptr = transfer(nml__handle, c_null_ptr)
    call c_f_pointer(nml__ptr, nml__obj)
    nml__status = NML_OK
  end subroutine nml_c_bindings_resolve_handle

  !> \brief Initialize defaults and sentinels for c_bindings
  integer function nml_c_bindings_init(nml__obj, errmsg) result(nml__status)
    class(nml_c_bindings_t), intent(inout) :: nml__obj !< namelist instance
    character(len=*), intent(out), optional :: errmsg !< error message for non-OK status values

    nml__status = NML_OK
    if (present(errmsg)) errmsg = ""
    nml__obj%is_configured = .false.

    ! allocate runtime-sized fields
    if (allocated(nml__obj%data%values)) deallocate(nml__obj%data%values)
    allocate(nml__obj%data%values(nml__obj%dims%c_intptr_t))

    ! default values
    nml__obj%data%c_intptr_t = c_intptr_t__default
    nml__obj%data%c_ptr = c_ptr__default
    nml__obj%data%c_null_ptr = c_null_ptr__default
    nml__obj%data%c_f_pointer = c_f_pointer__default
    nml__obj%data%values = values__default
  end function nml_c_bindings_init

  !> \brief Reset runtime dimensions for c_bindings
  integer function nml_c_bindings_set_dims(nml__obj, &
    c_intptr_t, &
    errmsg) result(nml__status)
    class(nml_c_bindings_t), intent(inout) :: nml__obj !< namelist instance
    integer, intent(in), optional :: c_intptr_t !< runtime dimension override for c_intptr_t
    integer :: candidate__c_intptr_t
    character(len=*), intent(out), optional :: errmsg !< error message for non-OK status values

    nml__status = NML_OK
    if (present(errmsg)) errmsg = ""
    if (present(c_intptr_t)) then
      candidate__c_intptr_t = c_intptr_t
    else
      candidate__c_intptr_t = c_intptr_t__dim_default
    end if
    if (candidate__c_intptr_t <= 0) then
      nml__status = NML_ERR_INVALID_INDEX
      if (present(errmsg)) errmsg = "dimension 'c_intptr_t' must be positive"
      return
    end if
    nml__obj%dims%c_intptr_t = candidate__c_intptr_t

    ! deallocate runtime-sized fields; init/set/from_file allocate them again
    if (allocated(nml__obj%data%values)) deallocate(nml__obj%data%values)
    nml__obj%is_configured = .false.
  end function nml_c_bindings_set_dims


  !> \brief Read c_bindings namelist from file
  integer function nml_c_bindings_from_file(nml__obj, file, errmsg) result(nml__status)
    class(nml_c_bindings_t), intent(inout) :: nml__obj !< namelist instance
    character(len=*), intent(in) :: file !< path to namelist file
    character(len=*), intent(out), optional :: errmsg !< error message for non-OK status values

    nml__status = nml_c_bindings_read__from_file(nml__obj, file, errmsg)
  end function nml_c_bindings_from_file

  integer function nml_c_bindings_read__from_file(nml__obj, nml__file, errmsg) &
    result(nml__status)
    class(nml_c_bindings_t), intent(inout) :: nml__obj
    character(len=*), intent(in) :: nml__file
    character(len=*), intent(out), optional :: errmsg
    ! namelist variables
    integer :: c_intptr_t
    integer :: c_ptr
    integer :: c_null_ptr
    integer :: c_f_pointer
    integer, allocatable, dimension(:) :: values
    ! locals
    type(nml_file_t) :: nml__reader
    integer :: nml__iostat
    integer :: nml__close_status
    character(len=nml_line_buffer) :: nml__iomsg

    namelist /c_bindings/ &
      c_intptr_t, &
      c_ptr, &
      c_null_ptr, &
      c_f_pointer, &
      values

    nml__status = nml__obj%init(errmsg=errmsg)
    if (nml__status /= NML_OK) return
    ! allocate local namelist variables matching runtime-sized fields
    if (allocated(values)) deallocate(values)
    allocate(values(nml__obj%dims%c_intptr_t))
    c_intptr_t = nml__obj%data%c_intptr_t
    c_ptr = nml__obj%data%c_ptr
    c_null_ptr = nml__obj%data%c_null_ptr
    c_f_pointer = nml__obj%data%c_f_pointer
    values = nml__obj%data%values

    nml__status = nml__reader%open(nml__file, errmsg=errmsg)
    if (nml__status /= NML_OK) return

    nml__status = nml__reader%find("c_bindings", errmsg=errmsg)
    if (nml__status /= NML_OK) then
      if (nml__status == NML_ERR_NML_NOT_FOUND) then
        nml__close_status = nml__reader%close(errmsg=errmsg)
        if (nml__close_status /= NML_OK) then
          nml__status = nml__close_status
          return
        end if
        nml__obj%is_configured = .true.
        nml__status = NML_OK
        return
      end if
      nml__close_status = nml__reader%close()
      return
    end if

    ! read namelist
    read(nml__reader%unit, nml=c_bindings, iostat=nml__iostat, iomsg=nml__iomsg)
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
    nml__obj%data%c_intptr_t = c_intptr_t
    nml__obj%data%c_ptr = c_ptr
    nml__obj%data%c_null_ptr = c_null_ptr
    nml__obj%data%c_f_pointer = c_f_pointer
    nml__obj%data%values = values

    ! mark as configured
    nml__obj%is_configured = .true.
    nml__status = NML_OK
  end function nml_c_bindings_read__from_file

  !> \brief Set c_bindings values
  integer function nml_c_bindings_set(nml__obj, &
    c_intptr_t, &
    c_ptr, &
    c_null_ptr, &
    c_f_pointer, &
    values, &
    errmsg) result(nml__status)

    class(nml_c_bindings_t), intent(inout) :: nml__obj !< namelist instance
    character(len=*), intent(out), optional :: errmsg !< error message for non-OK status values
    integer, intent(in), optional :: c_intptr_t !< c_intptr_t
    integer, intent(in), optional :: c_ptr !< c_ptr
    integer, intent(in), optional :: c_null_ptr !< c_null_ptr
    integer, intent(in), optional :: c_f_pointer !< c_f_pointer
    integer, dimension(:), intent(in), optional :: values !< values
    nml__status = nml__obj%init(errmsg=errmsg)
    if (nml__status /= NML_OK) return

    ! required parameters
    ! override with provided values
    if (present(c_intptr_t)) nml__obj%data%c_intptr_t = c_intptr_t
    if (present(c_ptr)) nml__obj%data%c_ptr = c_ptr
    if (present(c_null_ptr)) nml__obj%data%c_null_ptr = c_null_ptr
    if (present(c_f_pointer)) nml__obj%data%c_f_pointer = c_f_pointer
    if (present(values)) then
      if (size(values, 1) > size(nml__obj%data%values, 1)) then
        nml__status = NML_ERR_INVALID_INDEX
        if (present(errmsg)) errmsg = "dimension 1 exceeds bounds for 'values'"
        return
      end if
      nml__obj%data%values( &
        1:size(values, 1)) = values
    end if

    ! mark as configured
    nml__obj%is_configured = .true.
    nml__status = NML_OK
  end function nml_c_bindings_set

  !> \brief Check whether a namelist value was set
  integer function nml_c_bindings_is_set(nml__obj, name, idx, errmsg) result(nml__status)
    class(nml_c_bindings_t), intent(in) :: nml__obj !< namelist instance
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
    case ("c_intptr_t")
      if (present(idx)) then
        nml__status = NML_ERR_INVALID_INDEX
        if (present(errmsg)) errmsg = "index not supported for 'c_intptr_t'"
        return
      end if
    case ("c_ptr")
      if (present(idx)) then
        nml__status = NML_ERR_INVALID_INDEX
        if (present(errmsg)) errmsg = "index not supported for 'c_ptr'"
        return
      end if
    case ("c_null_ptr")
      if (present(idx)) then
        nml__status = NML_ERR_INVALID_INDEX
        if (present(errmsg)) errmsg = "index not supported for 'c_null_ptr'"
        return
      end if
    case ("c_f_pointer")
      if (present(idx)) then
        nml__status = NML_ERR_INVALID_INDEX
        if (present(errmsg)) errmsg = "index not supported for 'c_f_pointer'"
        return
      end if
    case ("values")
      if (.not. allocated(nml__obj%data%values)) then
        nml__status = NML_ERR_NOT_SET
        return
      end if
      if (present(idx)) then
        nml__status = idx__check(idx, shape(nml__obj%data%values), &
          "values", errmsg)
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
  end function nml_c_bindings_is_set

  !> \brief Validate required values and constraints
  integer function nml_c_bindings_is_valid(nml__obj, errmsg) result(nml__status)
    class(nml_c_bindings_t), intent(in) :: nml__obj !< namelist instance
    character(len=*), intent(out), optional :: errmsg !< error message for non-OK status values
    integer :: nml__istat

    nml__status = NML_OK
    if (present(errmsg)) errmsg = ""
    if (.not. nml__obj%is_configured) then
      nml__status = NML_ERR_NOT_SET
      if (present(errmsg)) errmsg = "namelist not configured; call set or from_file"
      return
    end if

  end function nml_c_bindings_is_valid

end module nml_c_bindings
