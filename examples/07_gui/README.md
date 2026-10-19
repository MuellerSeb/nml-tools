# Example 07: GUI project profiles

This example configures a small multi-body gravity simulation with the
`nml-tools` GUI. It demonstrates project and file profiles, scalar fields,
one-dimensional arrays, integers, floating-point numbers, strings, booleans,
file paths, date-times, defaults, examples, and schema descriptions.

Four namelist schemas are split across three reusable file profiles:

- `setup`: `run` and `gravity` → `setup.nml`
- `bodies`: `bodies` → `bodies.nml`
- `reporting`: `outputs` → `reporting.nml`

The configured project profiles are:

- `simulation`: `setup` and `bodies`
- `report_preview`: `setup` and `reporting`

This shows how two projects can share the same setup while exposing only their
relevant namelist files.

## Install the GUI

`nml-tools` requires Python 3.8 or newer. Install the GUI extra and one Qt
binding. From the root of a source checkout:

```bash
python -m pip install -e '.[gui]' PyQt5
```

For an installed release:

```bash
python -m pip install 'nml-tools[gui]' PyQt5
```

`PyQt6`, `PySide2`, or `PySide6` may be used instead of `PyQt5`. Prefer one Qt
binding per environment. The GUI extra installs QtPy, guidata, and NumPy.

## Example layout

```text
07_gui/
├── launch_gui.sh          # double-click launcher for Linux
├── launch_gui.command     # double-click launcher for macOS
├── launch_gui.bat         # double-click launcher for Windows
├── nml-config.toml        # dimensions, schemas, and profiles
├── schemas/
│   ├── run.yml
│   ├── gravity.yml
│   ├── bodies.yml
│   └── outputs.yml
├── input/                # files selectable from path fields
│   ├── restart_state.dat
│   ├── body_1.csv
│   ├── body_2.csv
│   └── body_3.csv
└── out/                  # sample and newly saved namelist files
    ├── setup.nml
    ├── bodies.nml
    └── reporting.nml
```

The schema directory supplied with `-i` must contain `nml-config.toml`. Schema
paths are resolved from that directory. The directory supplied with `-o` must
be writable. Existing profile namelists are read from it when a project is
loaded; otherwise the GUI starts with schema defaults and example hints.

## Open the example

After installation, double-click the launcher for your platform:

- Linux: `launch_gui.sh` and choose **Run** if prompted.
- macOS: `launch_gui.command`.
- Windows: `launch_gui.bat`.

Linux and macOS launchers must remain executable. All launchers change to this
directory and run:

```bash
nml-tools gui -i ./ -o ./out
```

The `nml-tools` executable must be available on the desktop session's `PATH`.
You can always run the same command in a terminal from this directory.

## GUI workflow

1. Select `Full simulation` or `Reporting preview` in **Load project**, then
   click **+** to add it to the project tree.
2. Expand the project and select a file profile or namelist. The matching tab
   and namelist page are selected automatically.
3. Use the **⚙️** tab to change dimensions or compose a custom file profile.
4. Edit values. Descriptions are available from the blue information buttons;
   default and example hints can be accepted with **Tab**.
5. Use **Save** for one file profile or **Save all** for the loaded project.

One- and two-dimensional arrays are edited directly in their namelist pages;
higher-dimensional arrays use the guidata array editor. Array values are saved
with explicit one-based Fortran indices. File browsers store paths relative to
the output directory where possible.

The project selector can also browse an additional project-profile TOML file.
Selecting `<new>` lets you compose a custom project from configured schemas and
file profiles; saved custom projects can be loaded again later.

The `n_bodies` dimension is linked to `run%body_count`. To test dimension
references and array resizing, open **Full simulation**, select the **⚙️** tab,
reduce `n_bodies`, and click **Run**. The body tables and the read-only
`body_count` field follow the new size. **Save all** writes both the source value
and the resized arrays, and reopening the project recovers the saved dimension.
Dimension-dependent defaults use one-element repeat seeds so they remain valid
for every positive `n_bodies` value; the three-body examples remain available
as hints and in the supplied sample namelists.

Applications may open a project directly through the public API:

```python
from nml_tools.gui import launch_gui

launch_gui("examples/07_gui", "examples/07_gui/out", "simulation")
```

Passing the project-profile name preloads it into the project tree. Omitting the
third argument leaves the tree empty so the user can choose a project.

## Expected output

The supplied `out` directory contains sample files so the reload workflow can
be tried immediately. Saving both configured projects produces or updates:

```text
out/
├── setup.nml
├── bodies.nml
└── reporting.nml
```

Arrays use indexed assignments such as:

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

Only files belonging to loaded projects are changed. Reopening the example
loads values already present in each profile's namelist file.
