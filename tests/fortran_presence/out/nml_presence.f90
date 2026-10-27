!> \file nml_presence.f90
!> \copydoc nml_presence

!> \brief presence
!> \details presence
module nml_presence
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
    n__default, &
    NML_ERR_PARTLY_SET
  use ieee_arithmetic, only: ieee_value, ieee_quiet_nan, ieee_is_nan

  implicit none

  ! default values
  integer, parameter, public :: scalar__default = 0
  integer, parameter, public :: defaulted__default = 7
  logical, parameter, public :: flags__default = .false.

  ! bounds values
  real, parameter, public :: matrix__min = 0.0

  !> \class nml_presence_t
  !> \brief presence
  !> \details presence
  type, public :: nml_presence_t
    logical :: is_configured = .false. !< whether the namelist has been configured
    integer :: n = n__default !< runtime dimension for n
    integer :: scalar !< scalar
    integer, dimension(MaX) :: counts !< counts
    real, dimension(3, 4) :: matrix !< matrix
    integer, dimension(2, 2, 3) :: cube !< cube
    character(len=4), dimension(3) :: labels !< labels
    integer, dimension(ShApE) :: defaulted !< defaulted
    logical, dimension(3) :: flags !< flags
    real, allocatable, dimension(:, :) :: runtime !< runtime
  contains
    procedure :: init => nml_presence_init
    procedure :: set_dims => nml_presence_set_dims
    procedure :: from_file => nml_presence_from_file
    procedure :: set => nml_presence_set
    procedure :: is_set => nml_presence_is_set
    procedure, private :: set_mask__rank__1 => nml_presence_set_mask__rank__1
    procedure, private :: set_mask__rank__2 => nml_presence_set_mask__rank__2
    procedure, private :: set_mask__rank__3 => nml_presence_set_mask__rank__3
    generic :: set_mask => &
      set_mask__rank__1, &
      set_mask__rank__2, &
      set_mask__rank__3
    procedure :: filled_shape => nml_presence_filled_shape
    procedure :: is_valid => nml_presence_is_valid
  end type nml_presence_t

