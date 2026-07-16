# Derived-type configuration

Demonstrates referenced reusable and inline imported derived types.

**Namelist**: `run`

## Fields

| Name | Type | Required | Info |
| --- | --- | --- | --- |
| [period](#period) | type(period_t) | yes | Main simulation period |
| [periods](#periods) | type(period_t) array | yes | Comparison periods |
| [station](#station) | type(station_t) | yes | Selected station |

## Field details

### period

Main simulation period `period`

Start and end years for a configured time window.

Summary:
- Type: `type(period_t)`
- Required: yes

Components:
- `period%start_year`: `integer(i4)`; Minimum: `>= 1800`; Maximum: `<= 2200`
- `period%end_year`: `integer(i4)`
- `period%label`: `character(len=period_label_len)`; default `"main"`

### periods

Comparison periods `periods`

Summary:
- Type: `type(period_t), dimension(n_periods)`
- Required: yes

Components:
- `periods%start_year`: `integer(i4)`; Minimum: `>= 1800`; Maximum: `<= 2200`
- `periods%end_year`: `integer(i4)`
- `periods%label`: `character(len=period_label_len)`; default `"period"`

### station

Selected station `station`

Application-owned station descriptor with schema-matched label storage.

Summary:
- Type: `type(station_t)`
- Required: yes

Components:
- `station%code`: `integer(i4)`; Minimum: `>= 1`
- `station%label`: `character(len=station_label_len)`; default `"unknown"`

## Derived types

### `period_t`

Simulation period

Start and end years for a configured time window.

- Ownership: `nml_helper`
- Buffer-compatible: yes
- Component order: start_year, end_year, label
- `start_year`: `integer(i4)`
- `end_year`: `integer(i4)`
- `label`: `character(len=period_label_len)`

### `station_t`

Selected station

Application-owned station descriptor with schema-matched label storage.

- Ownership: imported from `application_types`
- Buffer-compatible: yes
- Component order: code, label
- **Declaration-order contract:** the imported Fortran type must declare components in the resolved schema order shown above.
- `code`: `integer(i4)`
- `label`: `character(len=station_label_len)`

## Example

```fortran
&run
  period%start_year = 0
  period%end_year = 0
  period%label = "main"
  periods(:)%start_year = 0
  periods(:)%end_year = 0
  periods(:)%label = "period"
  station%code = 0
  station%label = "unknown"
/
```

