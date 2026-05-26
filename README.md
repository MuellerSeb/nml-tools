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
  `x-fortran-default-*`, `x-fortran-type`, `x-fortran-module`.
- Outputs: Fortran module, helper module, Markdown docs, template namelist.
- Config-driven CLI for batching multiple schemas.

### Missing Fortran features

- Derived types currently support one level of intrinsic scalar components
  only; nested derived values and array components are not supported.
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
- Meaning: Fortran array dimensions; identifiers are resolved via `[constants]`
  or `[dimensions]`.
- Required; deferred-size dimensions are not supported.
- Nested arrays are not supported. Use a single array with a shape list for
  multi-dimensional arrays.
- Shape identifiers from `[constants]` produce fixed-size arrays.
- Shape identifiers from `[dimensions]` produce allocatable arrays whose
  dimensions can be changed at runtime with the generated `set_dims()` method.

Example:

```yaml
values:
  type: array
  x-fortran-shape: [3, 2, max_iter]
  items:
    type: number
    x-fortran-kind: dp
```

### x-fortran-type and x-fortran-module

- Location: a referenced `type: object` definition used as a property or as
  array `items`.
- `x-fortran-type` is required and gives the Fortran derived type name.
- `x-fortran-module` is optional. If absent, the type is emitted once in the
  generated helper module. If present, the namelist module imports the type
  from that application-owned module.

```yaml
$defs:
  period:
    title: Time period
    description: Bounds for one interval.
    type: object
    x-fortran-type: period_t
    properties:
      start_year:
        type: integer
      label:
        type: string
        x-fortran-len: 16
        default: default
properties:
  period:
    $ref: "#/$defs/period"
  periods:
    type: array
    x-fortran-shape: n_periods
    items:
      $ref: "#/$defs/period"
```

Only intrinsic scalar members are supported in the first implementation.
Object defaults, derived array defaults, derived flexible-tail arrays, nested
derived members, and array members are rejected. Optional derived fields must
not declare required inner members. For scalar imported fields with string
members, generated code verifies that application storage is at least
`x-fortran-len` characters long and blanks longer trailing storage after reads
and setters.

Generated native APIs accept typed values and add `init_type`, for example:

```fortran
type(period_t) :: period
status = config%init_type(period=period)
period%start_year = 2001
status = config%set(period=period)
```

Namelist and template entries use normal component notation:

```fortran
period%start_year = 2001
periods(2)%start_year = 2001
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

## Array set semantics

Generated `set(...)` methods follow Fortran namelist-buffer semantics for
arrays. When an array argument is provided, the setter writes the supplied values
into the leading subsection of the target array. The provided extents must not
exceed the configured target extents, but they do not have to fill the full
array.

Completeness is checked by `is_valid()`, not by `set(...)`. This means a
required array can be partly set without an immediate setter error, but
`is_valid()` will fail until the required entries are fully provided.

Generated Python wrappers use the same semantics: scalar and lower-rank array
inputs are normalized to singleton trailing dimensions before calling the
Fortran setter.

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

## Configuration (`nml-config.toml` or `pyproject.toml`)

The CLI reads a TOML config file. If `--config` is omitted, nml-tools first
looks for `nml-config.toml` and then for `[tool.nml-tools]` in
`pyproject.toml`. Paths are resolved relative to the config file location.

Standalone config files use the tables shown below at the TOML root. In
`pyproject.toml`, put the same content under `[tool.nml-tools]`, for example
`[tool.nml-tools.helper]` and `[[tool.nml-tools.namelists]]`.

- `minimum-version` (string, optional): lower bound for the nml-tools version
  required by this config. This is not an exact version pin.

Example:

```toml
[tool.nml-tools]
minimum-version = "0.2.2"

[tool.nml-tools.helper]
path = "out/nml_helper.f90"

