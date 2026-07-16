program namelist_conformance
  implicit none

  type :: setting_t
    logical :: flag = .false.
    integer :: value = 0
  end type setting_t

  integer :: unit, stat
  integer :: values(2, 2) = -1
  character(len=8) :: label = ""
  type(setting_t) :: settings(2)
  character(len=512) :: path
  namelist /run/ values, settings, label

  if (command_argument_count() /= 1) error stop "expected one namelist path"
  call get_command_argument(1, path)
  open(newunit=unit, file=trim(path), status="old", action="read", iostat=stat)
  if (stat /= 0) error stop "failed to open conformance input"
  read(unit, nml=run, iostat=stat)
  close(unit)
  if (stat /= 0) error stop "failed to read conformance input"

  if (any(values(:, 1) /= [0, 0])) error stop "whole-array assignment mismatch"
  if (any(values(:, 2) /= [3, 2])) error stop "section/overlap assignment mismatch"
  if (.not. settings(1)%flag .or. settings(1)%value /= 1) then
    error stop "first derived buffer mismatch"
  end if
  if (settings(2)%flag .or. settings(2)%value /= 2) then
    error stop "second derived buffer mismatch"
  end if
  if (trim(label) /= "abc") error stop "character assignment mismatch"
end program namelist_conformance
