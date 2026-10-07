"""Configuration metadata and source-file dimension inference integration."""

from __future__ import annotations

import copy
import importlib
from pathlib import Path
from textwrap import dedent
from typing import Any

import click
import pytest
from click.testing import CliRunner

from nml_tools._dimensions import DimensionSource
from nml_tools.schema import SchemaResolver

cli: Any = importlib.import_module("nml_tools.cli")


@pytest.fixture
def project(tmp_path: Path) -> Path:
    (tmp_path / "settings.yml").write_text(
        dedent("""
        $defs:
          size:
            type: integer
            default: 7
            minimum: 1
        type: object
        x-fortran-namelist: Settings
        properties:
          Count:
            $ref: '#/$defs/size'
          weights:
            type: array
            items: {type: integer}
            x-fortran-shape: [n_values]
          required_other: {type: integer}
        required: [required_other]
        """),
        encoding="ascii",
    )
    (tmp_path / "data.yml").write_text(
        dedent("""
        type: object
        x-fortran-namelist: data
        properties:
          values:
            type: array
            items: {type: integer}
            x-fortran-shape: [n_values]
        required: [values]
        """),
        encoding="ascii",
    )
    config = tmp_path / "nml-config.toml"
    config.write_text(
        dedent("""
        [helper]
        path = "out/helper.f90"
        [kinds]
        module = "iso_fortran_env"
        [dimensions.n_values]
        default = 1
        source = { namelist = "SETTINGS", property = "COUNT" }
        [[namelists]]
        schema = "data.yml"
        mod_path = "out/data.f90"
        doc_path = "out/data.md"
        [[namelists]]
        schema = "settings.yml"
        mod_path = "out/settings.f90"
        doc_path = "out/settings.md"
        [[file_profiles]]
        name = "Main"
        default_file = "data.nml"
        namelists = ["data"]
        required = ["data"]
        [[file_profiles]]
        name = "Dimensions"
        default_file = "settings.nml"
        namelists = ["settings"]
        [[project_profiles]]
        name = "Standard"
        title = "Standard run"
        description = "Both configuration files."
        file_profiles = ["MAIN", "dimensions"]
        [[project_profiles]]
        name = "Minimal"
        file_profiles = ["main"]
        [[templates]]
        path = "out/data.nml"
        profile = "main"
        """),
        encoding="ascii",
    )
    (tmp_path / "data.nml").write_text("&data values=1,2,3 /", encoding="ascii")
    (tmp_path / "settings.nml").write_text("&settings count=3 /", encoding="ascii")
    return config


