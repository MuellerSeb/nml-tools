!> \file nml_records.f90
!> \copydoc nml_records

!> \brief records
!> \details records
module nml_records
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
    n_records__default, &
    entry_t, &
    known_t, &
    context_t, &
    NML_ERR_PARTLY_SET

  implicit none

  !> \class nml_records_t
  !> \brief records
  !> \details records
  type, public :: nml_records_t
    logical :: is_configured = .false. !< whether the namelist has been configured
    integer :: n_records = n_records__default !< runtime dimension for n_records
    type(entry_t), allocatable, dimension(:, :) :: entries !< entries
    type(known_t), dimension(2) :: known !< known
    type(context_t) :: context !< context
  contains
    procedure :: init => nml_records_init
    procedure :: init_type => nml_records_init_type
    procedure :: set_dims => nml_records_set_dims
    procedure :: from_file => nml_records_from_file
    procedure :: set => nml_records_set
    procedure :: is_set => nml_records_is_set
    procedure, private :: set_mask__rank__1 => nml_records_set_mask__rank__1
    procedure, private :: set_mask__rank__2 => nml_records_set_mask__rank__2
    generic :: set_mask => &
      set_mask__rank__1, &
      set_mask__rank__2
    procedure :: filled_shape => nml_records_filled_shape
    procedure :: is_valid => nml_records_is_valid
  end type nml_records_t

