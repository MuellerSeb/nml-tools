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