[[tool.nml-tools.namelists]]
schema = "optimization.yml"
mod_path = "out/nml_optimization.f90"
```

### [helper]

Controls the generated helper module.

- `path` (string, required to generate helper): output file for the helper module.
- `module` (string, optional): Fortran module name (default: `nml_helper`).
- `buffer` (int, optional): line buffer length for the helper module.
- `header` (string, optional): text inserted at the top of the helper file.

### [constants]

Named static constants used for fixed dimensions, string lengths, and generated
helper parameters.

- Each entry is a table with integer `value` and optional `doc`.
- Values must be plain integers (no kind suffixes).
- String lengths from `x-fortran-len` may use constants. Runtime dimensions are
  intentionally not supported for string lengths.

Example:

```toml
[constants.buf]
value = 128
doc = "String buffer length."
```

### [dimensions]

Named runtime array dimension defaults.

- Each entry is a table with positive integer `value` and optional `doc`.
- Names must be unique across `[constants]` and `[dimensions]`.
- Entries may be used in `x-fortran-shape`, but not in `x-fortran-len`.
- Arrays whose shape contains a `[dimensions]` name are generated as
  allocatable runtime-sized arrays.
- Generated Fortran and Python wrappers expose `set_dims(...)`. Omitted or
  `None` Python values reset the dimension to its configured default.
- Calling `set_dims(...)` deallocates affected arrays and clears configured
  values. Call `set(...)` or `from_file(...)` afterwards.

Example:

```toml
[dimensions.max_iter]
value = 4
doc = "Maximum number of iterations."
```

### [kinds]

Defines the kind module and allowed kinds.

- `module` (string): Fortran module to `use`.
- `real` (list of strings): allowed real kinds.
- `integer` (list of strings): allowed integer kinds.
- `map` (table, optional): schema kind name → module kind name.

### [f2py]

Optional settings for f2py wrapper generation.

- `f2cmap_path` (string, optional): output path for a generated `.f2py_f2cmap`
  file.
- `c_types.real` (table): explicit f2py C type mapping for schema real kind
  names used by f2py wrappers.
- `c_types.integer` (table): explicit f2py C type mapping for schema integer
  kind names used by f2py wrappers.
  `c_intptr_t` is added automatically as `long_long` unless explicitly
  overridden.

Generated Python f2py shims assume a package-local extension layout. The f2py
extension module named by `f2py_path` must be installed next to the generated
Python wrapper file, and the wrapper imports it with `from . import <module>`.

The f2py wrappers use the same schema kind aliases as the normal Fortran
module. For example, a schema kind `dp` with `[kinds].map = { dp = "real64" }`
is still emitted as `real(dp)` in the wrapper and imported as
`dp=>real64`. The generated f2py map therefore also uses `dp`:

```toml
[f2py]
f2cmap_path = ".f2py_f2cmap"

[f2py.c_types.real]
dp = "double"

