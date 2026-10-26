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

Both projects use the `setup` definition, but each owns a separate physical
`setup.nml` in its output directory. Editing one project therefore cannot
overwrite the other project's settings.

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
└── out/                  # one independent directory per project
    ├── simulation/
    │   ├── setup.nml
    │   └── bodies.nml
    └── report_preview/
        ├── setup.nml
        └── reporting.nml
```

The schema directory must contain `nml-config.toml`. Each loaded project also
needs its own writable output directory. Existing namelists are read from that
project's directory; otherwise its forms start with schema defaults and example
hints.

## Open the example

After installation, double-click the launcher for your platform:

- Linux: `launch_gui.sh` and choose **Run** if prompted.
- macOS: `launch_gui.command`.
- Windows: `launch_gui.bat`.

Linux and macOS launchers must remain executable. Each launcher changes to this
example directory and runs:

```bash
nml-tools gui
```

With no options, the current directory is both the schema/config directory and
the initial namelist output directory. Select a project with **+**, then use its
**⚙️** tab to choose a different output directory when needed.

## GUI workflow

1. Select a project under **Load project** and add it with **+**.
2. Expand the project and select a file profile or namelist. The matching tab
   and namelist page are selected automatically.
3. Use the **⚙️** tab to select that project's output directory, change
   dimensions, or compose a custom file profile.
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

Applications may preload a project with its complete runtime configuration:

```python
from nml_tools.gui import GuiProjectRequest, launch_gui

launch_gui(
    "examples/07_gui",
    [GuiProjectRequest("simulation", "examples/07_gui/out/simulation")],
)
```

Omitting project requests leaves the tree empty so the user can choose a project.

## Expected output

The supplied `out` directory contains sample files so the reload workflow can
be tried immediately. Saving both configured projects produces or updates:

```text
out/
├── simulation/
│   ├── setup.nml
│   └── bodies.nml
└── report_preview/
    ├── setup.nml
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

Only files belonging to the active project are saved. Reopening the example
loads each project's values from its own directory, including its independent
copy of `setup.nml`.
