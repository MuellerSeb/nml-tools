!> \file nml_long.f90
!> \copydoc nml_long_nnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnn

!> \brief long_nnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnn
!> \details long_nnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnn
module nml_long_nnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnn
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
    MaX, &
    ShApE, &
    NML_ERR_PARTLY_SET

  implicit none

  ! default values
  logical, parameter, public :: flags__default = .false.

  !> \class nml_long_nnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnn_t
  !> \brief long_nnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnn
  !> \details long_nnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnn
  type, public :: nml_long_nnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnn_t
    logical :: is_configured = .false. !< whether the namelist has been configured
    integer, dimension(MaX) :: values !< values
    logical, dimension(2, ShApE) :: flags !< flags
  contains
    procedure :: init => nml_long_nnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnn_init
    procedure :: from_file => nml_long_nnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnn_from_file
    procedure :: set => nml_long_nnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnn_set
    procedure :: is_set => nml_long_nnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnn_is_set
    procedure, private :: set_mask__rank__1 => nml_long_nnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnn_a932a767bc
    procedure, private :: set_mask__rank__2 => nml_long_nnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnn_ebe2c9119d
    generic :: set_mask => &
      set_mask__rank__1, &
      set_mask__rank__2
    procedure :: filled_shape => nml_long_nnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnn_4b0a62caab
    procedure :: is_valid => nml_long_nnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnn_is_valid
  end type nml_long_nnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnn_t