def load_metadata(config_path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    config, _ = cli._load_config_checked(config_path)
    registry = cli._namelist_registry_by_key(
        cli._load_namelist_registry(config, config_path.parent, SchemaResolver())
    )
    return config, registry


def test_metadata_is_retained_and_resolved(project: Path) -> None:
    config, registry = load_metadata(project)
    metadata = cli._load_config_metadata(config, registry)
    assert metadata.dimension_sources == {"n_values": DimensionSource("settings", "Count")}
    profile = metadata.project_profiles["standard"]
    assert profile.name == "Standard"
    assert profile.key == "standard"
    assert profile.title == "Standard run"
    assert profile.description == "Both configuration files."
    assert profile.file_profiles == ["main", "dimensions"]
    assert metadata.project_profiles["minimal"].file_profiles == ["main"]
    config["dimensions"]["Count"] = config["dimensions"].pop("n_values")
    del config["dimensions"]["Count"]["source"]["property"]
    assert cli._load_dimension_sources(config, registry) == {
        "count": DimensionSource("settings", "Count")
    }


def test_empty_metadata_and_overlapping_sources_are_allowed(project: Path) -> None:
    config, registry = load_metadata(project)
    file_profiles = cli._iter_file_profiles(config, registry)
    assert cli._iter_project_profiles({}, file_profiles) == {}
    assert cli._iter_project_profiles({"project_profiles": []}, file_profiles) == {}
    config["file_profiles"][0]["namelists"].append("settings")
    config["file_profiles"][0]["required"] = []
    assert cli._load_config_metadata(config, registry).project_profiles["standard"].file_profiles
    assert cli._load_dimension_sources({}, registry) == {}


@pytest.mark.parametrize(
    "source",
    [
        None,
        "settings",
        [],
        {},
        {"namelist": 3},
        {"namelist": ""},
        {"namelist": "unknown"},
        {"namelist": "settings", "property": "unknown"},
        {"namelist": "settings", "property": None},
        {"namelist": "settings", "property": ""},
        {"namelist": "settings", "property": "count(1)"},
        {"namelist": "settings", "property": "count%value"},
        {"namelist": "settings", "property": "weights"},
    ],
)
def test_invalid_source_metadata(project: Path, source: Any) -> None:
    config, registry = load_metadata(project)
    config["dimensions"]["n_values"]["source"] = source
    with pytest.raises(click.ClickException, match="dimension 'n_values' source"):
        cli._load_config_metadata(config, registry)


@pytest.mark.parametrize(
    "prop",
    [
        {"type": "number"},
        {"type": "boolean"},
        {"type": "string", "x-fortran-len": 3},
        {"type": "object", "properties": {"value": {"type": "integer"}}},
    ],
)
def test_source_requires_integer_scalar(project: Path, prop: dict[str, Any]) -> None:
    config, registry = load_metadata(project)
    registry["settings"].schema["properties"]["Count"] = prop
    with pytest.raises(click.ClickException, match="intrinsic integer scalar"):
        cli._load_config_metadata(config, registry)


@pytest.mark.parametrize(
    "entries",
    [
        None,
        {},
        "standard",
        [None],
        [{}],
        [{"name": ""}],
        [{"name": 3}],
        [{"name": "standard", "file_profiles": []}],
        [{"name": "standard", "file_profiles": "main"}],
        [{"name": "standard", "file_profiles": [None]}],
        [{"name": "standard", "file_profiles": [""]}],
        [{"name": "standard", "file_profiles": ["unknown"]}],
        [{"name": "standard", "file_profiles": ["main", "MAIN"]}],
        [{"name": "standard", "file_profiles": ["main"], "title": 3}],
        [{"name": "standard", "file_profiles": ["main"], "description": []}],
        [
            {"name": "standard", "file_profiles": ["main"]},
            {"name": "STANDARD", "file_profiles": ["dimensions"]},
        ],
    ],
)
def test_invalid_project_metadata(project: Path, entries: Any) -> None:
    config, registry = load_metadata(project)
    config["project_profiles"] = entries
    with pytest.raises(click.ClickException):
        cli._load_config_metadata(config, registry)


def run_validate(project: Path, *options: str) -> Any:
    return CliRunner().invoke(
        cli.cli, ["validate", "--config", str(project), *options, str(project.parent / "data.nml")]
    )


def test_dim_file_inference_with_profile_and_explicit_schema(project: Path) -> None:
    dim_file = str(project.parent / "settings.nml")
    for options in [("--profile", "MAIN"), ("--schema", str(project.parent / "data.yml")), ()]:
        result = run_validate(project, *options, "--dim-file", dim_file)
        assert result.exit_code == 0, result.output
    # Without the source file, the configured default of one is too small.
    assert run_validate(project).exit_code != 0
    # All target requirements still apply; context does not satisfy them.
    (project.parent / "data.nml").write_text("&data /", encoding="ascii")
    result = run_validate(project, "--dim-file", dim_file)
    assert result.exit_code != 0
    assert "missing required 'values'" in result.output


def test_same_file_sources_are_inferred_before_all_groups(project: Path) -> None:
    (project.parent / "data.nml").write_text(
        "&data values=1,2,3 / &settings weights=1,2,3 count=3 required_other=2 /",
        encoding="ascii",
    )
    result = run_validate(project)
    assert result.exit_code == 0, result.output


def test_dim_file_is_context_only_and_overrides_win(project: Path) -> None:
    dim_file = project.parent / "settings.nml"
    dim_file.write_text(
        "&unrelated ignored=1 / &settings count=2 weights=999*1 /", encoding="ascii"
    )
    result = run_validate(project, "--dim-file", str(dim_file), "--dimensions", "N_VALUES=3")
    assert result.exit_code == 0, result.output
    dim_file.write_text("&settings count=, /", encoding="ascii")
    (project.parent / "data.nml").write_text("&data values=1 /", encoding="ascii")
    result = run_validate(project, "--dim-file", str(dim_file))
    assert result.exit_code == 0, result.output


def test_dim_file_cannot_supply_required_target_group(project: Path) -> None:
    (project.parent / "data.nml").write_text("", encoding="ascii")
    result = run_validate(
        project, "--profile", "main", "--dim-file", str(project.parent / "settings.nml")
    )
    assert result.exit_code != 0
    assert "input is missing namelist 'data'" in result.output


def test_runtime_ambiguity_and_source_locations(project: Path) -> None:
    (project.parent / "data.nml").write_text(
        "&data values=1,2,3 / &settings count=3 required_other=2 /", encoding="ascii"
    )
    result = run_validate(project, "--dim-file", str(project.parent / "settings.nml"))
    assert result.exit_code != 0
    assert "ambiguous source namelist" in result.output
    assert "settings.nml:1:" in result.output
    # A source file cannot silently fall back when its explicit value is invalid.
    (project.parent / "data.nml").write_text("&data values=1,2,3 /", encoding="ascii")
    (project.parent / "settings.nml").write_text("&settings count=0 /", encoding="ascii")
    result = run_validate(project, "--dim-file", str(project.parent / "settings.nml"))
    assert result.exit_code != 0
    assert "settings.nml:1:" in result.output


def test_identical_paths_are_read_once(project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (project.parent / "data.nml").write_text(
        "&data values=1,2,3 / &settings count=3 required_other=2 /", encoding="ascii"
    )
    original = cli._read_namelist
    reads: list[Path] = []

    def read(path: Path) -> Any:
        reads.append(path)
        return original(path)

    monkeypatch.setattr(cli, "_read_namelist", read)
    result = run_validate(project, "--dim-file", str(project.parent / "." / "data.nml"))
    assert result.exit_code == 0, result.output
    assert len(reads) == 1


def test_dim_file_requires_config_and_reports_parse_errors(project: Path) -> None:
    result = CliRunner().invoke(
        cli.cli,
        [
            "validate",
            "--schema",
            str(project.parent / "data.yml"),
            "--dim-file",
            str(project.parent / "settings.nml"),
            str(project.parent / "data.nml"),
        ],
    )
    assert result.exit_code != 0
    assert "--dim-file requires config" in result.output
    (project.parent / "settings.nml").write_text("&settings count=3", encoding="ascii")
    result = run_validate(project, "--dim-file", str(project.parent / "settings.nml"))
    assert result.exit_code != 0
    assert "failed to parse namelist" in result.output
    assert "settings.nml" in result.output


@pytest.mark.parametrize(
    "command", ["generate", "check", "gen-fortran", "gen-markdown", "gen-template", "validate"]
)
@pytest.mark.parametrize("bad_metadata", ["source", "project"])
def test_commands_reject_metadata_before_writing(
    project: Path,
    command: str,
    bad_metadata: str,
) -> None:
    text = project.read_text(encoding="ascii")
    if bad_metadata == "source":
        text = text.replace('property = "COUNT"', 'property = "unknown"')
    else:
        text = text.replace('file_profiles = ["MAIN", "dimensions"]', 'file_profiles = ["unknown"]')
    project.write_text(text, encoding="ascii")
    args = [command, "--config", str(project)]
    if command == "validate":
        args.append(str(project.parent / "data.nml"))
    result = CliRunner().invoke(cli.cli, args)
    assert result.exit_code != 0
    assert "unknown" in result.output
    assert not (project.parent / "out").exists()


def test_metadata_does_not_change_generated_outputs(project: Path) -> None:
    config, _ = load_metadata(project)
    original = copy.deepcopy(config)
    original.pop("project_profiles")
    original["dimensions"]["n_values"].pop("source")
    assert cli._collect_generated_outputs(config, project) == cli._collect_generated_outputs(
        original, project
    )


def test_metadata_works_in_pyproject_tool_section(project: Path) -> None:
    text = project.read_text(encoding="ascii")
    # Prefix every table/array header while leaving inline tables intact.
    text = "\n".join(
        line.replace("[[", "[[tool.nml-tools.", 1)
        if line.startswith("[[")
        else line.replace("[", "[tool.nml-tools.", 1)
        if line.startswith("[")
        else line
        for line in text.splitlines()
    )
    pyproject = project.parent / "pyproject.toml"
    pyproject.write_text(text, encoding="ascii")
    config, registry = load_metadata(pyproject)
    assert cli._load_config_metadata(config, registry).project_profiles["standard"]
    result = run_validate(pyproject, "--dim-file", str(project.parent / "settings.nml"))
    assert result.exit_code == 0, result.output


@pytest.mark.parametrize(
    "options",
    [
        ["check", "--diff"],
        ["validate", "combined.nml"],
        ["validate", "--profile", "data", "--dim-file", "settings.nml", "data.nml"],
        [
            "validate",
            "--profile",
            "data",
            "--dim-file",
            "settings.nml",
            "--dimensions",
            "n_values=4",
            "data-override.nml",
        ],
        ["validate", "--profile", "data", "out/data-template.nml"],
    ],
)
def test_dimension_sources_example(options: list[str], monkeypatch: pytest.MonkeyPatch) -> None:
    example = Path(__file__).resolve().parents[1] / "examples" / "06_dimension_sources"
    monkeypatch.chdir(example)
    result = CliRunner().invoke(cli.cli, [options[0], "--config", "nml-config.toml", *options[1:]])
    assert result.exit_code == 0, result.output
