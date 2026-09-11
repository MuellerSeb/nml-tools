!> \file nml_namespaces.f90
!> \copydoc nml_namespaces

!> \brief Namespace conformance
!> \details Namespace conformance
module nml_namespaces
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
    nml__achar => achar, &
    nml__all => all, &
    nml__allocated => allocated, &
    nml__any => any, &
    nml__huge => huge, &
    nml__len => len, &
    nml__len_trim => len_trim, &
    nml__minval => minval, &
    nml__present => present, &
    nml__reshape => reshape, &
    nml__shape => shape, &
    nml__size => size, &
    nml__trim => trim, &
    to_lower, &
    status__dim_default, &
    set_dims__dim_default

  implicit none

  ! default values
  integer, parameter, public :: status__default = 0
  integer, parameter, public :: present__default = 0
  integer, parameter, public :: file__default = 0
  integer, parameter, public :: nml__default = 0
  integer, parameter, public :: iostat__default = 0
  integer, parameter, public :: close_status__default = 0
  integer, parameter, public :: data__default = 0
  integer, parameter, public :: dims__default = 0
  integer, parameter, public :: set__default = 0
  integer, parameter, public :: set_dims__default = 0
  integer, parameter, public :: init__default = 0
  integer, parameter, public :: init_type__default = 0
  integer, parameter, public :: from_file__default = 0
  integer, parameter, public :: is_set__default = 0
  integer, parameter, public :: is_valid__default = 0
  integer, parameter, public :: filled_shape__default = 0
  integer, parameter, public :: is_configured__default = 0
  integer, parameter, public :: size__default = 0
  integer, parameter, public :: values__default = 0
  integer, parameter, public :: more_values__default = 0

  private :: nml_namespaces_read__from_file
  private :: nml__achar, nml__all, nml__allocated, nml__any, nml__huge, nml__len, &
    nml__len_trim, nml__minval, nml__present, nml__reshape, nml__shape, nml__size, &
    nml__trim

  !> \class nml_namespaces_data_t
  !> \brief Schema-backed values for namespaces
  type, public :: nml_namespaces_data_t
    integer :: status !< status
    integer :: present !< present
    integer :: file !< file
    integer :: nml !< nml
    integer :: iostat !< iostat
    integer :: close_status !< close_status
    integer :: data !< data
    integer :: dims !< dims
    integer :: set !< set
    integer :: set_dims !< set_dims
    integer :: init !< init
    integer :: init_type !< init_type
    integer :: from_file !< from_file
    integer :: is_set !< is_set
    integer :: is_valid !< is_valid
    integer :: filled_shape !< filled_shape
    integer :: is_configured !< is_configured
    integer :: size !< size
    integer, allocatable, dimension(:) :: values !< values
    integer, allocatable, dimension(:) :: more_values !< more_values
  end type nml_namespaces_data_t

  !> \class nml_namespaces_dims_t
  !> \brief Runtime dimensions for namespaces
  type, public :: nml_namespaces_dims_t
    integer :: status = status__dim_default !< runtime dimension for status
    integer :: set_dims = set_dims__dim_default !< runtime dimension for set_dims
  end type nml_namespaces_dims_t

  !> \class nml_namespaces_t
  !> \brief Namespace conformance
  !> \details Namespace conformance
  type, public :: nml_namespaces_t
    type(nml_namespaces_data_t) :: data !< schema-backed namelist values
    type(nml_namespaces_dims_t) :: dims !< runtime array dimensions
    logical :: is_configured = .false. !< whether the namelist has been configured
  contains
    procedure :: init => nml_namespaces_init
    procedure :: set_dims => nml_namespaces_set_dims
    procedure :: from_file => nml_namespaces_from_file
    procedure :: set => nml_namespaces_set
    procedure :: is_set => nml_namespaces_is_set
    procedure :: is_valid => nml_namespaces_is_valid
  end type nml_namespaces_t

