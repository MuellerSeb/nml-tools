# Dimension Sources Example

The config wires the runtime dimension `n_values` to `settings%count`. Its
configured default is two, while the sample settings explicitly supply three.
The source field has a different name from the dimension, avoiding generated
Fortran member name collisions.

From the repository root, infer the dimension from a combined file. The source
appears after the data array, which still validates against the inferred extent:

```bash
nml-tools validate --config examples/06_dimension_sources/nml-config.toml \
  examples/06_dimension_sources/combined.nml
```

Validate only the data file using the separate settings file as source context:

```bash
nml-tools validate --config examples/06_dimension_sources/nml-config.toml \
  --profile data --dim-file examples/06_dimension_sources/settings.nml \
  examples/06_dimension_sources/data.nml
```

Explicit dimensions take precedence over source values:

```bash
nml-tools validate --config examples/06_dimension_sources/nml-config.toml \
  --profile data --dim-file examples/06_dimension_sources/settings.nml \
  --dimensions n_values=4 examples/06_dimension_sources/data-override.nml
```

The `standard` project profile describes the two file profiles together. It
does not trigger project-wide validation or constrain dimension sources.

Generation uses the dimension default of two and does not read settings files:

```bash
nml-tools generate --config examples/06_dimension_sources/nml-config.toml
nml-tools check --config examples/06_dimension_sources/nml-config.toml --diff
nml-tools validate --config examples/06_dimension_sources/nml-config.toml \
  --profile data examples/06_dimension_sources/out/data-template.nml
```

The generated template has two values. With no source group present, validation
falls back to the configured dimension default.
