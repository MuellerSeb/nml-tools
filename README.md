# nml-tools

<p align="center">
  <img src="https://raw.githubusercontent.com/MuellerSeb/nml-tools/6213cc56244cca589563d0baabf93f2b46610b27/docs/logo.png" alt="nml-tools logo" width="240">
</p>

Generate Fortran namelist modules, Markdown docs, and template namelists from a small JSON Schema-like specification with Fortran-focused extensions.

## Features

- Schema input in YAML or JSON.
- Core keywords from JSON schema: `type`, `properties`, `required`, `default`, `examples`, `title`, `description`.
- Fortran extensions: `x-fortran-namelist`, `x-fortran-kind`,
  `x-fortran-len`, `x-fortran-shape`, `x-fortran-flex-tail-dims`,
  `x-fortran-default-*`.
- Outputs: Fortran module, helper module, Markdown docs, template namelist.
- Config-driven CLI for batching multiple schemas.

### Missing Fortran features

- No support for derived types:
  - Only scalars and arrays of scalars are supported.
  - Could be emulated with nested objects, but one would need to decide where the respective fortran types are defined or used from.
- No support for complex types:
  - JSON doesn't have a native complex type.
  - Could be emulated with:
    - Lists of length 2 with metadata, like f90nml does for JSON conversion.
    - Objects with `real` and `imag` properties.
    - Strings with a specific format like pydantic does.

## Fortran extensions (x-fortran-*)

These keywords extend JSON Schema with Fortran-specific requirements.

### x-fortran-namelist

- Location: schema root.
- Type: string.
- Meaning: name of the Fortran namelist block.

Example:

```yaml
x-fortran-namelist: optimization
```

### x-fortran-kind

- Location: integer/number properties or array `items`.
- Type: string.
- Meaning: Fortran kind identifier (mapped via `[kinds]` in the config).
- If omitted, plain `integer`/`real` is used.

Example:

```yaml
count:
  type: integer
  x-fortran-kind: i4
```

### x-fortran-len

- Location: string properties or array `items`.
- Type: integer literal or identifier.
- Meaning: Fortran character length (`character(len=...)`).
- Identifiers must be defined in `[constants]` in the config and be integers.

Example:

```yaml
name:
  type: string
  x-fortran-len: buf
```

### x-fortran-shape

- Location: array properties.
- Type: integer, identifier, or list of integers/identifiers.
- Meaning: Fortran array dimensions; identifiers are resolved via `[constants]`.
- Required; deferred-size dimensions are not supported.
- Nested arrays are not supported. Use a single array with a shape list for
  multi-dimensional arrays.

Example:

```yaml
values:
  type: array
  x-fortran-shape: [3, 2, max_iter]
  items:
    type: number
    x-fortran-kind: dp
```

### x-fortran-flex-tail-dims

- Location: array properties.
- Type: integer.
- Meaning: number of trailing dimensions that may be shorter than the declared
  shape (0 disables flexibility).
- Must be between 0 and the array rank; only trailing dimensions are supported.
- Defaults and logical arrays are not supported for flexible arrays.
- The generated type exposes `filled_shape()` to compute the used extent.

Example:

```yaml
values:
  type: array
  x-fortran-shape: [3, 2, max_iter]
  x-fortran-flex-tail-dims: 1
  items:
    type: number
    x-fortran-kind: dp
```

### x-fortran-default-order

- Location: array properties with `default`.
- Type: string (`F` or `C`, default `F`).
- Meaning: memory order used when reshaping defaults.

Example:

```yaml
x-fortran-default-order: C
```

### x-fortran-default-repeat

- Location: array properties with `default`.
- Type: boolean.
- Meaning: repeat the provided default values to fill the full shape.
- Array defaults must be lists; to broadcast a scalar, set `default` on
  `items` instead.
- Cannot be used together with `x-fortran-default-pad`.

Example:

```yaml
x-fortran-default-repeat: true
```

### x-fortran-default-pad

- Location: array properties with `default`.
- Type: scalar or list of scalars.
- Meaning: pad values used to fill the array if the default list is shorter
  than the shape.
- Cannot be used together with `x-fortran-default-repeat`.

Example:

```yaml
x-fortran-default-pad: 0
```

Combined example:

```yaml
values_repeat:
  type: array
  x-fortran-shape: [2, 3]
  items:
    type: integer
    x-fortran-kind: i4
  default: [1, 2]
  x-fortran-default-repeat: true

values_pad_c:
  type: array
  x-fortran-shape: [2, 3]
  items:
    type: integer
    x-fortran-kind: i4
  default: [1, 2, 3]
  x-fortran-default-order: C
  x-fortran-default-pad: 0
```

