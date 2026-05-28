# nml-tools derived-types example

This package demonstrates one-level derived-type namelist fields. The main schema
references reusable `period_t` from `schema/definitions.yml`, which is generated
once in `nml_helper`, and declares its single-use `station_t` field inline while
importing the type from the application-owned `fortran/application_types.f90`
module.

The generated namelist has a required scalar period, a runtime-sized period array,
and a required imported station. The scalar `period` refines the referenced
`period_t%label` default to `main`, while the `periods` array keeps the reusable
definition default `period`. The imported `station_t%label` storage is longer
than its schema contract; generated code checks that storage and blanks content
beyond the mapped eight-character value after assignments.

## Regenerate

```bash
nml-tools generate
nml-tools validate templates/run.nml
```

## Build And Test

```bash
python -m pip install -v ".[test]"
python -m pytest -q tests
```

## Native Fortran

A caller can initialize any non-empty subset of typed values with the concrete
field defaults and sentinels before applying changes:

```fortran
type(period_t) :: period
type(period_t), allocatable :: periods(:)
integer :: status
character(len=512) :: errmsg

status = config%init_type(period=period, periods=periods, errmsg=errmsg)
period%start_year = 2001
period%end_year = 2010
status = config%set(period=period, errmsg=errmsg)
```

Generated templates and ordinary namelist input use Fortran component notation:

```fortran
period%start_year = 2001
periods(1)%start_year = 1980
```

## Python

The Python API preserves nested structure while the intrinsic-only f2py layer
flattens components internally using `__`:

```python
import nml_derived_types_example as example

cfg = example.get_config()
cfg.set(
    period={"start_year": 2001, "end_year": 2010},
    periods=[
        {"start_year": 1980, "end_year": 1990},
        {"start_year": 1991, "end_year": 2000},
    ],
    station={"code": 7, "label": "central"},
)
cfg.is_valid()
assert cfg.is_set("period.start_year")
```
