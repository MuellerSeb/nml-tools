# Example 07: GUI project profiles

This example uses the `nml-tools` GUI to configure a small multi-body gravity
simulation. It demonstrates scalar and array fields for integers, floating-point
numbers, strings, booleans, file paths, and date-times. Four namelist schemas are
split across three file profiles and reused by two project profiles.

## Requirements and installation

`nml-tools` requires Python 3.9 or newer. The GUI additionally needs the GUI
extra and one Qt binding. From a source checkout, install it with:

```bash
python -m pip install -e '.[gui]' PyQt5
```

For an installed release, use:

```bash
python -m pip install 'nml-tools[gui]' PyQt5
```

`PyQt6`, `PySide2`, or `PySide6` may be used instead of `PyQt5`. Install only
one binding in a clean environment when possible. The GUI extra installs QtPy,
guidata, and NumPy.

## Example layout

```text
07_gui/
├── nml-config.toml       # dimensions, schemas, and file profiles
├── schemas/              # four JSON Schema-compatible YAML files
│   ├── run.yml
│   ├── gravity.yml
│   ├── bodies.yml
│   └── outputs.yml
├── input/                # files selectable by file-path fields
│   ├── restart_state.dat
│   ├── body_1.csv
│   ├── body_2.csv
│   └── body_3.csv
└── out/                  # generated after saving in the GUI
```

The input directory passed to the GUI must contain `nml-config.toml`; schema
paths in that file are relative to the same directory. The output directory must
be writable. It may be empty initially.

The file profiles are:

- `setup`: `run` and `gravity` → `setup.nml`
- `bodies`: `bodies` → `bodies.nml`
- `reporting`: `outputs` → `reporting.nml`

The project profiles are:

- `simulation`: `setup` and `bodies`
- `report_preview`: `setup` and `reporting`

This demonstrates how projects can reuse the same `setup` file profile while
presenting only the files relevant to each workflow.

## Run the example

From the repository root:

```bash
mkdir -p examples/07_gui/out
nml-tools gui -i examples/07_gui -o examples/07_gui/out
```

Or from this directory:

```bash
nml-tools gui -i . -o out
```

Choose a project in the project selector and click **Add**. Its two file profiles
appear in the project tree and as editable tabs. Use **Save** or **Save all** to
write their namelist files. File browser selections are stored relative to
`out`, which is why the supplied defaults use paths such as
`../input/body_1.csv`.

## Expected output

After adding and saving both project profiles, `out` contains:

```text
out/
├── setup.nml
├── bodies.nml
└── reporting.nml
```

Arrays are written with explicit Fortran indices, for example:

```fortran
&gravity
  axis_codes(1) = 1
  axis_codes(2) = 2
  axis_codes(3) = 3
  gravity_vector(1) = 0.0
  gravity_vector(2) = 0.0
  gravity_vector(3) = -9.81
/
```

Only files belonging to the selected project need to be saved. Running the same
command again reloads existing values from the namelist files that are present.
