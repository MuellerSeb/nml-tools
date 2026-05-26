# nml-tools derived-types example

This package demonstrates one-level derived-type namelist fields. The main schema
references object definitions from `schema/definitions.yml`: `period_t` is generated
once in `nml_helper`, while `station_t` is imported from the application-owned
`fortran/application_types.f90` module.

The generated namelist has a required scalar period, a runtime-sized period array,
and a required imported station. The imported `station_t%label` storage is longer
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

A caller can initialize an individual typed value with the concrete field's
defaults and sentinels before applying changes:

```fortran
type(period_t) :: period
integer :: status
character(len=512) :: errmsg

status = config%init_type(period=period, errmsg=errmsg)
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