## Validation keywords

Only a subset of JSON Schema validation keywords is implemented.
Validation is opt-in: call `is_valid()` on the generated type to check required values, enum and bound constraints.

### Enum support
Enums are supported for strings and integers only.
For arrays, enums are defined on `items` (not on the array itself).

- Keywords: `enum`
- The generated Fortran module exposes public `*_enum_values` arrays and
  elemental `*_in_enum` helpers.
- String enums compare against `trim(value)`; enum literals are stored with the
  field length.

### Numeric bounds

You can add minimum/maximum constraints for integer or real values.
For arrays, the bounds apply to each item and must be defined on `items`.

- Keywords: `minimum`, `maximum`, `exclusiveMinimum`, `exclusiveMaximum`
- Applies to: `integer` and `number` (`real` in Fortran)
- For arrays: bounds belong on `items`, not the array property

Example (scalars):

```yaml
tolerance:
  type: number
  x-fortran-kind: dp
  minimum: 0.0
  exclusiveMaximum: 1.0
```

Example (array items):

```yaml
counts:
  type: array
  x-fortran-shape: 3
  items:
    type: integer
    minimum: 1
```

## Configuration (nml-config.toml)

The CLI reads a TOML config file. Paths are resolved relative to the config
file location.

### [helper]

Controls the generated helper module.

- `path` (string, required to generate helper): output file for the helper module.
- `module` (string, optional): Fortran module name (default: `nml_helper`).
- `buffer` (int, optional): line buffer length for the helper module.
- `header` (string, optional): text inserted at the top of the helper file.

### [constants]

Named constants used for dimensions and string lengths.

- Each entry is a table with `value` (int/float) and optional `doc`.
- Values must be plain numbers (no kind suffixes).

Example:

```toml
[constants.max_iter]
value = 4
doc = "Maximum number of iterations."
```

### [kinds]

Defines the kind module and allowed kinds.

- `module` (string): Fortran module to `use`.
- `real` (list of strings): allowed real kinds.
- `integer` (list of strings): allowed integer kinds.
- `map` (table, optional): schema kind name → module kind name.

### [documentation]

Optional extra module documentation appended after the generated `\brief` and
`\details`. Multiline strings are supported and Doxygen formatting is allowed.

- `module` (string, optional): extra module documentation block.
- `md_doxygen_id_from_name` (bool, optional): add `{#<namelist>}` to Markdown header (default `false`).
- `md_add_toc_statement` (bool, optional): insert `[TOC]` after the Markdown header (default `false`).

### namelists (array)

Schema entries to generate per-namelist outputs.

- `schema` (string): schema file path.
- `mod_path` (string, optional): Fortran module output path.
- `doc_path` (string, optional): Markdown output path.

If a path is omitted, that output is not generated.

### templates (array)

Template namelist output configuration.

- `output` (string): template namelist output path.
- `schemas` (list of strings): schemas included in the template file.
- `doc_mode`: `plain` or `documented`.
- `value_mode`: `empty`, `filled`, `minimal-empty`, or `minimal-filled`.

Optional values can override per-namelist fields for filled modes:

```toml
[templates.values.optimization]
niterations = 4
tolerance = 0.1
```

## CLI

The command line interface is available as `nml-tools` or `nmlt`.
Common flags: `-h`/`--help`, `-V`/`--version`, `-v`/`-q` (repeatable).

Primary subcommands:

- `generate`: run the full pipeline (helper, Fortran modules, docs, templates).
- `gen-fortran`: generate helper + Fortran modules only.
- `gen-markdown`: generate Markdown docs only.
- `gen-template`: generate template namelists only.
- `validate`: validate a namelist file against schema definitions.

### Generation

Generate all outputs:

```bash
nml-tools generate --config nml-config.toml
```

Generate specific outputs:

```bash
nml-tools gen-fortran --config nml-config.toml
nml-tools gen-markdown --config nml-config.toml
nml-tools gen-template --config nml-config.toml
```

### Validation

Validation is check-only (defaults are not applied) and implements only a
subset of JSON Schema constraints (types, required, enums, bounds, string
length, array shape/flex). Unknown keys in a namelist or namelist blocks not
covered by provided schemas are errors.

Config-driven:

```bash
nml-tools validate --config nml-config.toml input.nml
```

