# File Profiles Example

This example shows how `[[file_profiles]]` can define named combinations of
namelists for a small project.

The config defines three namelists:

- `run`
- `physics`
- `outputs`

It groups them into two logical files:

- `main`, with the `run` and `physics` namelists and a `run.nml` default file hint;
  `run` is required and `physics` is optional
- `outputs`, with the `outputs` namelist and an `outputs.nml` default file hint;
  `outputs` is required

Generate the templates with:

```bash
nml-tools gen-template --config examples/05_file_profiles/nml-config.toml
```

Validate the sample files with:

```bash
nml-tools validate --config examples/05_file_profiles/nml-config.toml --profile main examples/05_file_profiles/run.nml
nml-tools validate --config examples/05_file_profiles/nml-config.toml --profile outputs examples/05_file_profiles/outputs.nml
```
