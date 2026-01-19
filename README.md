# nml-tools

Generate Fortran namelist modules, Markdown docs, and template namelists from a
small JSON Schema-like specification with Fortran-focused extensions.

## Features

- Schema input in YAML or JSON.
- Core keywords: `type`, `properties`, `required`, `default`, `enum`,
  `examples`, `title`, `description`.
- Fortran extensions: `x-fortran-namelist`, `x-fortran-kind`,
  `x-fortran-len`, `x-fortran-shape`, `x-fortran-default-*`.
- Outputs: Fortran module, helper module, Markdown docs, template namelist.
- Config-driven CLI for batching multiple schemas.

## Enum support

- Enums are supported for strings and integers only.
- For arrays, enums are defined on `items` (not on the array itself).
- The generated Fortran module exposes public `*_enum_values` arrays and
  elemental `*_in_enum` helpers.
- Validation is opt-in: call `is_valid()` on the generated type to check
  required values and enum constraints.
- String enums compare against `trim(value)`; enum literals are stored with the
  field length.

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
- When the default is a scalar, it is broadcast to the whole array.
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
- No numeric or string validation keywords like `minimum`, `maximum`,
  `multipleOf`, `minLength`, `maxLength`, `pattern`, `format`.
- No nested object schemas; properties are scalars or arrays of scalars only.

Use the `x-fortran-*` extensions to express kind, length, and shape information
needed for code generation.
