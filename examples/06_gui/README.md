# Example 06: GUI configuration

This example uses the `nml-tools` GUI to configure a small multi-body gravity
simulation. It demonstrates scalar and array fields for integers, floating-point
numbers, strings, booleans, file paths, and date-times. Four namelist schemas are
split across two output-file profiles.

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
06_gui/
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

The profiles in this example are:

- `simulation`: `run`, `gravity`, and `bodies` → `simulation.nml`
- `reporting`: `run` and `outputs` → `reporting.nml`

The shared `run` namelist appears in both files and can be edited independently.

## Run the example

From the repository root:

```bash
mkdir -p examples/06_gui/out
nml-tools gui -i examples/06_gui -o examples/06_gui/out
```

Or from this directory:

```bash
nml-tools gui -i . -o out
```

In the initial Config tab, keep or change `n_bodies` and `n_snapshots`, then
click **Run**. Edit each profile and use **Save** or **Save all**. File browser
selections are stored relative to `out`, which is why the supplied defaults use
paths such as `../input/body_1.csv`.

## Expected output

After saving both profiles, `out` contains:

```text
out/
├── simulation.nml
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

Running the same command again reloads existing values from these namelist files.