contains

  !> \brief Initialize defaults and sentinels for long_nnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnn
  integer function nml_long_nnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnn_init(this, errmsg) result(status)
    class(nml_long_nnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnn_t), intent(inout) :: this !< namelist instance
    character(len=*), intent(out), optional :: errmsg !< error message for non-OK status values

    status = NML_OK
    if (present(errmsg)) errmsg = ""
    this%is_configured = .false.

    ! sentinel values for required/optional parameters
    this%values = -huge(this%values) ! sentinel for optional integer array
    ! default values
    this%flags = flags__default
  end function nml_long_nnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnn_init


  !> \brief Read long_nnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnn namelist from file
  integer function nml_long_nnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnn_from_file(this, file, errmsg) result(status)
    class(nml_long_nnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnn_t), intent(inout) :: this !< namelist instance
    character(len=*), intent(in) :: file !< path to namelist file
    character(len=*), intent(out), optional :: errmsg !< error message for non-OK status values
    ! namelist variables
    integer, dimension(MaX) :: values
    logical, dimension(2, ShApE) :: flags
    ! locals
    type(nml_file_t) :: nml
    integer :: iostat
    integer :: close_status
    character(len=nml_line_buffer) :: iomsg

    namelist /long_nnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnn/ &
      values, &
      flags

    status = this%init(errmsg=errmsg)
    if (status /= NML_OK) return
    values = this%values
    flags = this%flags

    status = nml%open(file, errmsg=errmsg)
    if (status /= NML_OK) return

    status = nml%find("long_nnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnn", errmsg=errmsg)
    if (status /= NML_OK) then
      if (status == NML_ERR_NML_NOT_FOUND) then
        close_status = nml%close(errmsg=errmsg)
        if (close_status /= NML_OK) then
          status = close_status
          return
        end if
        this%is_configured = .true.
        status = NML_OK
        return
      end if
      close_status = nml%close()
      return
    end if

    ! read namelist
    read(nml%unit, nml=long_nnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnn, iostat=iostat, iomsg=iomsg)
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
    this%values = values
    this%flags = flags

    ! mark as configured
    this%is_configured = .true.
    status = NML_OK
  end function nml_long_nnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnn_from_file

  !> \brief Set long_nnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnn values
  integer function nml_long_nnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnn_set(this, &
    values, &
    flags, &
    errmsg) result(status)

    class(nml_long_nnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnn_t), intent(inout) :: this !< namelist instance
    character(len=*), intent(out), optional :: errmsg !< error message for non-OK status values
    integer, dimension(:), intent(in), optional :: values !< values
    logical, dimension(:, :), intent(in), optional :: flags !< flags

    status = this%init(errmsg=errmsg)
    if (status /= NML_OK) return

    ! required parameters
    ! override with provided values
    if (present(values)) then
      if (size(values, 1) > size(this%values, 1)) then
        status = NML_ERR_INVALID_INDEX
        if (present(errmsg)) errmsg = "dimension 1 exceeds bounds for 'values'"
        return
      end if
      this%values(1:size(values, 1)) = values
    end if
    if (present(flags)) then
      if (size(flags, 1) > size(this%flags, 1)) then
        status = NML_ERR_INVALID_INDEX
        if (present(errmsg)) errmsg = "dimension 1 exceeds bounds for 'flags'"
        return
      end if
      if (size(flags, 2) > size(this%flags, 2)) then
        status = NML_ERR_INVALID_INDEX
        if (present(errmsg)) errmsg = "dimension 2 exceeds bounds for 'flags'"
        return
      end if
      this%flags(1:size(flags, 1), 1:size(flags, 2)) = flags
    end if

    ! mark as configured
    this%is_configured = .true.
    status = NML_OK
  end function nml_long_nnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnn_set

  !> \brief Check whether a namelist value was set
  integer function nml_long_nnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnn_is_set(this, name, idx, errmsg) result(status)
    class(nml_long_nnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnn_t), intent(in) :: this !< namelist instance
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
    case ("values")
      if (present(idx)) then
        status = idx_check(idx, shape(this%values), "values", errmsg)
        if (status /= NML_OK) return
        if (this%values(idx(1)) == -huge(this%values(idx(1)))) status = NML_ERR_NOT_SET
      else
        if (all(this%values == -huge(this%values))) status = NML_ERR_NOT_SET
      end if
    case ("flags")
      if (present(idx)) then
        status = idx_check(idx, shape(this%flags), "flags", errmsg)
        if (status /= NML_OK) return
      end if
    case default
      status = NML_ERR_INVALID_NAME
      if (present(errmsg)) errmsg = "unknown field: " // trim(name)
    end select
    if (status == NML_ERR_NOT_SET .and. present(errmsg)) then
      if (len_trim(errmsg) == 0) errmsg = "field not set: " // trim(name)
    end if
  end function nml_long_nnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnn_is_set

  !> \brief Obtain the item presence mask with one field-name dispatch
  integer function nml_long_nnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnn_a932a767bc(this, name, mask, errmsg) result(status)
    class(nml_long_nnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnn_t), intent(in) :: this !< namelist instance
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
    case ("values")
      allocate(mask( &
        size(this%values, 1)))
      do idx__1 = 1, size(this%values, 1)
        if (this%values(idx__1) == -huge(this%values(idx__1))) then
          mask(idx__1) = .false.
        else
          mask(idx__1) = .true.
        end if
      end do
    case ("flags")
      status = NML_ERR_INVALID_INDEX
      if (present(errmsg)) errmsg = "mask rank mismatch for 'flags'"
    case default
      status = NML_ERR_INVALID_NAME
      if (present(errmsg)) errmsg = "unknown field: " // trim(name)
    end select
  end function nml_long_nnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnn_a932a767bc

  !> \brief Obtain the item presence mask with one field-name dispatch
  integer function nml_long_nnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnn_ebe2c9119d(this, name, mask, errmsg) result(status)
    class(nml_long_nnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnn_t), intent(in) :: this !< namelist instance
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
    case ("values")
      status = NML_ERR_INVALID_INDEX
      if (present(errmsg)) errmsg = "mask rank mismatch for 'values'"
    case ("flags")
      allocate(mask( &
        size(this%flags, 1), &
        size(this%flags, 2)))
      mask = .true.
    case default
      status = NML_ERR_INVALID_NAME
      if (present(errmsg)) errmsg = "unknown field: " // trim(name)
    end select
  end function nml_long_nnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnn_ebe2c9119d

  !> \brief Determine the smallest complete populated prefix starting at index 1
  integer function nml_long_nnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnn_4b0a62caab(this, name, filled, errmsg) result(status)
    class(nml_long_nnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnn_t), intent(in) :: this !< namelist instance
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
    case ("values")
      if (size(filled) /= 1) then
        status = NML_ERR_INVALID_INDEX
        if (present(errmsg)) errmsg = "shape rank mismatch for 'values'"
        return
      end if
      do idx__1 = 1, size(this%values, 1)
        if (this%values(idx__1) == -huge(this%values(idx__1))) cycle
        if (idx__1 > filled(1)) filled(1) = idx__1
      end do
      do idx__1 = 1, filled(1)
        if (this%values(idx__1) == -huge(this%values(idx__1))) then
          status = NML_ERR_PARTLY_SET
          if (present(errmsg)) errmsg = "array partly set: values"
          return
        end if
      end do
    case ("flags")
      if (size(filled) /= 2) then
        status = NML_ERR_INVALID_INDEX
        if (present(errmsg)) errmsg = "shape rank mismatch for 'flags'"
        return
      end if
      filled(1) = size(this%flags, 1)
      filled(2) = size(this%flags, 2)
    case default
      status = NML_ERR_INVALID_NAME
      if (present(errmsg)) errmsg = "unknown field: " // trim(name)
    end select
  end function nml_long_nnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnn_4b0a62caab

  !> \brief Validate required values and constraints
  integer function nml_long_nnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnn_is_valid(this, errmsg) result(status)
    class(nml_long_nnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnn_t), intent(in) :: this !< namelist instance
    character(len=*), intent(out), optional :: errmsg !< error message for non-OK status values
    integer :: istat

    status = NML_OK
    if (present(errmsg)) errmsg = ""
    if (.not. this%is_configured) then
      status = NML_ERR_NOT_SET
      if (present(errmsg)) errmsg = "namelist not configured; call set or from_file"
      return
    end if

  end function nml_long_nnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnn_is_valid

end module nml_long_nnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnn
