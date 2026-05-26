# Reference-driven report configuration

A second namelist sharing the external definition library.

**Namelist**: `report`

## Fields

| Name | Type | Required | Info |
| --- | --- | --- | --- |
| [label](#label) | string | no | Report label |
| [level](#level) | integer | no | Reporting detail |
| [acceptance_fraction](#acceptance_fraction) | real | no | Acceptance fraction |

## Field details

### label

Report label `label`

Use-site documentation and default override for a shared string.

Summary:
- Type: `character(len=label_len)`
- Required: no
- Default: `"station-summary"`

### level

Reporting detail `level`

Inherits the default reporting level from the shared definition.

Summary:
- Type: `integer(i4)`
- Required: no
- Default: `1`
- Allowed values: `0`, `1`, `2`

### acceptance_fraction

Acceptance fraction `acceptance_fraction`

Use-site lower bound and default for the report threshold.

Summary:
- Type: `real(dp)`
- Required: no
- Default: `0.75`
- Minimum: `>= 0.5`
- Maximum: `<= 1.0`

## Example

```fortran
&report
  label = "station-summary"
  level = 1
  acceptance_fraction = 0.75
/
```