contains

  !> \brief Check whether a value is within bounds
  elemental logical function matrix__in_bounds(val, allow_missing) result(in_bounds)
    real, intent(in) :: val !< value to check
    logical, intent(in), optional :: allow_missing !< allow sentinel values as valid

    if (present(allow_missing)) then
      if (allow_missing) then
        if (ieee_is_nan(val)) then
          in_bounds = .true.
          return
        end if
      end if
    end if

    in_bounds = .true.
    if (val < matrix__min) in_bounds = .false.
  end function matrix__in_bounds

  !> \brief Initialize defaults and sentinels for presence
  integer function nml_presence_init(this, errmsg) result(status)
    class(nml_presence_t), intent(inout) :: this !< namelist instance
    character(len=*), intent(out), optional :: errmsg !< error message for non-OK status values

    status = NML_OK
    if (present(errmsg)) errmsg = ""
    this%is_configured = .false.

    ! allocate runtime-sized fields
    if (allocated(this%runtime)) deallocate(this%runtime)
    allocate(this%runtime(this%n, 2))

    ! sentinel values for required/optional parameters
    this%counts = -huge(this%counts) ! sentinel for optional integer array
    this%matrix = ieee_value(this%matrix, ieee_quiet_nan) ! sentinel for optional real array
    this%cube = -huge(this%cube) ! sentinel for optional integer array
    this%labels = achar(0) ! sentinel for optional string array
    this%runtime = ieee_value(this%runtime, ieee_quiet_nan) ! sentinel for optional real array
    ! default values
    this%scalar = scalar__default
    this%defaulted = defaulted__default
    this%flags = flags__default
  end function nml_presence_init

  !> \brief Reset runtime dimensions for presence
  integer function nml_presence_set_dims(this, &
    n, &
    errmsg) result(status)
    class(nml_presence_t), intent(inout) :: this !< namelist instance
    integer, intent(in), optional :: n !< runtime dimension override for n
    integer :: candidate__n
    character(len=*), intent(out), optional :: errmsg !< error message for non-OK status values

    status = NML_OK
    if (present(errmsg)) errmsg = ""
    if (present(n)) then
      candidate__n = n
    else
      candidate__n = n__default
    end if
    if (candidate__n <= 0) then
      status = NML_ERR_INVALID_INDEX
      if (present(errmsg)) errmsg = "dimension 'n' must be positive"
      return
    end if
    this%n = candidate__n

    ! deallocate runtime-sized fields; init/set/from_file allocate them again
    if (allocated(this%runtime)) deallocate(this%runtime)
    this%is_configured = .false.
  end function nml_presence_set_dims


  !> \brief Read presence namelist from file
  integer function nml_presence_from_file(this, file, errmsg) result(status)
    class(nml_presence_t), intent(inout) :: this !< namelist instance
    character(len=*), intent(in) :: file !< path to namelist file
    character(len=*), intent(out), optional :: errmsg !< error message for non-OK status values
    ! namelist variables
    integer :: scalar
    integer, dimension(MaX) :: counts
    real, dimension(3, 4) :: matrix
    integer, dimension(2, 2, 3) :: cube
    character(len=4), dimension(3) :: labels
    integer, dimension(ShApE) :: defaulted
    logical, dimension(3) :: flags
    real, allocatable, dimension(:, :) :: runtime
    ! locals
    type(nml_file_t) :: nml
    integer :: iostat
    integer :: close_status
    character(len=nml_line_buffer) :: iomsg

    namelist /presence/ &
      scalar, &
      counts, &
      matrix, &
      cube, &
      labels, &
      defaulted, &
      flags, &
      runtime

    status = this%init(errmsg=errmsg)
    if (status /= NML_OK) return
    ! allocate local namelist variables matching runtime-sized fields
    if (allocated(runtime)) deallocate(runtime)
    allocate(runtime(this%n, 2))
    scalar = this%scalar
    counts = this%counts
    matrix = this%matrix
    cube = this%cube
    labels = this%labels
    defaulted = this%defaulted
    flags = this%flags
    runtime = this%runtime

    status = nml%open(file, errmsg=errmsg)
    if (status /= NML_OK) return

    status = nml%find("presence", errmsg=errmsg)
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
    read(nml%unit, nml=presence, iostat=iostat, iomsg=iomsg)
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
    this%scalar = scalar
    this%counts = counts
    this%matrix = matrix
    this%cube = cube
    this%labels = labels
    this%defaulted = defaulted
    this%flags = flags
    this%runtime = runtime

    ! mark as configured
    this%is_configured = .true.
    status = NML_OK
  end function nml_presence_from_file

  !> \brief Set presence values
  integer function nml_presence_set(this, &
    scalar, &
    counts, &
    matrix, &
    cube, &
    labels, &
    defaulted, &
    flags, &
    runtime, &
    errmsg) result(status)

    class(nml_presence_t), intent(inout) :: this !< namelist instance
    character(len=*), intent(out), optional :: errmsg !< error message for non-OK status values
    integer, intent(in), optional :: scalar !< scalar
    integer, dimension(:), intent(in), optional :: counts !< counts
    real, dimension(:, :), intent(in), optional :: matrix !< matrix
    integer, dimension(:, :, :), intent(in), optional :: cube !< cube
    character(len=*), dimension(:), intent(in), optional :: labels !< labels
    integer, dimension(:), intent(in), optional :: defaulted !< defaulted
    logical, dimension(:), intent(in), optional :: flags !< flags
    real, dimension(:, :), intent(in), optional :: runtime !< runtime
    integer :: &
      lb__1, &
      lb__2, &
      lb__3, &
      ub__1, &
      ub__2, &
      ub__3

    status = this%init(errmsg=errmsg)
    if (status /= NML_OK) return

    ! required parameters
    ! override with provided values
    if (present(scalar)) this%scalar = scalar
    if (present(counts)) then
      if (size(counts, 1) > size(this%counts, 1)) then
        status = NML_ERR_INVALID_INDEX
        if (present(errmsg)) errmsg = "dimension 1 exceeds bounds for 'counts'"
        return
      end if
      lb__1 = lbound(this%counts, 1)
      ub__1 = lb__1 + size(counts, 1) - 1
      this%counts(lb__1:ub__1) = counts
    end if
    if (present(matrix)) then
      if (size(matrix, 1) > size(this%matrix, 1)) then
        status = NML_ERR_INVALID_INDEX
        if (present(errmsg)) errmsg = "dimension 1 exceeds bounds for 'matrix'"
        return
      end if
      lb__1 = lbound(this%matrix, 1)
      ub__1 = lb__1 + size(matrix, 1) - 1
      if (size(matrix, 2) > size(this%matrix, 2)) then
        status = NML_ERR_INVALID_INDEX
        if (present(errmsg)) errmsg = "dimension 2 exceeds bounds for 'matrix'"
        return
      end if
      lb__2 = lbound(this%matrix, 2)
      ub__2 = lb__2 + size(matrix, 2) - 1
      this%matrix(lb__1:ub__1, lb__2:ub__2) = matrix
    end if
    if (present(cube)) then
      if (size(cube, 1) > size(this%cube, 1)) then
        status = NML_ERR_INVALID_INDEX
        if (present(errmsg)) errmsg = "dimension 1 exceeds bounds for 'cube'"
        return
      end if
      lb__1 = lbound(this%cube, 1)
      ub__1 = lb__1 + size(cube, 1) - 1
      if (size(cube, 2) > size(this%cube, 2)) then
        status = NML_ERR_INVALID_INDEX
        if (present(errmsg)) errmsg = "dimension 2 exceeds bounds for 'cube'"
        return
      end if
      lb__2 = lbound(this%cube, 2)
      ub__2 = lb__2 + size(cube, 2) - 1
      if (size(cube, 3) > size(this%cube, 3)) then
        status = NML_ERR_INVALID_INDEX
        if (present(errmsg)) errmsg = "dimension 3 exceeds bounds for 'cube'"
        return
      end if
      lb__3 = lbound(this%cube, 3)
      ub__3 = lb__3 + size(cube, 3) - 1
      this%cube(lb__1:ub__1, lb__2:ub__2, lb__3:ub__3) = cube
    end if
    if (present(labels)) then
      if (size(labels, 1) > size(this%labels, 1)) then
        status = NML_ERR_INVALID_INDEX
        if (present(errmsg)) errmsg = "dimension 1 exceeds bounds for 'labels'"
        return
      end if
      lb__1 = lbound(this%labels, 1)
      ub__1 = lb__1 + size(labels, 1) - 1
      this%labels(lb__1:ub__1) = labels
    end if
    if (present(defaulted)) then
      if (size(defaulted, 1) > size(this%defaulted, 1)) then
        status = NML_ERR_INVALID_INDEX
        if (present(errmsg)) errmsg = "dimension 1 exceeds bounds for 'defaulted'"
        return
      end if
      lb__1 = lbound(this%defaulted, 1)
      ub__1 = lb__1 + size(defaulted, 1) - 1
      this%defaulted(lb__1:ub__1) = defaulted
    end if
    if (present(flags)) then
      if (size(flags, 1) > size(this%flags, 1)) then
        status = NML_ERR_INVALID_INDEX
        if (present(errmsg)) errmsg = "dimension 1 exceeds bounds for 'flags'"
        return
      end if
      lb__1 = lbound(this%flags, 1)
      ub__1 = lb__1 + size(flags, 1) - 1
      this%flags(lb__1:ub__1) = flags
    end if
    if (present(runtime)) then
      if (size(runtime, 1) > size(this%runtime, 1)) then
        status = NML_ERR_INVALID_INDEX
        if (present(errmsg)) errmsg = "dimension 1 exceeds bounds for 'runtime'"
        return
      end if
      lb__1 = lbound(this%runtime, 1)
      ub__1 = lb__1 + size(runtime, 1) - 1
      if (size(runtime, 2) > size(this%runtime, 2)) then
        status = NML_ERR_INVALID_INDEX
        if (present(errmsg)) errmsg = "dimension 2 exceeds bounds for 'runtime'"
        return
      end if
      lb__2 = lbound(this%runtime, 2)
      ub__2 = lb__2 + size(runtime, 2) - 1
      this%runtime(lb__1:ub__1, lb__2:ub__2) = runtime
    end if

    ! mark as configured
    this%is_configured = .true.
    status = NML_OK
  end function nml_presence_set

  !> \brief Check whether a namelist value was set
  integer function nml_presence_is_set(this, name, idx, errmsg) result(status)
    class(nml_presence_t), intent(in) :: this !< namelist instance
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
    case ("scalar")
      if (present(idx)) then
        status = NML_ERR_INVALID_INDEX
        if (present(errmsg)) errmsg = "index not supported for 'scalar'"
        return
      end if
    case ("counts")
      if (present(idx)) then
        status = idx_check(idx, lbound(this%counts), &
          ubound(this%counts), "counts", errmsg)
        if (status /= NML_OK) return
        if (this%counts(idx(1)) == -huge(this%counts(idx(1)))) then
          status = NML_ERR_NOT_SET
        end if
      else
        if (all(this%counts == -huge(this%counts))) then
          status = NML_ERR_NOT_SET
        end if
      end if
    case ("matrix")
      if (present(idx)) then
        status = idx_check(idx, lbound(this%matrix), &
          ubound(this%matrix), "matrix", errmsg)
        if (status /= NML_OK) return
        if (ieee_is_nan(this%matrix(idx(1), idx(2)))) then
          status = NML_ERR_NOT_SET
        end if
      else
        if (all(ieee_is_nan(this%matrix))) then
          status = NML_ERR_NOT_SET
        end if
      end if
    case ("cube")
      if (present(idx)) then
        status = idx_check(idx, lbound(this%cube), &
          ubound(this%cube), "cube", errmsg)
        if (status /= NML_OK) return
        if (this%cube(idx(1), idx(2), idx(3)) == -huge(this%cube(idx(1), idx(2), idx(3)))) then
          status = NML_ERR_NOT_SET
        end if
      else
        if (all(this%cube == -huge(this%cube))) then
          status = NML_ERR_NOT_SET
        end if
      end if
    case ("labels")
      if (present(idx)) then
        status = idx_check(idx, lbound(this%labels), &
          ubound(this%labels), "labels", errmsg)
        if (status /= NML_OK) return
        if (this%labels(idx(1)) == achar(0)) then
          status = NML_ERR_NOT_SET
        end if
      else
        if (all(this%labels == achar(0))) then
          status = NML_ERR_NOT_SET
        end if
      end if
    case ("defaulted")
      if (present(idx)) then
        status = idx_check(idx, lbound(this%defaulted), &
          ubound(this%defaulted), "defaulted", errmsg)
        if (status /= NML_OK) return
      else
      end if
    case ("flags")
      if (present(idx)) then
        status = idx_check(idx, lbound(this%flags), &
          ubound(this%flags), "flags", errmsg)
        if (status /= NML_OK) return
      else
      end if
    case ("runtime")
      if (.not. allocated(this%runtime)) then
        status = NML_ERR_NOT_SET
        if (present(errmsg)) errmsg = "array storage unavailable: runtime"
        return
      end if
      if (present(idx)) then
        status = idx_check(idx, lbound(this%runtime), &
          ubound(this%runtime), "runtime", errmsg)
        if (status /= NML_OK) return
        if (ieee_is_nan(this%runtime(idx(1), idx(2)))) then
          status = NML_ERR_NOT_SET
        end if
      else
        if (all(ieee_is_nan(this%runtime))) then
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
  end function nml_presence_is_set

  !> \brief Obtain the item presence mask with one field-name dispatch
  integer function nml_presence_set_mask__rank__1(this, name, mask, errmsg) result(status)
    class(nml_presence_t), intent(in) :: this !< namelist instance
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
    case ("scalar")
      status = NML_ERR_INVALID_INDEX
      if (present(errmsg)) errmsg = "array query not supported for scalar: scalar"
    case ("counts")

      allocate(mask( &
        size(this%counts, 1)))
      do idx__1 = 1, size(this%counts, 1)

        if (this%counts(idx__1) == -huge(this%counts(idx__1))) then
          mask(idx__1) = .false.
        else
          mask(idx__1) = .true.
        end if
      end do

    case ("matrix")
      status = NML_ERR_INVALID_INDEX
      if (present(errmsg)) errmsg = "mask rank mismatch for 'matrix'"
    case ("cube")
      status = NML_ERR_INVALID_INDEX
      if (present(errmsg)) errmsg = "mask rank mismatch for 'cube'"
    case ("labels")

      allocate(mask( &
        size(this%labels, 1)))
      do idx__1 = 1, size(this%labels, 1)

        if (this%labels(idx__1) == achar(0)) then
          mask(idx__1) = .false.
        else
          mask(idx__1) = .true.
        end if
      end do

    case ("defaulted")

      allocate(mask( &
        size(this%defaulted, 1)))
      mask = .true.
    case ("flags")

      allocate(mask( &
        size(this%flags, 1)))
      mask = .true.
    case ("runtime")
      status = NML_ERR_INVALID_INDEX
      if (present(errmsg)) errmsg = "mask rank mismatch for 'runtime'"
    case default
      status = NML_ERR_INVALID_NAME
      if (present(errmsg)) errmsg = "unknown field: " // trim(name)
    end select
  end function nml_presence_set_mask__rank__1

  !> \brief Obtain the item presence mask with one field-name dispatch
  integer function nml_presence_set_mask__rank__2(this, name, mask, errmsg) result(status)
    class(nml_presence_t), intent(in) :: this !< namelist instance
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
    case ("scalar")
      status = NML_ERR_INVALID_INDEX
      if (present(errmsg)) errmsg = "array query not supported for scalar: scalar"
    case ("counts")
      status = NML_ERR_INVALID_INDEX
      if (present(errmsg)) errmsg = "mask rank mismatch for 'counts'"
    case ("matrix")

      allocate(mask( &
        size(this%matrix, 1), &
        size(this%matrix, 2)))
      do idx__2 = 1, size(this%matrix, 2)
        do idx__1 = 1, size(this%matrix, 1)

          if (ieee_is_nan(this%matrix(idx__1, idx__2))) then
            mask(idx__1, idx__2) = .false.
          else
            mask(idx__1, idx__2) = .true.
          end if
        end do
      end do

    case ("cube")
      status = NML_ERR_INVALID_INDEX
      if (present(errmsg)) errmsg = "mask rank mismatch for 'cube'"
    case ("labels")
      status = NML_ERR_INVALID_INDEX
      if (present(errmsg)) errmsg = "mask rank mismatch for 'labels'"
    case ("defaulted")
      status = NML_ERR_INVALID_INDEX
      if (present(errmsg)) errmsg = "mask rank mismatch for 'defaulted'"
    case ("flags")
      status = NML_ERR_INVALID_INDEX
      if (present(errmsg)) errmsg = "mask rank mismatch for 'flags'"
    case ("runtime")
      if (.not. allocated(this%runtime)) then
        status = NML_ERR_NOT_SET
        if (present(errmsg)) errmsg = "array storage unavailable: runtime"
        return
      end if

      allocate(mask( &
        size(this%runtime, 1), &
        size(this%runtime, 2)))
      do idx__2 = 1, size(this%runtime, 2)
        do idx__1 = 1, size(this%runtime, 1)

          if (ieee_is_nan(this%runtime(idx__1, idx__2))) then
            mask(idx__1, idx__2) = .false.
          else
            mask(idx__1, idx__2) = .true.
          end if
        end do
      end do

    case default
      status = NML_ERR_INVALID_NAME
      if (present(errmsg)) errmsg = "unknown field: " // trim(name)
    end select
  end function nml_presence_set_mask__rank__2

  !> \brief Obtain the item presence mask with one field-name dispatch
  integer function nml_presence_set_mask__rank__3(this, name, mask, errmsg) result(status)
    class(nml_presence_t), intent(in) :: this !< namelist instance
    character(len=*), intent(in) :: name !< field or derived component path
    logical, allocatable, intent(out) :: mask(:, :, :) !< item presence
    character(len=*), intent(out), optional :: errmsg !< error message for non-OK status values
    integer :: idx__1
    integer :: idx__2
    integer :: idx__3
    status = NML_OK
    if (present(errmsg)) errmsg = ""
    if (.not. this%is_configured) then
      status = NML_ERR_NOT_SET
      if (present(errmsg)) errmsg = "namelist not configured; call set or from_file"
      return
    end if
    select case (to_lower(trim(name)))
    case ("scalar")
      status = NML_ERR_INVALID_INDEX
      if (present(errmsg)) errmsg = "array query not supported for scalar: scalar"
    case ("counts")
      status = NML_ERR_INVALID_INDEX
      if (present(errmsg)) errmsg = "mask rank mismatch for 'counts'"
    case ("matrix")
      status = NML_ERR_INVALID_INDEX
      if (present(errmsg)) errmsg = "mask rank mismatch for 'matrix'"
    case ("cube")

      allocate(mask( &
        size(this%cube, 1), &
        size(this%cube, 2), &
        size(this%cube, 3)))
      do idx__3 = 1, size(this%cube, 3)
        do idx__2 = 1, size(this%cube, 2)
          do idx__1 = 1, size(this%cube, 1)

            if (this%cube(idx__1, idx__2, idx__3) == -huge(this%cube(idx__1, idx__2, idx__3))) then
              mask(idx__1, idx__2, idx__3) = .false.
            else
              mask(idx__1, idx__2, idx__3) = .true.
            end if
          end do
        end do
      end do

    case ("labels")
      status = NML_ERR_INVALID_INDEX
      if (present(errmsg)) errmsg = "mask rank mismatch for 'labels'"
    case ("defaulted")
      status = NML_ERR_INVALID_INDEX
      if (present(errmsg)) errmsg = "mask rank mismatch for 'defaulted'"
    case ("flags")
      status = NML_ERR_INVALID_INDEX
      if (present(errmsg)) errmsg = "mask rank mismatch for 'flags'"
    case ("runtime")
      status = NML_ERR_INVALID_INDEX
      if (present(errmsg)) errmsg = "mask rank mismatch for 'runtime'"
    case default
      status = NML_ERR_INVALID_NAME
      if (present(errmsg)) errmsg = "unknown field: " // trim(name)
    end select
  end function nml_presence_set_mask__rank__3

  !> \brief Determine the smallest complete lower-bound-anchored populated prefix
  integer function nml_presence_filled_shape(this, name, filled, errmsg) result(status)
    class(nml_presence_t), intent(in) :: this !< namelist instance
    character(len=*), intent(in) :: name !< field or derived component path
    integer, intent(out) :: filled(:) !< prefix extents, retained when the prefix has holes
    character(len=*), intent(out), optional :: errmsg !< error message for non-OK status values
    integer :: idx__1
    integer :: idx__2
    integer :: idx__3

    filled = 0
    status = NML_OK
    if (present(errmsg)) errmsg = ""
    if (.not. this%is_configured) then
      status = NML_ERR_NOT_SET
      if (present(errmsg)) errmsg = "namelist not configured; call set or from_file"
      return
    end if
    select case (to_lower(trim(name)))
    case ("scalar")
      status = NML_ERR_INVALID_INDEX
      if (present(errmsg)) errmsg = "array query not supported for scalar: scalar"
    case ("counts")
      if (size(filled) /= 1) then
        status = NML_ERR_INVALID_INDEX
        if (present(errmsg)) errmsg = "shape rank mismatch for 'counts'"
        return
      end if

      do idx__1 = 1, size(this%counts, 1)

        if (this%counts(idx__1) == -huge(this%counts(idx__1))) cycle
        if (idx__1 > filled(1)) filled(1) = idx__1
      end do

      do idx__1 = 1, filled(1)

        if (this%counts(idx__1) == -huge(this%counts(idx__1))) then
          status = NML_ERR_PARTLY_SET
          if (present(errmsg)) errmsg = "array partly set: counts"
          return
        end if
      end do

    case ("matrix")
      if (size(filled) /= 2) then
        status = NML_ERR_INVALID_INDEX
        if (present(errmsg)) errmsg = "shape rank mismatch for 'matrix'"
        return
      end if

      do idx__2 = 1, size(this%matrix, 2)
        do idx__1 = 1, size(this%matrix, 1)

          if (ieee_is_nan(this%matrix(idx__1, idx__2))) cycle
          if (idx__1 > filled(1)) filled(1) = idx__1
          if (idx__2 > filled(2)) filled(2) = idx__2
        end do
      end do

      do idx__2 = 1, filled(2)
        do idx__1 = 1, filled(1)

          if (ieee_is_nan(this%matrix(idx__1, idx__2))) then
            status = NML_ERR_PARTLY_SET
            if (present(errmsg)) errmsg = "array partly set: matrix"
            return
          end if
        end do
      end do

    case ("cube")
      if (size(filled) /= 3) then
        status = NML_ERR_INVALID_INDEX
        if (present(errmsg)) errmsg = "shape rank mismatch for 'cube'"
        return
      end if

      do idx__3 = 1, size(this%cube, 3)
        do idx__2 = 1, size(this%cube, 2)
          do idx__1 = 1, size(this%cube, 1)

            if (this%cube(idx__1, idx__2, idx__3) == -huge(this%cube(idx__1, idx__2, idx__3))) cycle
            if (idx__1 > filled(1)) filled(1) = idx__1
            if (idx__2 > filled(2)) filled(2) = idx__2
            if (idx__3 > filled(3)) filled(3) = idx__3
          end do
        end do
      end do

      do idx__3 = 1, filled(3)
        do idx__2 = 1, filled(2)
          do idx__1 = 1, filled(1)

            if (this%cube(idx__1, idx__2, idx__3) == -huge(this%cube(idx__1, idx__2, idx__3))) then
              status = NML_ERR_PARTLY_SET
              if (present(errmsg)) errmsg = "array partly set: cube"
              return
            end if
          end do
        end do
      end do

    case ("labels")
      if (size(filled) /= 1) then
        status = NML_ERR_INVALID_INDEX
        if (present(errmsg)) errmsg = "shape rank mismatch for 'labels'"
        return
      end if

      do idx__1 = 1, size(this%labels, 1)

        if (this%labels(idx__1) == achar(0)) cycle
        if (idx__1 > filled(1)) filled(1) = idx__1
      end do

      do idx__1 = 1, filled(1)

        if (this%labels(idx__1) == achar(0)) then
          status = NML_ERR_PARTLY_SET
          if (present(errmsg)) errmsg = "array partly set: labels"
          return
        end if
      end do

    case ("defaulted")
      if (size(filled) /= 1) then
        status = NML_ERR_INVALID_INDEX
        if (present(errmsg)) errmsg = "shape rank mismatch for 'defaulted'"
        return
      end if

      filled(1) = size(this%defaulted, 1)
    case ("flags")
      if (size(filled) /= 1) then
        status = NML_ERR_INVALID_INDEX
        if (present(errmsg)) errmsg = "shape rank mismatch for 'flags'"
        return
      end if

      filled(1) = size(this%flags, 1)
    case ("runtime")
      if (size(filled) /= 2) then
        status = NML_ERR_INVALID_INDEX
        if (present(errmsg)) errmsg = "shape rank mismatch for 'runtime'"
        return
      end if
      if (.not. allocated(this%runtime)) then
        status = NML_ERR_NOT_SET
        if (present(errmsg)) errmsg = "array storage unavailable: runtime"
        return
      end if

      do idx__2 = 1, size(this%runtime, 2)
        do idx__1 = 1, size(this%runtime, 1)

          if (ieee_is_nan(this%runtime(idx__1, idx__2))) cycle
          if (idx__1 > filled(1)) filled(1) = idx__1
          if (idx__2 > filled(2)) filled(2) = idx__2
        end do
      end do

      do idx__2 = 1, filled(2)
        do idx__1 = 1, filled(1)

          if (ieee_is_nan(this%runtime(idx__1, idx__2))) then
            status = NML_ERR_PARTLY_SET
            if (present(errmsg)) errmsg = "array partly set: runtime"
            return
          end if
        end do
      end do

    case default
      status = NML_ERR_INVALID_NAME
      if (present(errmsg)) errmsg = "unknown field: " // trim(name)
    end select
  end function nml_presence_filled_shape

  !> \brief Validate required values and constraints
  integer function nml_presence_is_valid(this, errmsg) result(status)
    class(nml_presence_t), intent(in) :: this !< namelist instance
    character(len=*), intent(out), optional :: errmsg !< error message for non-OK status values
    integer :: istat

    status = NML_OK
    if (present(errmsg)) errmsg = ""
    if (.not. this%is_configured) then
      status = NML_ERR_NOT_SET
      if (present(errmsg)) errmsg = "namelist not configured; call set or from_file"
      return
    end if

    ! bounds constraints
    if (.not. all(matrix__in_bounds(this%matrix, allow_missing=.true.))) then
      status = NML_ERR_BOUNDS
      if (present(errmsg)) errmsg = "bounds constraint failed: matrix"
      return
    end if
  end function nml_presence_is_valid

end module nml_presence
