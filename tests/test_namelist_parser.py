"""Tests for the private lossless Fortran namelist parser."""

from __future__ import annotations

import pytest

from nml_tools._namelist_parser import (
    DecimalMode,
    NullValue,
    RepeatedValue,
    ScalarSelector,
    SectionSelector,
    parse_namelist,
)


def test_parser_preserves_groups_assignments_spelling_and_locations() -> None:
    parsed = parse_namelist(
        "\n&Run\n  Value = 1\n/\n&Run\n  value = 2\n/\n",
        source="run.nml",
    )
    assert [group.name for group in parsed.groups] == ["Run", "Run"]
    first = parsed.groups[0].assignments[0]
    assert first.designator.source_text == "Value"
    assert first.span.start.line == 3
    assert first.span.start.column == 3


def test_comments_records_and_character_contents_do_not_terminate_groups() -> None:
    parsed = parse_namelist(
        "&text ! group comment\n"
        "value = 'a,!/''quoted' ! / ignored\n"
        "continued = \"first\nsecond\"\n"
        "/\n"
    )
    assignments = parsed.groups[0].assignments
    assert len(assignments) == 2
    assert assignments[0].values[0].source_text == "'a,!/''quoted'"  # type: ignore[union-attr]
    assert "\n" in assignments[1].values[0].source_text  # type: ignore[union-attr]


def test_designators_preserve_scalar_sections_and_multiple_selector_groups() -> None:
    parsed = parse_namelist(
        "&run\nsettings(2:1:-1,3)%label(2:4) = 'abc'\n/"
    )
    designator = parsed.groups[0].assignments[0].designator
    assert [part.name for part in designator.parts] == ["settings", "label"]
    root_selectors = designator.parts[0].selectors[0].selectors
    assert isinstance(root_selectors[0], SectionSelector)
    assert (root_selectors[0].lower, root_selectors[0].upper, root_selectors[0].stride) == (
        2,
        1,
        -1,
    )
    assert isinstance(root_selectors[1], ScalarSelector)
    substring = designator.parts[1].selectors[0].selectors[0]
    assert isinstance(substring, SectionSelector)


def test_parser_preserves_nulls_repetitions_and_blank_separated_values() -> None:
    parsed = parse_namelist("&run\nvalues = , 2*3 2* , 4\n/")
    values = parsed.groups[0].assignments[0].values
    assert isinstance(values[0], NullValue)
    assert isinstance(values[1], RepeatedValue)
    assert values[1].count == 2
    assert isinstance(values[2], RepeatedValue)
    assert isinstance(values[2].value, NullValue)
    assert values[3].source_text == "4"  # type: ignore[union-attr]


def test_end_of_record_is_not_a_null_separator() -> None:
    parsed = parse_namelist("&run\nvalues = 1\n  2\nnext = 3\n/")
    first, second = parsed.groups[0].assignments
    assert len(first.values) == 2
    assert second.designator.source_text == "next"


def test_point_and_comma_decimal_modes_have_distinct_value_separators() -> None:
    point = parse_namelist("&run\nvalues = 1.5, 2.5\n/")
    comma = parse_namelist(
        "&run\nvalues = 1,5; 2,5\n/",
        decimal_mode=DecimalMode.COMMA,
    )
    assert [value.source_text for value in point.groups[0].assignments[0].values] == [  # type: ignore[union-attr]
        "1.5",
        "2.5",
    ]
    assert [value.source_text for value in comma.groups[0].assignments[0].values] == [  # type: ignore[union-attr]
        "1,5",
        "2,5",
    ]

    complex_value = parse_namelist(
        "&run\nvalue = (1,5; -2,25)\n/",
        decimal_mode=DecimalMode.COMMA,
    ).groups[0].assignments[0].values[0]
    assert complex_value.source_text == "(1,5; -2,25)"  # type: ignore[union-attr]


@pytest.mark.parametrize(
    ("text", "match"),
    [
        ("$run\nvalue=1\n$end", "'\\$' group syntax is not standard"),
        ("&run\nvalue=1\n&end", "'&end' is not a standard group terminator"),
        ("&run\n# comment\nvalue=1\n/", "'#' comments are not standard"),
        ("&run/value=1/", "group name must be separated"),
        ("& run\nvalue=1\n/", "group name must follow '&' immediately"),
        ("&run\nvalue (1)=1\n/", "designator must not contain embedded blanks"),
        ("&run\nvalue=1! invalid comment\n/", "comment must follow a value separator"),
        ("&run\nvalue=1", "unterminated namelist group"),
        ("&run\nvalue=1_i4\n/", "kind suffixes are not permitted"),
        ("&run\nvalue=1_8\n/", "kind suffixes are not permitted"),
        ("&run\nvalue='abc'_char_kind\n/", "kind suffixes are not permitted"),
        ("&run\nvalue(i)=1\n/", "subscripts and bounds must be integer literals"),
        ("&run\nvalue(::0)=1\n/", "stride must not be zero"),
        ("unexpected", "expected '&'"),
    ],
)
def test_parser_rejects_extensions_and_malformed_syntax(text: str, match: str) -> None:
    with pytest.raises(ValueError, match=match):
        parse_namelist(text, source="bad.nml")


def test_slash_in_comment_and_empty_group_are_supported() -> None:
    parsed = parse_namelist("&empty\n! / is ignored\n/\n")
    assert parsed.groups[0].assignments == ()


def test_parser_preserves_complex_values_without_interpreting_parts() -> None:
    parsed = parse_namelist("&run\nvalue = (NaN(payload)\n,\n -2.0)\n/")
    value = parsed.groups[0].assignments[0].values[0]
    assert value.source_text == "(NaN(payload)\n,\n -2.0)"  # type: ignore[union-attr]
