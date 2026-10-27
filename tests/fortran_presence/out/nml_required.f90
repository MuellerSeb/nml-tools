!> \file nml_required.f90
!> \copydoc nml_required

!> \brief required
!> \details required
module nml_required
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
    NML_ERR_PARTLY_SET

  implicit none

  !> \class nml_required_t
  !> \brief required
  !> \details required
  type, public :: nml_required_t
    logical :: is_configured = .false. !< whether the namelist has been configured
    integer, dimension(3) :: values !< values
  contains
    procedure :: init => nml_required_init
    procedure :: from_file => nml_required_from_file
    procedure :: set => nml_required_set
    procedure :: is_set => nml_required_is_set
    procedure, private :: set_mask__rank__1 => nml_required_set_mask__rank__1
    generic :: set_mask => &
      set_mask__rank__1
    procedure :: filled_shape => nml_required_filled_shape
    procedure :: is_valid => nml_required_is_valid
  end type nml_required_t

contains

  !> \brief Initialize defaults and sentinels for required
  integer function nml_required_init(this, errmsg) result(status)
    class(nml_required_t), intent(inout) :: this !< namelist instance
    character(len=*), intent(out), optional :: errmsg !< error message for non-OK status values

    status = NML_OK
    if (present(errmsg)) errmsg = ""
    this%is_configured = .false.

    ! sentinel values for required/optional parameters
    this%values = -huge(this%values) ! sentinel for required integer array
  end function nml_required_init


  !> \brief Read required namelist from file
  integer function nml_required_from_file(this, file, errmsg) result(status)
    class(nml_required_t), intent(inout) :: this !< namelist instance
    character(len=*), intent(in) :: file !< path to namelist file
    character(len=*), intent(out), optional :: errmsg !< error message for non-OK status values
    ! namelist variables
    integer, dimension(3) :: values
    ! locals
    type(nml_file_t) :: nml
    integer :: iostat
    integer :: close_status
    character(len=nml_line_buffer) :: iomsg

    namelist /required/ &
      values

    status = this%init(errmsg=errmsg)
    if (status /= NML_OK) return
    values = this%values

    status = nml%open(file, errmsg=errmsg)
    if (status /= NML_OK) return

    status = nml%find("required", errmsg=errmsg)
    if (status /= NML_OK) then
      close_status = nml%close()
      return
    end if

    ! read namelist
    read(nml%unit, nml=required, iostat=iostat, iomsg=iomsg)
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

    ! mark as configured
    this%is_configured = .true.
    status = NML_OK
  end function nml_required_from_file

  !> \brief Set required values
  integer function nml_required_set(this, &
    values, &
    errmsg) result(status)

    class(nml_required_t), intent(inout) :: this !< namelist instance
    character(len=*), intent(out), optional :: errmsg !< error message for non-OK status values
    integer, dimension(:), intent(in) :: values !< values
    integer :: &
      lb__1, &
      ub__1

    status = this%init(errmsg=errmsg)
    if (status /= NML_OK) return

    ! required parameters
    if (size(values, 1) > size(this%values, 1)) then
      status = NML_ERR_INVALID_INDEX
      if (present(errmsg)) errmsg = "dimension 1 exceeds bounds for 'values'"
      return
    end if
    lb__1 = lbound(this%values, 1)
    ub__1 = lb__1 + size(values, 1) - 1
    this%values(lb__1:ub__1) = values

    ! mark as configured
    this%is_configured = .true.
    status = NML_OK
  end function nml_required_set

  !> \brief Check whether a namelist value was set
  integer function nml_required_is_set(this, name, idx, errmsg) result(status)
    class(nml_required_t), intent(in) :: this !< namelist instance
    character(len=*), intent(in) :: name !< field name
    integer, intent(in), optional :: idx(:) !< optional field index values
    character(len=*), intent(out), optional :: errmsg !< error message for non-OK status values

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
        status = idx_check(idx, lbound(this%values), &
          ubound(this%values), "values", errmsg)
        if (status /= NML_OK) return
        if (this%values(idx(1)) == -huge(this%values(idx(1)))) then
          status = NML_ERR_NOT_SET
        end if
      else
        if (all(this%values == -huge(this%values))) then
          status = NML_ERR_NOT_SET
        end if
      end if
    case default
      status = NML_ERR_INVALID_NAME
      if (present(errmsg)) errmsg = "unknown field: " // trim(name)
    end select
    if (status == NML_ERR_NOT_SET .and. present(errmsg)) then
      if (len_trim(errmsg) == 0) errmsg = "field not set: " // trim(name)
    end if
  end function nml_required_is_set

  !> \brief Obtain the item presence mask with one field-name dispatch
  integer function nml_required_set_mask__rank__1(this, name, mask, errmsg) result(status)
    class(nml_required_t), intent(in) :: this !< namelist instance
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

    case default
      status = NML_ERR_INVALID_NAME
      if (present(errmsg)) errmsg = "unknown field: " // trim(name)
    end select
  end function nml_required_set_mask__rank__1

  !> \brief Determine the smallest complete lower-bound-anchored populated prefix
  integer function nml_required_filled_shape(this, name, filled, errmsg) result(status)
    class(nml_required_t), intent(in) :: this !< namelist instance
    character(len=*), intent(in) :: name !< field or derived component path
    integer, intent(out) :: filled(:) !< prefix extents, retained when the prefix has holes
    character(len=*), intent(out), optional :: errmsg !< error message for non-OK status values
    integer :: idx__1

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

    case default
      status = NML_ERR_INVALID_NAME
      if (present(errmsg)) errmsg = "unknown field: " // trim(name)
    end select
  end function nml_required_filled_shape

  !> \brief Validate required values and constraints
  integer function nml_required_is_valid(this, errmsg) result(status)
    class(nml_required_t), intent(in) :: this !< namelist instance
    character(len=*), intent(out), optional :: errmsg !< error message for non-OK status values
    integer :: istat

    status = NML_OK
    if (present(errmsg)) errmsg = ""
    if (.not. this%is_configured) then
      status = NML_ERR_NOT_SET
      if (present(errmsg)) errmsg = "namelist not configured; call set or from_file"
      return
    end if

    ! required arrays
    if (all(this%values(:) == -huge(this%values(:)))) then
      status = NML_ERR_REQUIRED
      if (present(errmsg)) errmsg = "required field not set: values"
      return
    end if
    if (any(this%values(:) == -huge(this%values(:)))) then
      status = NML_ERR_PARTLY_SET
      if (present(errmsg)) errmsg = "array partly set: values"
      return
    end if
  end function nml_required_is_valid

end module nml_required