Schema-only:

```bash
nml-tools validate --schema demo.yml --input demo.nml
nml-tools validate --schema a.yml --schema b.yml combined.nml
```

Constants are resolved from `[constants]` in the config, or provided ad hoc:

```bash
nml-tools validate --schema demo.yml --constants MAX_ITER=10 input.nml
```

Array values are validated as rectangular lists in Fortran order
(outer list corresponds to the last Fortran index), matching `f90nml` parsing.

## Error handling

Generated type-bound procedures return integer status codes and accept an
optional `errmsg` argument. No `error stop` is emitted by generated code.

Status codes (defined in the helper module):

| Code | Meaning |
| --- | --- |
| `NML_OK` (0) | success |
| `NML_ERR_FILE_NOT_FOUND` (1) | file does not exist |
| `NML_ERR_OPEN` (2) | failed to open file |
| `NML_ERR_NOT_OPEN` (3) | file not open |
| `NML_ERR_NML_NOT_FOUND` (4) | namelist not found |
| `NML_ERR_READ` (5) | read/parse error |
| `NML_ERR_CLOSE` (6) | close error |
| `NML_ERR_REQUIRED` (10) | required field missing |
| `NML_ERR_ENUM` (11) | enum constraint failed |
| `NML_ERR_NOT_SET` (12) | field not set (sentinel) |
| `NML_ERR_PARTLY_SET` (13) | array partially set |
| `NML_ERR_BOUNDS` (14) | bounds constraint failed |
| `NML_ERR_INVALID_NAME` (20) | unknown field name |
| `NML_ERR_INVALID_INDEX` (21) | invalid index for array access |

Notes:

- `errmsg`, when present, is filled with a short message (including `iomsg` on read errors).
- `is_set` returns `NML_ERR_NOT_SET` if a value is missing, and
  `NML_ERR_INVALID_NAME`/`NML_ERR_INVALID_INDEX` on misuse.

## Documentation format

Generated Fortran doc-strings are currently tailored for Doxygen. Future
versions may make this configurable to support other tools such as FORD or the
Sphinx Fortran domain.

## Installation

```bash
pip install nml-tools
```

## Minimal example

Schema (`demo.yml`):

```yaml
title: Demo namelist
description: Small example namelist for nml-tools.
x-fortran-namelist: demo
type: object
required: [count]
properties:
  count:
    type: integer
    title: Number of steps
    x-fortran-kind: i4
  name:
    type: string
    title: Run label
    x-fortran-len: 64
    default: run1
  weights:
    type: array
    title: Weight vector
    x-fortran-shape: 3
    items:
      type: number
      x-fortran-kind: dp
    default: [0.1, 0.2, 0.3]
```

Config (`nml-config.toml`):

```toml
[helper]
path = "out/nml_helper.f90"
module = "nml_helper"
buffer = 1024

[kinds]
module = "iso_fortran_env"
real = ["real64"]
integer = ["int32"]
map = { dp = "real64", i4 = "int32" }

[[namelists]]
schema = "demo.yml"
mod_path = "out/nml_demo.f90"
doc_path = "out/nml_demo.md"

[[templates]]
output = "out/demo.nml"
schemas = ["demo.yml"]
doc_mode = "documented"
value_mode = "filled"
```

Generate outputs:

```bash
nml-tools generate --config nml-config.toml
```

Expected outputs:

- `out/nml_helper.f90`
- `out/nml_demo.f90`
- `out/nml_demo.md`
- `out/demo.nml`

## Comparison to JSON Schema

This project implements a focused subset of JSON Schema aimed at Fortran
namelist workflows, plus extensions for Fortran-specific types and shapes.

Main missing features compared to JSON Schema:

- No `$ref`/`$defs` or remote schema resolution.
- No composition keywords: `allOf`, `anyOf`, `oneOf`, `not`.
- No conditional keywords: `if`/`then`/`else`.
- No object constraints: `additionalProperties`, `patternProperties`,
  `propertyNames`, `dependencies`.
- No advanced array constraints: tuple typing, `contains`, `minItems`,
  `maxItems`, `uniqueItems`.
- No numeric or string validation keywords like `multipleOf`, `minLength`,
  `maxLength`, `pattern`, `format` (bounds are supported via `minimum`,
  `maximum`, `exclusiveMinimum`, and `exclusiveMaximum`).
- No nested object schemas; properties are scalars or arrays of scalars only.

Use the `x-fortran-*` extensions to express kind, length, and shape information
needed for code generation.