[f2py.c_types.integer]
i4 = "int"
```

The f2py-visible wrapper procedures avoid Fortran `optional` dummy arguments
and assumed-shape arrays. Optional Python values are represented by generated
`has_<name>` flags and harmless dummy values. Inside the Fortran wrapper,
allocated local variables are passed to the generated type-bound `set` method
when a value is present; unallocated allocatables are passed otherwise, so the
type-bound `set` still sees `present(arg) == .false.`. This keeps the f2py ABI
simple while preserving the normal generated Fortran setter semantics. This
relies on the Fortran 2008 rule that an unallocated allocatable actual argument
associated with an optional nonallocatable dummy argument is treated as not
present.

For array arguments, the generated Python shim follows the same partial-set
semantics as the Fortran setter. Scalar inputs become shape `(1, ..., 1)`;
lower-rank inputs get singleton trailing dimensions before being passed to f2py.

The f2py wrappers use opaque integer handles for Fortran-owned namelist
instances. nml-tools assumes that the owning Fortran library creates those
handles from live `target` objects and keeps the objects alive while Python uses
the handle. The raw-address helper generated for f2py support uses `c_loc`/
`c_f_pointer` semantics; taking `c_loc` of the nonpolymorphic generated namelist
target relies on the Fortran 2008 rule that allows scalar nonpolymorphic
variables with no length type parameter. `NML_ERR_INVALID_HANDLE` only detects a
zero handle. Passing a stale, foreign, or otherwise invalid non-zero handle is
undefined behavior and may crash. Projects that need robust invalid-handle
detection should add their own registry/token layer in the owning library.
If the owning Fortran library deallocates, replaces, or otherwise invalidates a
target, users should discard all Python wrappers for that handle or call the
generated wrapper's `invalidate()` method. `invalidate()` only sets that Python
wrapper's stored handle to zero; it does not notify Fortran or deallocate
anything.

### [documentation]

Optional extra module documentation appended after the generated `\brief` and
`\details`. Multiline strings are supported and Doxygen formatting is allowed.

- `module` (string, optional): extra module documentation block.
- `py-style` (`numpy` or `doxygen`, optional): generated Python f2py wrapper
  docstring style (default `numpy`).
- `md_doxygen_id_from_name` (bool, optional): add `{#<namelist>}` to Markdown header (default `false`).
- `md_add_toc_statement` (bool, optional): insert `[TOC]` after the Markdown header (default `false`).

### namelists (array)

Schema entries to generate per-namelist outputs.

- `schema` (string): schema file path.
- `mod_path` (string, optional): Fortran module output path.
- `doc_path` (string, optional): Markdown output path.
- `f2py_path` (string, optional): Fortran source path for f2py wrapper modules.
- `py_path` (string, optional): Python shim path for wrapper classes. Requires
  `f2py_path`.

If a path is omitted, that output is not generated.

Multiple namelists may use the same `f2py_path` or `py_path`; nml-tools
collects the wrappers/classes into the shared file.

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

Derived overrides use nested TOML tables and arrays of tables:

```toml
[templates.values.run.period]
start_year = 2001

[[templates.values.run.periods]]
start_year = 1980

[[templates.values.run.periods]]
start_year = 2001
```

## CLI

The command line interface is available as `nml-tools` or `nmlt`.
Common flags: `-h`/`--help`, `-V`/`--version`, `-v`/`-q` (repeatable).

Primary subcommands:

- `generate`: run the full pipeline (helper, Fortran modules, docs, templates).
- `check`: verify configured generated files are up to date.
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

If `f2py_path` is configured, `generate` and `gen-fortran` also emit the
f2py-facing Fortran wrapper file. `generate` additionally emits `py_path`
Python shims. If `[f2py].f2cmap_path` is configured, the generated map can be
passed to f2py with `--f2cmap`.

Check generated files without rewriting them:

```bash
nml-tools check --config nml-config.toml
nml-tools check --config nml-config.toml --diff
```

`check` exits with a non-zero status if any configured generated file is
missing or differs from the current generator output. This is intended for CI
jobs that should ensure checked-in generated files are current.

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

When validation is config-driven, schema constants are loaded from `[constants]`
and runtime array dimensions are loaded from `[dimensions]`. Both can be
overridden for a validation run:

```bash
nml-tools validate --config nml-config.toml \
  --constants buf=128 \
  --dimensions max_iter=10 \
  input.nml
```

In schema-only validation, provide the same values ad hoc:

```bash
nml-tools validate --schema demo.yml \
  --constants buf=128 \
  --dimensions max_iter=10 \
  input.nml
```

`--constants` supplies static schema constants for string lengths and fixed
array shapes. `--dimensions` supplies runtime array dimensions. Names are
matched case-insensitively, normalized to lowercase, and must stay unique across
both sets.

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
| `NML_ERR_INVALID_HANDLE` (22) | zero opaque f2py handle |

Notes:

- `errmsg`, when present, is filled with a short message (including `iomsg` on read errors).
- `is_set` returns `NML_ERR_NOT_SET` if a value is missing, and
  `NML_ERR_INVALID_NAME`/`NML_ERR_INVALID_INDEX` on misuse.
- `NML_ERR_INVALID_HANDLE` only reports zero f2py handles. Non-zero invalid
  handles are outside the generated wrapper contract.

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

- No remote schema resolution.
- No composition keywords: `allOf`, `anyOf`, `oneOf`, `not`.
- No conditional keywords: `if`/`then`/`else`.
- No object constraints: `additionalProperties`, `patternProperties`,
  `propertyNames`, `dependencies`.
- No advanced array constraints: tuple typing, `contains`, `minItems`,
  `maxItems`, `uniqueItems`.
- No numeric or string validation keywords like `multipleOf`, `minLength`,
  `maxLength`, `pattern`, `format` (bounds are supported via `minimum`,
  `maximum`, `exclusiveMinimum`, and `exclusiveMaximum`).
- Object schemas are supported only as one-level referenced Fortran derived
  types with intrinsic scalar members.

Use the `x-fortran-*` extensions to express kind, length, and shape information
needed for code generation.

### Reusable definitions and references

Schemas may reuse supported scalar or scalar-array field definitions with JSON
Schema Draft 2020-12 `$defs` and `$ref`:

```yaml
x-fortran-namelist: solver
type: object
$defs:
  positive_count:
    type: integer
    minimum: 1
    x-fortran-kind: i4
properties:
  iterations:
    $ref: "#/$defs/positive_count"
    title: Iteration limit
    default: 100
```

References may target the same document or local `.yml`, `.yaml`, or `.json`
files, for example `common-definitions.yml#/$defs/fraction`. Relative file
paths are resolved from the file containing the `$ref`; no project registry or
network retrieval is used. Standard JSON Pointer fragments are supported.

Keywords next to `$ref` compose with the reusable definition. A use site may
narrow numeric bounds or enums, and its `title`, `description`, `examples`, or
`default` is used for generated output when present. Conflicting Fortran
representation keywords such as `x-fortran-kind`, `x-fortran-len`, and
`x-fortran-shape` are rejected. For arrays, a use-site array `default` replaces
the referenced default together with any `x-fortran-default-*` controls.

Referenced named object definitions may also represent one-level derived-type
properties through `x-fortran-type` and optional `x-fortran-module`. Type use
sites may refine existing scalar components but cannot add components or change
the Fortran type identity. `$id`/`$anchor` resolution, recursive references,
`$dynamicRef`, legacy `definitions`, and general composition keywords are not
supported.
