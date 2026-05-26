# Reusable Schema Reference Example

This example demonstrates `$defs` and `$ref` support across two namelists:

- `schema/common-definitions.yml` is a shared definition library.
- `schema/run-base.yml` is a reusable root object and itself references the
  shared definition library.
- `schema/run.yml` references that root object, refines inherited properties,
  and contains one same-file definition.
- `schema/report.yml` reuses the same external definitions directly.

The schemas illustrate:

- same-file and external local references;
- a chained external reference resolved relative to its containing file;
- root-level `properties` and `required` composition;
- use-site titles, descriptions, and defaults;
- narrowed numeric constraints;
- an inherited definition-level default;
- a replaced array default bundle using a runtime `[dimensions]` extent;
- config `[constants]` used through a referenced string definition.

From the repository root, generate and check the committed artifacts:

```bash
nml-tools generate --config examples/03_references/nml-config.toml
nml-tools check --config examples/03_references/nml-config.toml --diff
```

Validate the generated filled namelist template:

```bash
nml-tools validate --config examples/03_references/nml-config.toml \
  examples/03_references/out/reference-demo.nml
```

References remain local and offline. Network references, recursive references,
and object-valued fields for derived types are intentionally not part of this
example.
