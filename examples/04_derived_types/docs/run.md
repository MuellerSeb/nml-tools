# Derived-type configuration

Demonstrates referenced reusable and inline imported derived types.

**Namelist**: `run`

## Fields

| Name | Type | Declared required | Input required | Info |
| --- | --- | --- | --- | --- |
| [period](#period) | type(period_t) | yes | yes | Main simulation period |
| [periods](#periods) | type(period_t) array | yes | no | Comparison periods |
| [station](#station) | type(station_t) | yes | yes | Selected station |

## Field details

### period

Main simulation period `period`

Start and end years for a configured time window.

Summary:
- Type: `type(period_t)`
- Declared required: yes
- Input required: yes
- Default: `{start_year: 2000}`

Components:
- `period%start_year`: `integer(i4)`; declared required yes; input required no; default `2000` (object default); Minimum: `>= 1800`; Maximum: `<= 2200`
- `period%end_year`: `integer(i4)`; declared required yes; input required yes
- `period%label`: `character(len=period_label_len)`; declared required no; input required no; default `"main"` (component default)

### periods

Comparison periods `periods`

Summary:
- Type: `type(period_t), dimension(n_periods)`
- Declared required: yes
- Input required: no
- Default: `{start_year: 1980, end_year: 1999}` (broadcast item default)

Components:
- `periods%start_year`: `integer(i4)`; declared required yes; input required no; default `1980` (item default); Minimum: `>= 1800`; Maximum: `<= 2200`
- `periods%end_year`: `integer(i4)`; declared required yes; input required no; default `1999` (item default)
- `periods%label`: `character(len=period_label_len)`; declared required no; input required no; default `"period"` (component default)

### station

Selected station `station`

Application-owned station descriptor with schema-matched label storage.

Summary:
- Type: `type(station_t)`
- Declared required: yes
- Input required: yes

Components:
- `station%code`: `integer(i4)`; declared required yes; input required yes; Minimum: `>= 1`
- `station%label`: `character(len=station_label_len)`; declared required no; input required no; default `"unknown"` (component default)

## Derived types

### `period_t`

Simulation period

Start and end years for a configured time window.

- Ownership: `nml_helper`
- Buffer-compatible: yes
- Component order: start_year, end_year, label
- `start_year`: `integer(i4)`; declared required yes; input required yes
- `end_year`: `integer(i4)`; declared required yes; input required yes
- `label`: `character(len=period_label_len)`; declared required no; input required no; default `"period"` (component default)

### `station_t`

Selected station

Application-owned station descriptor with schema-matched label storage.

- Ownership: imported from `application_types`
- Buffer-compatible: yes
- Component order: code, label
- **Declaration-order contract:** the imported Fortran type must declare components in the resolved schema order shown above.
- `code`: `integer(i4)`; declared required yes; input required yes
- `label`: `character(len=station_label_len)`; declared required no; input required no; default `"unknown"` (component default)

## Example

```fortran
&run
  period%start_year = 2000
  period%end_year = 0
  period%label = "main"
  periods(:)%start_year = 1980
  periods(:)%end_year = 1999
  periods(:)%label = "period"
  station%code = 0
  station%label = "unknown"
/
```