contains

  !> \brief Initialize defaults and sentinels for records
  integer function nml_records_init(this, errmsg) result(status)
    class(nml_records_t), intent(inout) :: this !< namelist instance
    character(len=*), intent(out), optional :: errmsg !< error message for non-OK status values

    status = NML_OK
    if (present(errmsg)) errmsg = ""
    this%is_configured = .false.

    ! derived values
    status = this%init_type( &
      entries=this%entries, &
      known=this%known, &
      context=this%context, &
      errmsg=errmsg)
    if (status /= NML_OK) return
  end function nml_records_init

  !> \brief Initialize derived values with their field-specific defaults
  integer function nml_records_init_type(this, &
    entries, &
    known, &
    context, &
    errmsg) result(status)
    class(nml_records_t), intent(in) :: this !< parent namelist instance
    type(entry_t), dimension(:, :), allocatable, intent(inout), optional :: entries !< entries
    type(known_t), dimension(:), intent(inout), optional :: known !< known
    type(context_t), intent(inout), optional :: context !< context
    character(len=*), intent(out), optional :: errmsg !< error message for non-OK status values

    status = NML_OK
    if (present(errmsg)) errmsg = ""
    if (present(entries)) then
      if (allocated(entries)) deallocate(entries)
      allocate(entries(this%n_records, 2))
      entries%left = -huge(entries%left) ! sentinel for derived component left
      entries%right = -huge(entries%right) ! sentinel for derived component right
      entries%note = achar(0) ! sentinel for derived component note
      entries%flag = .true.
    end if
    if (present(known)) then
      known%value = 7
    end if
    if (present(context)) then
      context%value = 0
    end if
  end function nml_records_init_type

  !> \brief Reset runtime dimensions for records
  integer function nml_records_set_dims(this, &
    n_records, &
    errmsg) result(status)
    class(nml_records_t), intent(inout) :: this !< namelist instance
    integer, intent(in), optional :: n_records !< runtime dimension override for n_records
    integer :: candidate__n_records
    character(len=*), intent(out), optional :: errmsg !< error message for non-OK status values

    status = NML_OK
    if (present(errmsg)) errmsg = ""
    if (present(n_records)) then
      candidate__n_records = n_records
    else
      candidate__n_records = n_records__default
    end if
    if (candidate__n_records <= 0) then
      status = NML_ERR_INVALID_INDEX
      if (present(errmsg)) errmsg = "dimension 'n_records' must be positive"
      return
    end if
    this%n_records = candidate__n_records

    ! deallocate runtime-sized fields; init/set/from_file allocate them again
    if (allocated(this%entries)) deallocate(this%entries)
    this%is_configured = .false.
  end function nml_records_set_dims


  !> \brief Read records namelist from file
  integer function nml_records_from_file(this, file, errmsg) result(status)
    class(nml_records_t), intent(inout) :: this !< namelist instance
    character(len=*), intent(in) :: file !< path to namelist file
    character(len=*), intent(out), optional :: errmsg !< error message for non-OK status values
    ! namelist variables
    type(entry_t), allocatable, dimension(:, :) :: entries
    type(known_t), dimension(2) :: known
    type(context_t) :: context
    ! locals
    type(nml_file_t) :: nml
    integer :: iostat
    integer :: close_status
    character(len=nml_line_buffer) :: iomsg

    namelist /records/ &
      entries, &
      known, &
      context

    status = this%init(errmsg=errmsg)
    if (status /= NML_OK) return
    ! allocate local namelist variables matching runtime-sized fields
    if (allocated(entries)) deallocate(entries)
    allocate(entries(this%n_records, 2))
    entries = this%entries
    known = this%known
    context = this%context

    status = nml%open(file, errmsg=errmsg)
    if (status /= NML_OK) return

    status = nml%find("records", errmsg=errmsg)
    if (status /= NML_OK) then
      close_status = nml%close()
      return
    end if

    ! read namelist
    read(nml%unit, nml=records, iostat=iostat, iomsg=iomsg)
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
    this%entries = entries
    this%known = known
    this%context = context

    ! mark as configured
    this%is_configured = .true.
    status = NML_OK
  end function nml_records_from_file

  !> \brief Set records values
  integer function nml_records_set(this, &
    entries, &
    known, &
    context, &
    errmsg) result(status)

    class(nml_records_t), intent(inout) :: this !< namelist instance
    character(len=*), intent(out), optional :: errmsg !< error message for non-OK status values
    type(entry_t), dimension(:, :), intent(in) :: entries !< entries
    type(known_t), dimension(:), intent(in), optional :: known !< known
    type(context_t), intent(in), optional :: context !< context

    status = this%init(errmsg=errmsg)
    if (status /= NML_OK) return

    ! required parameters
    if (size(entries, 1) > size(this%entries, 1)) then
      status = NML_ERR_INVALID_INDEX
      if (present(errmsg)) errmsg = "dimension 1 exceeds bounds for 'entries'"
      return
    end if
    if (size(entries, 2) > size(this%entries, 2)) then
      status = NML_ERR_INVALID_INDEX
      if (present(errmsg)) errmsg = "dimension 2 exceeds bounds for 'entries'"
      return
    end if
    this%entries(1:size(entries, 1), 1:size(entries, 2)) = entries
    ! override with provided values
    if (present(known)) then
      if (size(known, 1) > size(this%known, 1)) then
        status = NML_ERR_INVALID_INDEX
        if (present(errmsg)) errmsg = "dimension 1 exceeds bounds for 'known'"
        return
      end if
      this%known(1:size(known, 1)) = known
    end if
    if (present(context)) this%context = context

    ! mark as configured
    this%is_configured = .true.
    status = NML_OK
  end function nml_records_set

  !> \brief Check whether a namelist value was set
  integer function nml_records_is_set(this, name, idx, errmsg) result(status)
    class(nml_records_t), intent(in) :: this !< namelist instance
    character(len=*), intent(in) :: name !< field name
    integer, intent(in), optional :: idx(:) !< optional field index values
    character(len=*), intent(out), optional :: errmsg !< error message for non-OK status values
    intrinsic :: shape

    status = NML_OK
    if (present(errmsg)) errmsg = ""
    if (.not. this%is_configured) then
      status = NML_ERR_NOT_SET
      if (present(errmsg)) errmsg = "namelist not configured; call set or from_file"
      return
    end if
    select case (to_lower(trim(name)))
    case ("entries%left")
      if (.not. allocated(this%entries)) then
        status = NML_ERR_NOT_SET
        if (present(errmsg)) errmsg = "array storage unavailable: entries%left"
        return
      end if
      if (present(idx)) then
        status = idx_check(idx, shape(this%entries), "entries%left", errmsg)
        if (status /= NML_OK) return
        if (this%entries(idx(1), idx(2))%left == -huge(this%entries(idx(1), idx(2))%left)) status = NML_ERR_NOT_SET
      else
        if (all(this%entries%left == -huge(this%entries%left))) status = NML_ERR_NOT_SET
      end if
    case ("entries%right")
      if (.not. allocated(this%entries)) then
        status = NML_ERR_NOT_SET
        if (present(errmsg)) errmsg = "array storage unavailable: entries%right"
        return
      end if
      if (present(idx)) then
        status = idx_check(idx, shape(this%entries), "entries%right", errmsg)
        if (status /= NML_OK) return
        if (this%entries(idx(1), idx(2))%right == -huge(this%entries(idx(1), idx(2))%right)) status = NML_ERR_NOT_SET
      else
        if (all(this%entries%right == -huge(this%entries%right))) status = NML_ERR_NOT_SET
      end if
    case ("entries%note")
      if (.not. allocated(this%entries)) then
        status = NML_ERR_NOT_SET
        if (present(errmsg)) errmsg = "array storage unavailable: entries%note"
        return
      end if
      if (present(idx)) then
        status = idx_check(idx, shape(this%entries), "entries%note", errmsg)
        if (status /= NML_OK) return
        if (this%entries(idx(1), idx(2))%note == achar(0)) status = NML_ERR_NOT_SET
      else
        if (all(this%entries%note == achar(0))) status = NML_ERR_NOT_SET
      end if
    case ("entries%flag")
      if (.not. allocated(this%entries)) then
        status = NML_ERR_NOT_SET
        if (present(errmsg)) errmsg = "array storage unavailable: entries%flag"
        return
      end if
      if (present(idx)) then
        status = idx_check(idx, shape(this%entries), "entries%flag", errmsg)
        if (status /= NML_OK) return
      end if
    case ("entries")
      if (.not. allocated(this%entries)) then
        status = NML_ERR_NOT_SET
        if (present(errmsg)) errmsg = "array storage unavailable: entries"
        return
      end if
      if (present(idx)) then
        status = idx_check(idx, shape(this%entries), "entries", errmsg)
        if (status /= NML_OK) return
        if ((this%entries(idx(1), idx(2))%left == -huge(this%entries(idx(1), idx(2))%left)) .and. &
              (this%entries(idx(1), idx(2))%right == -huge(this%entries(idx(1), idx(2))%right))) then
          status = NML_ERR_NOT_SET
        else if ((this%entries(idx(1), idx(2))%left == -huge(this%entries(idx(1), idx(2))%left)) .or. &
              (this%entries(idx(1), idx(2))%right == -huge(this%entries(idx(1), idx(2))%right))) then
          status = NML_ERR_PARTLY_SET
        end if
      else
        if (all((this%entries%left == -huge(this%entries%left)) .and. &
              (this%entries%right == -huge(this%entries%right)))) then
          status = NML_ERR_NOT_SET
        else if (any((this%entries%left == -huge(this%entries%left)) .or. &
              (this%entries%right == -huge(this%entries%right)))) then
          status = NML_ERR_PARTLY_SET
        end if
      end if
    case ("known%value")
      if (present(idx)) then
        status = idx_check(idx, shape(this%known), "known%value", errmsg)
        if (status /= NML_OK) return
      end if
    case ("known")
      if (present(idx)) then
        status = idx_check(idx, shape(this%known), "known", errmsg)
        if (status /= NML_OK) return
      end if
    case ("context%value")
      if (present(idx)) then
        status = NML_ERR_INVALID_INDEX
        if (present(errmsg)) errmsg = "index not supported for 'context%value'"
        return
      end if
    case ("context")
      if (present(idx)) then
        status = NML_ERR_INVALID_INDEX
        if (present(errmsg)) errmsg = "index not supported for 'context'"
        return
      end if
    case default
      status = NML_ERR_INVALID_NAME
      if (present(errmsg)) errmsg = "unknown field: " // trim(name)
    end select
    if (status == NML_ERR_NOT_SET .and. present(errmsg)) then
      if (len_trim(errmsg) == 0) errmsg = "field not set: " // trim(name)
    end if
  end function nml_records_is_set

  !> \brief Obtain the item presence mask with one field-name dispatch
  integer function nml_records_set_mask__rank__1(this, name, mask, errmsg) result(status)
    class(nml_records_t), intent(in) :: this !< namelist instance
    character(len=*), intent(in) :: name !< field or derived component path
    logical, allocatable, intent(out) :: mask(:) !< item presence
    character(len=*), intent(out), optional :: errmsg !< error message for non-OK status values
    integer :: idx__1

    status = NML_OK
    if (present(errmsg)) errmsg = ""
    if (.not. this%is_configured) then
      status = NML_ERR_NOT_SET
      if (present(errmsg)) errmsg = "namelist not configured; call set or from_file"
      return
    end if
    select case (to_lower(trim(name)))
    case ("entries%left")
      status = NML_ERR_INVALID_INDEX
      if (present(errmsg)) errmsg = "mask rank mismatch for 'entries%left'"
    case ("entries%right")
      status = NML_ERR_INVALID_INDEX
      if (present(errmsg)) errmsg = "mask rank mismatch for 'entries%right'"
    case ("entries%note")
      status = NML_ERR_INVALID_INDEX
      if (present(errmsg)) errmsg = "mask rank mismatch for 'entries%note'"
    case ("entries%flag")
      status = NML_ERR_INVALID_INDEX
      if (present(errmsg)) errmsg = "mask rank mismatch for 'entries%flag'"
    case ("entries")
      status = NML_ERR_INVALID_INDEX
      if (present(errmsg)) errmsg = "mask rank mismatch for 'entries'"
    case ("known%value")
      allocate(mask( &
        size(this%known, 1)))
      mask = .true.
    case ("known")
      allocate(mask( &
        size(this%known, 1)))
      mask = .true.
    case ("context%value")
      status = NML_ERR_INVALID_INDEX
      if (present(errmsg)) errmsg = "array query not supported for scalar: context%value"
    case ("context")
      status = NML_ERR_INVALID_INDEX
      if (present(errmsg)) errmsg = "array query not supported for scalar: context"
    case default
      status = NML_ERR_INVALID_NAME
      if (present(errmsg)) errmsg = "unknown field: " // trim(name)
    end select
  end function nml_records_set_mask__rank__1

  !> \brief Obtain the item presence mask with one field-name dispatch
  integer function nml_records_set_mask__rank__2(this, name, mask, errmsg) result(status)
    class(nml_records_t), intent(in) :: this !< namelist instance
    character(len=*), intent(in) :: name !< field or derived component path
    logical, allocatable, intent(out) :: mask(:, :) !< item presence
    character(len=*), intent(out), optional :: errmsg !< error message for non-OK status values
    integer :: idx__1
    integer :: idx__2

    status = NML_OK
    if (present(errmsg)) errmsg = ""
    if (.not. this%is_configured) then
      status = NML_ERR_NOT_SET
      if (present(errmsg)) errmsg = "namelist not configured; call set or from_file"
      return
    end if
    select case (to_lower(trim(name)))
    case ("entries%left")
      if (.not. allocated(this%entries)) then
        status = NML_ERR_NOT_SET
        if (present(errmsg)) errmsg = "array storage unavailable: entries%left"
        return
      end if
      allocate(mask( &
        size(this%entries, 1), &
        size(this%entries, 2)))
      do idx__2 = 1, size(this%entries, 2)
        do idx__1 = 1, size(this%entries, 1)
          if (this%entries(idx__1, idx__2)%left == -huge(this%entries(idx__1, idx__2)%left)) then
            mask(idx__1, idx__2) = .false.
          else
            mask(idx__1, idx__2) = .true.
          end if
        end do
      end do
    case ("entries%right")
      if (.not. allocated(this%entries)) then
        status = NML_ERR_NOT_SET
        if (present(errmsg)) errmsg = "array storage unavailable: entries%right"
        return
      end if
      allocate(mask( &
        size(this%entries, 1), &
        size(this%entries, 2)))
      do idx__2 = 1, size(this%entries, 2)
        do idx__1 = 1, size(this%entries, 1)
          if (this%entries(idx__1, idx__2)%right == -huge(this%entries(idx__1, idx__2)%right)) then
            mask(idx__1, idx__2) = .false.
          else
            mask(idx__1, idx__2) = .true.
          end if
        end do
      end do
    case ("entries%note")
      if (.not. allocated(this%entries)) then
        status = NML_ERR_NOT_SET
        if (present(errmsg)) errmsg = "array storage unavailable: entries%note"
        return
      end if
      allocate(mask( &
        size(this%entries, 1), &
        size(this%entries, 2)))
      do idx__2 = 1, size(this%entries, 2)
        do idx__1 = 1, size(this%entries, 1)
          if (this%entries(idx__1, idx__2)%note == achar(0)) then
            mask(idx__1, idx__2) = .false.
          else
            mask(idx__1, idx__2) = .true.
          end if
        end do
      end do
    case ("entries%flag")
      if (.not. allocated(this%entries)) then
        status = NML_ERR_NOT_SET
        if (present(errmsg)) errmsg = "array storage unavailable: entries%flag"
        return
      end if
      allocate(mask( &
        size(this%entries, 1), &
        size(this%entries, 2)))
      mask = .true.
    case ("entries")
      if (.not. allocated(this%entries)) then
        status = NML_ERR_NOT_SET
        if (present(errmsg)) errmsg = "array storage unavailable: entries"
        return
      end if
      allocate(mask( &
        size(this%entries, 1), &
        size(this%entries, 2)))
      do idx__2 = 1, size(this%entries, 2)
        do idx__1 = 1, size(this%entries, 1)
          if ((this%entries(idx__1, idx__2)%left == -huge(this%entries(idx__1, idx__2)%left)) .and. &
              (this%entries(idx__1, idx__2)%right == -huge(this%entries(idx__1, idx__2)%right))) then
            mask(idx__1, idx__2) = .false.
          else
            if ((this%entries(idx__1, idx__2)%left == -huge(this%entries(idx__1, idx__2)%left)) .or. &
                (this%entries(idx__1, idx__2)%right == -huge(this%entries(idx__1, idx__2)%right))) then
              status = NML_ERR_PARTLY_SET
              if (present(errmsg)) errmsg = "derived array element partly set: entries"
              deallocate(mask)
              return
            end if
            mask(idx__1, idx__2) = .true.
          end if
        end do
      end do
    case ("known%value")
      status = NML_ERR_INVALID_INDEX
      if (present(errmsg)) errmsg = "mask rank mismatch for 'known%value'"
    case ("known")
      status = NML_ERR_INVALID_INDEX
      if (present(errmsg)) errmsg = "mask rank mismatch for 'known'"
    case ("context%value")
      status = NML_ERR_INVALID_INDEX
      if (present(errmsg)) errmsg = "array query not supported for scalar: context%value"
    case ("context")
      status = NML_ERR_INVALID_INDEX
      if (present(errmsg)) errmsg = "array query not supported for scalar: context"
    case default
      status = NML_ERR_INVALID_NAME
      if (present(errmsg)) errmsg = "unknown field: " // trim(name)
    end select
  end function nml_records_set_mask__rank__2

  !> \brief Determine the smallest complete populated prefix starting at index 1
  integer function nml_records_filled_shape(this, name, filled, errmsg) result(status)
    class(nml_records_t), intent(in) :: this !< namelist instance
    character(len=*), intent(in) :: name !< field or derived component path
    integer, intent(out) :: filled(:) !< prefix extents, retained when the prefix has holes
    character(len=*), intent(out), optional :: errmsg !< error message for non-OK status values
    integer :: idx__1
    integer :: idx__2

    filled = 0
    status = NML_OK
    if (present(errmsg)) errmsg = ""
    if (.not. this%is_configured) then
      status = NML_ERR_NOT_SET
      if (present(errmsg)) errmsg = "namelist not configured; call set or from_file"
      return
    end if
    select case (to_lower(trim(name)))
    case ("entries%left")
      if (size(filled) /= 2) then
        status = NML_ERR_INVALID_INDEX
        if (present(errmsg)) errmsg = "shape rank mismatch for 'entries%left'"
        return
      end if
      if (.not. allocated(this%entries)) then
        status = NML_ERR_NOT_SET
        if (present(errmsg)) errmsg = "array storage unavailable: entries%left"
        return
      end if
      do idx__2 = 1, size(this%entries, 2)
        do idx__1 = 1, size(this%entries, 1)
          if (this%entries(idx__1, idx__2)%left == -huge(this%entries(idx__1, idx__2)%left)) cycle
          if (idx__1 > filled(1)) filled(1) = idx__1
          if (idx__2 > filled(2)) filled(2) = idx__2
        end do
      end do
      do idx__2 = 1, filled(2)
        do idx__1 = 1, filled(1)
          if (this%entries(idx__1, idx__2)%left == -huge(this%entries(idx__1, idx__2)%left)) then
            status = NML_ERR_PARTLY_SET
            if (present(errmsg)) errmsg = "array partly set: entries%left"
            return
          end if
        end do
      end do
    case ("entries%right")
      if (size(filled) /= 2) then
        status = NML_ERR_INVALID_INDEX
        if (present(errmsg)) errmsg = "shape rank mismatch for 'entries%right'"
        return
      end if
      if (.not. allocated(this%entries)) then
        status = NML_ERR_NOT_SET
        if (present(errmsg)) errmsg = "array storage unavailable: entries%right"
        return
      end if
      do idx__2 = 1, size(this%entries, 2)
        do idx__1 = 1, size(this%entries, 1)
          if (this%entries(idx__1, idx__2)%right == -huge(this%entries(idx__1, idx__2)%right)) cycle
          if (idx__1 > filled(1)) filled(1) = idx__1
          if (idx__2 > filled(2)) filled(2) = idx__2
        end do
      end do
      do idx__2 = 1, filled(2)
        do idx__1 = 1, filled(1)
          if (this%entries(idx__1, idx__2)%right == -huge(this%entries(idx__1, idx__2)%right)) then
            status = NML_ERR_PARTLY_SET
            if (present(errmsg)) errmsg = "array partly set: entries%right"
            return
          end if
        end do
      end do
    case ("entries%note")
      if (size(filled) /= 2) then
        status = NML_ERR_INVALID_INDEX
        if (present(errmsg)) errmsg = "shape rank mismatch for 'entries%note'"
        return
      end if
      if (.not. allocated(this%entries)) then
        status = NML_ERR_NOT_SET
        if (present(errmsg)) errmsg = "array storage unavailable: entries%note"
        return
      end if
      do idx__2 = 1, size(this%entries, 2)
        do idx__1 = 1, size(this%entries, 1)
          if (this%entries(idx__1, idx__2)%note == achar(0)) cycle
          if (idx__1 > filled(1)) filled(1) = idx__1
          if (idx__2 > filled(2)) filled(2) = idx__2
        end do
      end do
      do idx__2 = 1, filled(2)
        do idx__1 = 1, filled(1)
          if (this%entries(idx__1, idx__2)%note == achar(0)) then
            status = NML_ERR_PARTLY_SET
            if (present(errmsg)) errmsg = "array partly set: entries%note"
            return
          end if
        end do
      end do
    case ("entries%flag")
      if (size(filled) /= 2) then
        status = NML_ERR_INVALID_INDEX
        if (present(errmsg)) errmsg = "shape rank mismatch for 'entries%flag'"
        return
      end if
      if (.not. allocated(this%entries)) then
        status = NML_ERR_NOT_SET
        if (present(errmsg)) errmsg = "array storage unavailable: entries%flag"
        return
      end if
      filled(1) = size(this%entries, 1)
      filled(2) = size(this%entries, 2)
    case ("entries")
      if (size(filled) /= 2) then
        status = NML_ERR_INVALID_INDEX
        if (present(errmsg)) errmsg = "shape rank mismatch for 'entries'"
        return
      end if
      if (.not. allocated(this%entries)) then
        status = NML_ERR_NOT_SET
        if (present(errmsg)) errmsg = "array storage unavailable: entries"
        return
      end if
      do idx__2 = 1, size(this%entries, 2)
        do idx__1 = 1, size(this%entries, 1)
          if ((this%entries(idx__1, idx__2)%left == -huge(this%entries(idx__1, idx__2)%left)) .and. &
              (this%entries(idx__1, idx__2)%right == -huge(this%entries(idx__1, idx__2)%right))) cycle
          if ((this%entries(idx__1, idx__2)%left == -huge(this%entries(idx__1, idx__2)%left)) .or. &
                (this%entries(idx__1, idx__2)%right == -huge(this%entries(idx__1, idx__2)%right))) then
            status = NML_ERR_PARTLY_SET
            if (present(errmsg)) errmsg = "derived array element partly set: entries"
            filled = 0
            return
          end if
          if (idx__1 > filled(1)) filled(1) = idx__1
          if (idx__2 > filled(2)) filled(2) = idx__2
        end do
      end do
      do idx__2 = 1, filled(2)
        do idx__1 = 1, filled(1)
          if ((this%entries(idx__1, idx__2)%left == -huge(this%entries(idx__1, idx__2)%left)) .and. &
              (this%entries(idx__1, idx__2)%right == -huge(this%entries(idx__1, idx__2)%right))) then
            status = NML_ERR_PARTLY_SET
            if (present(errmsg)) errmsg = "array partly set: entries"
            return
          end if
        end do
      end do
    case ("known%value")
      if (size(filled) /= 1) then
        status = NML_ERR_INVALID_INDEX
        if (present(errmsg)) errmsg = "shape rank mismatch for 'known%value'"
        return
      end if
      filled(1) = size(this%known, 1)
    case ("known")
      if (size(filled) /= 1) then
        status = NML_ERR_INVALID_INDEX
        if (present(errmsg)) errmsg = "shape rank mismatch for 'known'"
        return
      end if
      filled(1) = size(this%known, 1)
    case ("context%value")
      status = NML_ERR_INVALID_INDEX
      if (present(errmsg)) errmsg = "array query not supported for scalar: context%value"
    case ("context")
      status = NML_ERR_INVALID_INDEX
      if (present(errmsg)) errmsg = "array query not supported for scalar: context"
    case default
      status = NML_ERR_INVALID_NAME
      if (present(errmsg)) errmsg = "unknown field: " // trim(name)
    end select
  end function nml_records_filled_shape

  !> \brief Validate required values and constraints
  integer function nml_records_is_valid(this, errmsg) result(status)
    class(nml_records_t), intent(in) :: this !< namelist instance
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
    istat = this%is_set("entries", errmsg=errmsg)
    if (istat == NML_ERR_NOT_SET) then
      status = NML_ERR_REQUIRED
      if (present(errmsg)) then
        if (len_trim(errmsg) == 0) then
          errmsg = "field not set: entries"
        end if
        errmsg = "required " // trim(errmsg)
      end if
      return
    end if
    if (istat /= NML_OK) then
      status = istat
      return
    end if
  end function nml_records_is_valid

end module nml_records