contains

  !> \brief Initialize defaults and sentinels for namespaces
  integer function nml_namespaces_init(nml__obj, errmsg) result(nml__status)
    class(nml_namespaces_t), intent(inout) :: nml__obj !< namelist instance
    character(len=*), intent(out), optional :: errmsg !< error message for non-OK status values

    nml__status = NML_OK
    if (nml__present(errmsg)) errmsg = ""
    nml__obj%is_configured = .false.

    ! allocate runtime-sized fields
    if (nml__allocated(nml__obj%data%values)) deallocate(nml__obj%data%values)
    allocate(nml__obj%data%values(nml__obj%dims%status))
    if (nml__allocated(nml__obj%data%more_values)) deallocate(nml__obj%data%more_values)
    allocate(nml__obj%data%more_values(nml__obj%dims%set_dims))

    ! default values
    nml__obj%data%status = status__default
    nml__obj%data%present = present__default
    nml__obj%data%file = file__default
    nml__obj%data%nml = nml__default
    nml__obj%data%iostat = iostat__default
    nml__obj%data%close_status = close_status__default
    nml__obj%data%data = data__default
    nml__obj%data%dims = dims__default
    nml__obj%data%set = set__default
    nml__obj%data%set_dims = set_dims__default
    nml__obj%data%init = init__default
    nml__obj%data%init_type = init_type__default
    nml__obj%data%from_file = from_file__default
    nml__obj%data%is_set = is_set__default
    nml__obj%data%is_valid = is_valid__default
    nml__obj%data%filled_shape = filled_shape__default
    nml__obj%data%is_configured = is_configured__default
    nml__obj%data%size = size__default
    nml__obj%data%values = values__default
    nml__obj%data%more_values = more_values__default
  end function nml_namespaces_init

  !> \brief Reset runtime dimensions for namespaces
  integer function nml_namespaces_set_dims(nml__obj, &
    status, &
    set_dims, &
    errmsg) result(nml__status)
    class(nml_namespaces_t), intent(inout) :: nml__obj !< namelist instance
    integer, intent(in), optional :: status !< runtime dimension override for status
    integer, intent(in), optional :: set_dims !< runtime dimension override for set_dims
    integer :: candidate__status
    integer :: candidate__set_dims
    character(len=*), intent(out), optional :: errmsg !< error message for non-OK status values

    nml__status = NML_OK
    if (nml__present(errmsg)) errmsg = ""
    if (nml__present(status)) then
      candidate__status = status
    else
      candidate__status = status__dim_default
    end if
    if (candidate__status <= 0) then
      nml__status = NML_ERR_INVALID_INDEX
      if (nml__present(errmsg)) errmsg = "dimension 'status' must be positive"
      return
    end if
    if (nml__present(set_dims)) then
      candidate__set_dims = set_dims
    else
      candidate__set_dims = set_dims__dim_default
    end if
    if (candidate__set_dims <= 0) then
      nml__status = NML_ERR_INVALID_INDEX
      if (nml__present(errmsg)) errmsg = "dimension 'set_dims' must be positive"
      return
    end if
    nml__obj%dims%status = candidate__status
    nml__obj%dims%set_dims = candidate__set_dims

    ! deallocate runtime-sized fields; init/set/from_file allocate them again
    if (nml__allocated(nml__obj%data%values)) deallocate(nml__obj%data%values)
    if (nml__allocated(nml__obj%data%more_values)) deallocate(nml__obj%data%more_values)
    nml__obj%is_configured = .false.
  end function nml_namespaces_set_dims


  !> \brief Read namespaces namelist from file
  integer function nml_namespaces_from_file(nml__obj, file, errmsg) result(nml__status)
    class(nml_namespaces_t), intent(inout) :: nml__obj !< namelist instance
    character(len=*), intent(in) :: file !< path to namelist file
    character(len=*), intent(out), optional :: errmsg !< error message for non-OK status values

    nml__status = nml_namespaces_read__from_file(nml__obj, file, errmsg)
  end function nml_namespaces_from_file

  integer function nml_namespaces_read__from_file(nml__obj, nml__file, errmsg) &
    result(nml__status)
    class(nml_namespaces_t), intent(inout) :: nml__obj
    character(len=*), intent(in) :: nml__file
    character(len=*), intent(out), optional :: errmsg
    ! namelist variables
    integer :: status
    integer :: present
    integer :: file
    integer :: nml
    integer :: iostat
    integer :: close_status
    integer :: data
    integer :: dims
    integer :: set
    integer :: set_dims
    integer :: init
    integer :: init_type
    integer :: from_file
    integer :: is_set
    integer :: is_valid
    integer :: filled_shape
    integer :: is_configured
    integer :: size
    integer, allocatable, dimension(:) :: values
    integer, allocatable, dimension(:) :: more_values
    ! locals
    type(nml_file_t) :: nml__reader
    integer :: nml__iostat
    integer :: nml__close_status
    character(len=nml_line_buffer) :: nml__iomsg

    namelist /namespaces/ &
      status, &
      present, &
      file, &
      nml, &
      iostat, &
      close_status, &
      data, &
      dims, &
      set, &
      set_dims, &
      init, &
      init_type, &
      from_file, &
      is_set, &
      is_valid, &
      filled_shape, &
      is_configured, &
      size, &
      values, &
      more_values

    nml__status = nml__obj%init(errmsg=errmsg)
    if (nml__status /= NML_OK) return
    ! allocate local namelist variables matching runtime-sized fields
    if (nml__allocated(values)) deallocate(values)
    allocate(values(nml__obj%dims%status))
    if (nml__allocated(more_values)) deallocate(more_values)
    allocate(more_values(nml__obj%dims%set_dims))
    status = nml__obj%data%status
    present = nml__obj%data%present
    file = nml__obj%data%file
    nml = nml__obj%data%nml
    iostat = nml__obj%data%iostat
    close_status = nml__obj%data%close_status
    data = nml__obj%data%data
    dims = nml__obj%data%dims
    set = nml__obj%data%set
    set_dims = nml__obj%data%set_dims
    init = nml__obj%data%init
    init_type = nml__obj%data%init_type
    from_file = nml__obj%data%from_file
    is_set = nml__obj%data%is_set
    is_valid = nml__obj%data%is_valid
    filled_shape = nml__obj%data%filled_shape
    is_configured = nml__obj%data%is_configured
    size = nml__obj%data%size
    values = nml__obj%data%values
    more_values = nml__obj%data%more_values

    nml__status = nml__reader%open(nml__file, errmsg=errmsg)
    if (nml__status /= NML_OK) return

    nml__status = nml__reader%find("namespaces", errmsg=errmsg)
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
    read(nml__reader%unit, nml=namespaces, iostat=nml__iostat, iomsg=nml__iomsg)
    if (nml__iostat /= 0) then
      nml__status = NML_ERR_READ
      if (nml__present(errmsg)) errmsg = nml__trim(nml__iomsg)
      nml__close_status = nml__reader%close()
      return
    end if
    nml__close_status = nml__reader%close(errmsg=errmsg)
    if (nml__close_status /= NML_OK) then
      nml__status = nml__close_status
      return
    end if

    ! assign values
    nml__obj%data%status = status
    nml__obj%data%present = present
    nml__obj%data%file = file
    nml__obj%data%nml = nml
    nml__obj%data%iostat = iostat
    nml__obj%data%close_status = close_status
    nml__obj%data%data = data
    nml__obj%data%dims = dims
    nml__obj%data%set = set
    nml__obj%data%set_dims = set_dims
    nml__obj%data%init = init
    nml__obj%data%init_type = init_type
    nml__obj%data%from_file = from_file
    nml__obj%data%is_set = is_set
    nml__obj%data%is_valid = is_valid
    nml__obj%data%filled_shape = filled_shape
    nml__obj%data%is_configured = is_configured
    nml__obj%data%size = size
    nml__obj%data%values = values
    nml__obj%data%more_values = more_values

    ! mark as configured
    nml__obj%is_configured = .true.
    nml__status = NML_OK
  end function nml_namespaces_read__from_file

  !> \brief Set namespaces values
  integer function nml_namespaces_set(nml__obj, &
    status, &
    present, &
    file, &
    nml, &
    iostat, &
    close_status, &
    data, &
    dims, &
    set, &
    set_dims, &
    init, &
    init_type, &
    from_file, &
    is_set, &
    is_valid, &
    filled_shape, &
    is_configured, &
    size, &
    values, &
    more_values, &
    errmsg) result(nml__status)

    class(nml_namespaces_t), intent(inout) :: nml__obj !< namelist instance
    character(len=*), intent(out), optional :: errmsg !< error message for non-OK status values
    integer, intent(in), optional :: status !< status
    integer, intent(in), optional :: present !< present
    integer, intent(in), optional :: file !< file
    integer, intent(in), optional :: nml !< nml
    integer, intent(in), optional :: iostat !< iostat
    integer, intent(in), optional :: close_status !< close_status
    integer, intent(in), optional :: data !< data
    integer, intent(in), optional :: dims !< dims
    integer, intent(in), optional :: set !< set
    integer, intent(in), optional :: set_dims !< set_dims
    integer, intent(in), optional :: init !< init
    integer, intent(in), optional :: init_type !< init_type
    integer, intent(in), optional :: from_file !< from_file
    integer, intent(in), optional :: is_set !< is_set
    integer, intent(in), optional :: is_valid !< is_valid
    integer, intent(in), optional :: filled_shape !< filled_shape
    integer, intent(in), optional :: is_configured !< is_configured
    integer, intent(in), optional :: size !< size
    integer, dimension(:), intent(in), optional :: values !< values
    integer, dimension(:), intent(in), optional :: more_values !< more_values
    nml__status = nml__obj%init(errmsg=errmsg)
    if (nml__status /= NML_OK) return

    ! required parameters
    ! override with provided values
    if (nml__present(status)) nml__obj%data%status = status
    if (nml__present(present)) nml__obj%data%present = present
    if (nml__present(file)) nml__obj%data%file = file
    if (nml__present(nml)) nml__obj%data%nml = nml
    if (nml__present(iostat)) nml__obj%data%iostat = iostat
    if (nml__present(close_status)) nml__obj%data%close_status = close_status
    if (nml__present(data)) nml__obj%data%data = data
    if (nml__present(dims)) nml__obj%data%dims = dims
    if (nml__present(set)) nml__obj%data%set = set
    if (nml__present(set_dims)) nml__obj%data%set_dims = set_dims
    if (nml__present(init)) nml__obj%data%init = init
    if (nml__present(init_type)) nml__obj%data%init_type = init_type
    if (nml__present(from_file)) nml__obj%data%from_file = from_file
    if (nml__present(is_set)) nml__obj%data%is_set = is_set
    if (nml__present(is_valid)) nml__obj%data%is_valid = is_valid
    if (nml__present(filled_shape)) nml__obj%data%filled_shape = filled_shape
    if (nml__present(is_configured)) nml__obj%data%is_configured = is_configured
    if (nml__present(size)) nml__obj%data%size = size
    if (nml__present(values)) then
      if (nml__size(values, 1) > nml__size(nml__obj%data%values, 1)) then
        nml__status = NML_ERR_INVALID_INDEX
        if (nml__present(errmsg)) errmsg = "dimension 1 exceeds bounds for 'values'"
        return
      end if
      nml__obj%data%values( &
        1:nml__size(values, 1)) = values
    end if
    if (nml__present(more_values)) then
      if (nml__size(more_values, 1) > nml__size(nml__obj%data%more_values, 1)) then
        nml__status = NML_ERR_INVALID_INDEX
        if (nml__present(errmsg)) errmsg = "dimension 1 exceeds bounds for 'more_values'"
        return
      end if
      nml__obj%data%more_values( &
        1:nml__size(more_values, 1)) = more_values
    end if

    ! mark as configured
    nml__obj%is_configured = .true.
    nml__status = NML_OK
  end function nml_namespaces_set

  !> \brief Check whether a namelist value was set
  integer function nml_namespaces_is_set(nml__obj, name, idx, errmsg) result(nml__status)
    class(nml_namespaces_t), intent(in) :: nml__obj !< namelist instance
    character(len=*), intent(in) :: name !< field name
    integer, intent(in), optional :: idx(:) !< optional field index values
    character(len=*), intent(out), optional :: errmsg !< error message for non-OK status values

    nml__status = NML_OK
    if (nml__present(errmsg)) errmsg = ""
    if (.not. nml__obj%is_configured) then
      nml__status = NML_ERR_NOT_SET
      if (nml__present(errmsg)) errmsg = "namelist not configured; call set or from_file"
      return
    end if
    select case (to_lower(nml__trim(name)))
    case ("status")
      if (nml__present(idx)) then
        nml__status = NML_ERR_INVALID_INDEX
        if (nml__present(errmsg)) errmsg = "index not supported for 'status'"
        return
      end if
    case ("present")
      if (nml__present(idx)) then
        nml__status = NML_ERR_INVALID_INDEX
        if (nml__present(errmsg)) errmsg = "index not supported for 'present'"
        return
      end if
    case ("file")
      if (nml__present(idx)) then
        nml__status = NML_ERR_INVALID_INDEX
        if (nml__present(errmsg)) errmsg = "index not supported for 'file'"
        return
      end if
    case ("nml")
      if (nml__present(idx)) then
        nml__status = NML_ERR_INVALID_INDEX
        if (nml__present(errmsg)) errmsg = "index not supported for 'nml'"
        return
      end if
    case ("iostat")
      if (nml__present(idx)) then
        nml__status = NML_ERR_INVALID_INDEX
        if (nml__present(errmsg)) errmsg = "index not supported for 'iostat'"
        return
      end if
    case ("close_status")
      if (nml__present(idx)) then
        nml__status = NML_ERR_INVALID_INDEX
        if (nml__present(errmsg)) errmsg = "index not supported for 'close_status'"
        return
      end if
    case ("data")
      if (nml__present(idx)) then
        nml__status = NML_ERR_INVALID_INDEX
        if (nml__present(errmsg)) errmsg = "index not supported for 'data'"
        return
      end if
    case ("dims")
      if (nml__present(idx)) then
        nml__status = NML_ERR_INVALID_INDEX
        if (nml__present(errmsg)) errmsg = "index not supported for 'dims'"
        return
      end if
    case ("set")
      if (nml__present(idx)) then
        nml__status = NML_ERR_INVALID_INDEX
        if (nml__present(errmsg)) errmsg = "index not supported for 'set'"
        return
      end if
    case ("set_dims")
      if (nml__present(idx)) then
        nml__status = NML_ERR_INVALID_INDEX
        if (nml__present(errmsg)) errmsg = "index not supported for 'set_dims'"
        return
      end if
    case ("init")
      if (nml__present(idx)) then
        nml__status = NML_ERR_INVALID_INDEX
        if (nml__present(errmsg)) errmsg = "index not supported for 'init'"
        return
      end if
    case ("init_type")
      if (nml__present(idx)) then
        nml__status = NML_ERR_INVALID_INDEX
        if (nml__present(errmsg)) errmsg = "index not supported for 'init_type'"
        return
      end if
    case ("from_file")
      if (nml__present(idx)) then
        nml__status = NML_ERR_INVALID_INDEX
        if (nml__present(errmsg)) errmsg = "index not supported for 'from_file'"
        return
      end if
    case ("is_set")
      if (nml__present(idx)) then
        nml__status = NML_ERR_INVALID_INDEX
        if (nml__present(errmsg)) errmsg = "index not supported for 'is_set'"
        return
      end if
    case ("is_valid")
      if (nml__present(idx)) then
        nml__status = NML_ERR_INVALID_INDEX
        if (nml__present(errmsg)) errmsg = "index not supported for 'is_valid'"
        return
      end if
    case ("filled_shape")
      if (nml__present(idx)) then
        nml__status = NML_ERR_INVALID_INDEX
        if (nml__present(errmsg)) errmsg = "index not supported for 'filled_shape'"
        return
      end if
    case ("is_configured")
      if (nml__present(idx)) then
        nml__status = NML_ERR_INVALID_INDEX
        if (nml__present(errmsg)) errmsg = "index not supported for 'is_configured'"
        return
      end if
    case ("size")
      if (nml__present(idx)) then
        nml__status = NML_ERR_INVALID_INDEX
        if (nml__present(errmsg)) errmsg = "index not supported for 'size'"
        return
      end if
    case ("values")
      if (.not. nml__allocated(nml__obj%data%values)) then
        nml__status = NML_ERR_NOT_SET
        return
      end if
      if (nml__present(idx)) then
        nml__status = idx_check(idx, nml__shape(nml__obj%data%values), &
          "values", errmsg)
        if (nml__status /= NML_OK) return
      else
      end if
    case ("more_values")
      if (.not. nml__allocated(nml__obj%data%more_values)) then
        nml__status = NML_ERR_NOT_SET
        return
      end if
      if (nml__present(idx)) then
        nml__status = idx_check(idx, nml__shape(nml__obj%data%more_values), &
          "more_values", errmsg)
        if (nml__status /= NML_OK) return
      else
      end if
    case default
      nml__status = NML_ERR_INVALID_NAME
      if (nml__present(errmsg)) errmsg = "unknown field: " // nml__trim(name)
    end select
    if (nml__status == NML_ERR_NOT_SET .and. nml__present(errmsg)) then
      if (nml__len_trim(errmsg) == 0) errmsg = "field not set: " // nml__trim(name)
    end if
  end function nml_namespaces_is_set

  !> \brief Validate required values and constraints
  integer function nml_namespaces_is_valid(nml__obj, errmsg) result(nml__status)
    class(nml_namespaces_t), intent(in) :: nml__obj !< namelist instance
    character(len=*), intent(out), optional :: errmsg !< error message for non-OK status values
    integer :: nml__istat

    nml__status = NML_OK
    if (nml__present(errmsg)) errmsg = ""
    if (.not. nml__obj%is_configured) then
      nml__status = NML_ERR_NOT_SET
      if (nml__present(errmsg)) errmsg = "namelist not configured; call set or from_file"
      return
    end if

  end function nml_namespaces_is_valid

end module nml_namespaces
