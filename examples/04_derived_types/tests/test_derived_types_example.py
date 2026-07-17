from __future__ import annotations

import pytest

example = pytest.importorskip("nml_derived_types_example")


def _set_complete_config(cfg: object) -> None:
    cfg.set(
        period={"start_year": 2001, "end_year": 2010, "label": "present"},
        periods=[
            {"start_year": 1980, "end_year": 1990},
            {"start_year": 1991, "end_year": 2000, "label": "future"},
        ],
        station={"code": 7, "label": "central"},
    )


def test_nested_mappings_update_local_and_imported_types() -> None:
    example.reset_config()
    cfg = example.get_config()

    _set_complete_config(cfg)
    cfg.is_valid()

    assert example.get_period_start() == 2001
    assert example.get_period_item_starts() == (1980, 1991)
    assert example.get_station_code() == 7
    assert example.get_station_label() == "central"
    assert cfg.is_set("period")
    assert cfg.is_set("period.start_year")
    assert cfg.is_set("periods.start_year", idx=2)


def test_object_and_item_defaults_allow_partial_or_omitted_nested_mappings() -> None:
    example.reset_config()
    cfg = example.get_config()

    cfg.set(period={"end_year": 2010}, station={"code": 7})
    cfg.is_valid()

    assert example.get_period_start() == 2000
    assert example.get_period_item_starts() == (1980, 1980)


def test_imported_character_component_uses_schema_length_contract() -> None:
    example.reset_config()
    cfg = example.get_config()
    cfg.set(
        period={"start_year": 2001, "end_year": 2010},
        periods=[
            {"start_year": 1980, "end_year": 1990},
            {"start_year": 1991, "end_year": 2000},
        ],
        station={"code": 8, "label": "station-name"},
    )

    assert example.get_station_label() == "station-"


def test_nested_unknown_member_is_rejected_before_fortran_call() -> None:
    example.reset_config()
    cfg = example.get_config()

    with pytest.raises(ValueError, match="unknown member"):
        cfg.set(
            period={"start_year": 2001, "end_year": 2010, "unknown": 1},
            periods=[
                {"start_year": 1980, "end_year": 1990},
                {"start_year": 1991, "end_year": 2000},
            ],
            station={"code": 7},
        )


def test_missing_required_nested_leaf_is_invalid() -> None:
    example.reset_config()
    cfg = example.get_config()
    cfg.set(
        period={"start_year": 2001},
        periods=[
            {"start_year": 1980, "end_year": 1990},
            {"start_year": 1991, "end_year": 2000},
        ],
        station={"code": 7},
    )

    with pytest.raises(example.NmlError):
        cfg.is_valid()


def test_nested_component_bounds_are_checked_in_native_validation() -> None:
    example.reset_config()
    cfg = example.get_config()
    cfg.set(
        period={"start_year": 1700, "end_year": 2010},
        periods=[
            {"start_year": 1980, "end_year": 1990},
            {"start_year": 1991, "end_year": 2000},
        ],
        station={"code": 7},
    )

    with pytest.raises(example.NmlError, match="bounds constraint failed"):
        cfg.is_valid()
