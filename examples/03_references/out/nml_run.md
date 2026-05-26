# Reference-driven run configuration

Configuration composed from a reusable root schema and local fields.

**Namelist**: `run`

## Fields

| Name | Type | Required | Info |
| --- | --- | --- | --- |
| [label](#label) | string | no | Run label |
| [steps](#steps) | integer | yes | Simulation steps |
| [station_weights](#station_weights) | real array | no | Station weights |
| [method](#method) | string | no | Time integration method |
| [relaxation](#relaxation) | real | no | Relaxation factor |

## Field details

### label

Run label `label`

Human-readable label for this concrete run.

Summary:
- Type: `character(len=label_len)`
- Required: no
- Default: `"reference-example"`

### steps

Simulation steps `steps`

Summary:
- Type: `integer(i4)`
- Required: yes
- Minimum: `>= 1`
- Maximum: `<= 10000`
- Examples: `24`

### station_weights

Station weights `station_weights`

Override the library default pattern for this use site.

Summary:
- Type: `real(dp), dimension(n_stations)`
- Required: no
- Default: `[0.5, 1.0]` (repeated)
- Minimum: `>= 0.0`

### method

Time integration method `method`

Integration scheme selected for this run.

Summary:
- Type: `character(len=label_len)`
- Required: no
- Default: `"RK2"`
- Allowed values: `"Euler"`, `"RK2"`, `"RK4"`

### relaxation

Relaxation factor `relaxation`

A strictly positive fraction narrowed at the use site.

Summary:
- Type: `real(dp)`
- Required: no
- Default: `0.25`
- Minimum: `> 0.0`
- Maximum: `<= 0.5`

## Example

```fortran
&run
  label = "reference-example"
  steps = 24
  station_weights(:) = 0.5, 1.0
  method = "RK2"
  relaxation = 0.25
/
```

