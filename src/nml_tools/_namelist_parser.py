"""Private, lossless parser for standard formatted Fortran namelist input."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import NoReturn, Union


class DecimalMode(str, Enum):
    """External-unit decimal editing mode."""

    POINT = "POINT"
    COMMA = "COMMA"


@dataclass(frozen=True)
class SourcePosition:
    offset: int
    line: int
    column: int


@dataclass(frozen=True)
class SourceSpan:
    start: SourcePosition
    end: SourcePosition


class NamelistError(ValueError):
    """Base class for source-located namelist errors."""

    category = "namelist"

    def __init__(self, message: str, *, source: str, span: SourceSpan) -> None:
        self.message = message
        self.source = source
        self.span = span
        super().__init__(self.__str__())

    def __str__(self) -> str:
        position = self.span.start
        return (
            f"{self.source}:{position.line}:{position.column}: "
            f"{self.category} error: {self.message}"
        )


class NamelistSyntaxError(NamelistError):
    category = "syntax"


@dataclass(frozen=True)
class ScalarSelector:
    value: int
    span: SourceSpan


@dataclass(frozen=True)
class SectionSelector:
    lower: int | None
    upper: int | None
    stride: int | None
    span: SourceSpan


Selector = Union[ScalarSelector, SectionSelector]


@dataclass(frozen=True)
class SelectorGroup:
    selectors: tuple[Selector, ...]
    span: SourceSpan


@dataclass(frozen=True)
class DesignatorPart:
    name: str
    selectors: tuple[SelectorGroup, ...]
    span: SourceSpan


@dataclass(frozen=True)
class Designator:
    parts: tuple[DesignatorPart, ...]
    source_text: str
    span: SourceSpan


@dataclass(frozen=True)
class RawValue:
    source_text: str
    quoted: bool
    span: SourceSpan


@dataclass(frozen=True)
class NullValue:
    span: SourceSpan


@dataclass(frozen=True)
class RepeatedValue:
    count: int
    value: RawValue | NullValue
    span: SourceSpan


ParsedValue = Union[RawValue, NullValue, RepeatedValue]


@dataclass(frozen=True)
class Assignment:
    designator: Designator
    values: tuple[ParsedValue, ...]
    span: SourceSpan


@dataclass(frozen=True)
class ParsedGroup:
    name: str
    assignments: tuple[Assignment, ...]
    span: SourceSpan


@dataclass(frozen=True)
class ParsedFile:
    groups: tuple[ParsedGroup, ...]
    source: str


@dataclass(frozen=True)
class _Token:
    kind: str
    text: str
    span: SourceSpan


_PUNCTUATION = {
    "&": "AMP",
    "/": "SLASH",
    "=": "EQUAL",
    "%": "PERCENT",
    "(": "LPAREN",
    ")": "RPAREN",
    ":": "COLON",
    ",": "COMMA",
    ";": "SEMICOLON",
    "*": "STAR",
}


def parse_namelist(
    text: str,
    *,
    source: str = "<input>",
    decimal_mode: DecimalMode = DecimalMode.POINT,
) -> ParsedFile:
    """Parse *text* into an ordered, source-located namelist IR."""
    parser = _Parser(text, source=source, decimal_mode=decimal_mode)
    return parser.parse()


class _Scanner:
    def __init__(self, text: str, source: str) -> None:
        self.text = text
        self.source = source
        self.offset = 0
        self.line = 1
        self.column = 1

    def scan(self) -> list[_Token]:
        tokens: list[_Token] = []
        while self.offset < len(self.text):
            char = self.text[self.offset]
            if char in " \t\f\v":
                self._advance(char)
                continue
            if char in "\r\n":
                start = self._position()
                self._consume_newline()
                tokens.append(_Token("EOR", "\n", SourceSpan(start, self._position())))
                continue
            if char == "!":
                if not self._comment_is_permitted():
                    self._error(
                        "a namelist comment must follow a value separator or start a record",
                        self._single_span(),
                    )
                self._skip_comment()
                continue
            if char == "#":
                self._error("'#' comments are not standard; use '!'", self._single_span())
            if char == "$":
                if self._at_first_nonblank_of_record():
                    self._error(
                        "'$' group syntax is not standard; use '&name' and '/'",
                        self._single_span(),
                    )
            if char in {"'", '"'}:
                tokens.append(self._scan_string(char))
                continue
            kind = _PUNCTUATION.get(char)
            if kind is not None:
                start = self._position()
                self._advance(char)
                tokens.append(_Token(kind, char, SourceSpan(start, self._position())))
                continue
            tokens.append(self._scan_word())
        position = self._position()
        tokens.append(_Token("EOF", "", SourceSpan(position, position)))
        return tokens

    def _scan_word(self) -> _Token:
        start = self._position()
        start_offset = self.offset
        while self.offset < len(self.text):
            char = self.text[self.offset]
            if char.isspace() or char in _PUNCTUATION or char in {"!", "#", "'", '"'}:
                break
            self._advance(char)
        if self.offset == start_offset:
            self._error(f"unexpected character {self.text[self.offset]!r}", self._single_span())
        return _Token(
            "WORD",
            self.text[start_offset : self.offset],
            SourceSpan(start, self._position()),
        )

    def _scan_string(self, delimiter: str) -> _Token:
        start = self._position()
        start_offset = self.offset
        self._advance(delimiter)
        while self.offset < len(self.text):
            char = self.text[self.offset]
            if char == delimiter:
                self._advance(char)
                if self.offset < len(self.text) and self.text[self.offset] == delimiter:
                    self._advance(delimiter)
                    continue
                return _Token(
                    "STRING",
                    self.text[start_offset : self.offset],
                    SourceSpan(start, self._position()),
                )
            if char in "\r\n":
                self._consume_newline()
            else:
                self._advance(char)
        self._error("unterminated character value", SourceSpan(start, self._position()))

    def _skip_comment(self) -> None:
        while self.offset < len(self.text) and self.text[self.offset] not in "\r\n":
            self._advance(self.text[self.offset])

    def _comment_is_permitted(self) -> bool:
        record_start = max(
            self.text.rfind("\n", 0, self.offset),
            self.text.rfind("\r", 0, self.offset),
        ) + 1
        prefix = self.text[record_start : self.offset]
        if not prefix.strip():
            return True
        return bool(prefix) and (prefix[-1].isspace() or prefix[-1] in {",", ";"})

    def _at_first_nonblank_of_record(self) -> bool:
        record_start = max(
            self.text.rfind("\n", 0, self.offset),
            self.text.rfind("\r", 0, self.offset),
        ) + 1
        return not self.text[record_start : self.offset].strip()

    def _consume_newline(self) -> None:
        if self.text[self.offset] == "\r":
            self.offset += 1
            if self.offset < len(self.text) and self.text[self.offset] == "\n":
                self.offset += 1
        else:
            self.offset += 1
        self.line += 1
        self.column = 1

    def _advance(self, char: str) -> None:
        self.offset += 1
        self.column += 1

    def _position(self) -> SourcePosition:
        return SourcePosition(self.offset, self.line, self.column)

    def _single_span(self) -> SourceSpan:
        start = self._position()
        return SourceSpan(start, SourcePosition(start.offset + 1, start.line, start.column + 1))

    def _error(self, message: str, span: SourceSpan) -> NoReturn:
        raise NamelistSyntaxError(message, source=self.source, span=span)


class _Parser:
    def __init__(self, text: str, *, source: str, decimal_mode: DecimalMode) -> None:
        self.text = text
        self.source = source
        self.decimal_mode = decimal_mode
        self.tokens = _Scanner(text, source).scan()
        self.index = 0

    def parse(self) -> ParsedFile:
        groups: list[ParsedGroup] = []
        self._skip_eor()
        while not self._at("EOF"):
            if not self._at("AMP"):
                self._error("expected '&' followed by a namelist group name", self._peek().span)
            groups.append(self._parse_group())
            self._skip_eor()
        return ParsedFile(tuple(groups), self.source)

    def _parse_group(self) -> ParsedGroup:
        amp = self._consume("AMP")
        start = amp.span.start
        name_token = self._consume("WORD", "expected a group name immediately after '&'")
        if name_token.span.start.offset != amp.span.end.offset:
            self._error("group name must follow '&' immediately", name_token.span)
        if not _is_identifier(name_token.text):
            self._error(f"invalid namelist group identifier {name_token.text!r}", name_token.span)
        if name_token.text.lower() == "end":
            self._error("'&end' is not a standard group terminator; use '/'", name_token.span)
        next_token = self._peek()
        separator = self.text[name_token.span.end.offset : next_token.span.start.offset]
        if next_token.kind != "EOR" and not any(char.isspace() for char in separator):
            self._error("group name must be separated from its contents", next_token.span)

        assignments: list[Assignment] = []
        self._skip_eor()
        while not self._at("SLASH"):
            if self._at("EOF"):
                self._error(f"unterminated namelist group '{name_token.text}'", self._peek().span)
            if self._at("AMP"):
                self._error("'&end' is not a standard group terminator; use '/'", self._peek().span)
            if self._at_value_separator():
                self.index += 1
                self._skip_eor()
                continue
            assignments.append(self._parse_assignment())
            self._skip_eor()
        end = self._consume("SLASH").span.end
        return ParsedGroup(name_token.text, tuple(assignments), SourceSpan(start, end))

    def _parse_assignment(self) -> Assignment:
        designator = self._parse_designator()
        self._consume("EQUAL", f"expected '=' after designator '{designator.source_text}'")
        values = self._parse_values()
        end = values[-1].span.end if values else designator.span.end
        return Assignment(designator, tuple(values), SourceSpan(designator.span.start, end))

    def _parse_values(self) -> list[ParsedValue]:
        values: list[ParsedValue] = []
        expecting_value = True
        saw_separator = False
        while True:
            self._skip_eor()
            if self._at("SLASH") or self._at("EOF") or self._starts_assignment():
                return values
            if self._at("AMP"):
                self._error("'&end' is not a standard group terminator; use '/'", self._peek().span)
            if self._at_value_separator():
                separator = self._peek()
                self.index += 1
                if expecting_value and (not values or saw_separator):
                    values.append(NullValue(separator.span))
                expecting_value = True
                saw_separator = True
                continue
            value = self._parse_value()
            values.append(value)
            expecting_value = False
            saw_separator = False

    def _parse_value(self) -> ParsedValue:
        token = self._peek()
        if (
            token.kind == "WORD"
            and _is_unsigned_integer(token.text)
            and self._peek(1).kind == "STAR"
        ):
            count_token = self._consume("WORD")
            count = int(count_token.text)
            if count <= 0:
                self._error("repeat count must be positive", count_token.span)
            self._consume("STAR")
            if (
                self._at("SLASH")
                or self._at("EOF")
                or self._at("EOR")
                or self._at_value_separator()
                or self._starts_assignment()
            ):
                null = NullValue(SourceSpan(count_token.span.end, self._peek().span.start))
                return RepeatedValue(count, null, SourceSpan(count_token.span.start, null.span.end))
            repeated = self._parse_raw_value()
            return RepeatedValue(
                count,
                repeated,
                SourceSpan(count_token.span.start, repeated.span.end),
            )
        return self._parse_raw_value()

    def _parse_raw_value(self) -> RawValue:
        token = self._peek()
        if token.kind == "STRING":
            self.index += 1
            suffix = self._peek()
            if (
                suffix.kind == "WORD"
                and suffix.text.startswith("_")
                and suffix.span.start.offset == token.span.end.offset
            ):
                self._error(
                    "kind suffixes are not permitted in namelist input constants",
                    suffix.span,
                )
            return RawValue(token.text, True, token.span)
        if token.kind == "LPAREN":
            start = token.span.start
            self.index += 1
            self._skip_eor()
            self._parse_complex_part("real")
            self._skip_eor()
            separator_kind = "COMMA" if self.decimal_mode is DecimalMode.POINT else "SEMICOLON"
            self._consume(separator_kind, "complex parts use the decimal-mode value separator")
            self._skip_eor()
            self._parse_complex_part("imaginary")
            self._skip_eor()
            end = self._consume("RPAREN", "expected ')' after a complex value").span.end
            return RawValue(self.text[start.offset : end.offset], False, SourceSpan(start, end))
        if token.kind != "WORD":
            self._error("expected a namelist input value", token.span)
        self.index += 1
        if _has_kind_suffix(token.text):
            self._error("kind suffixes are not permitted in namelist input constants", token.span)
        if token.text.lower().lstrip("+-") in {"nan", "snan"} and self._at("LPAREN"):
            self.index += 1
            while not self._at("RPAREN"):
                if self._at("EOF") or self._at("EOR"):
                    self._error("unterminated IEEE NaN input value", token.span)
                self.index += 1
            end = self._consume("RPAREN").span.end
            span = SourceSpan(token.span.start, end)
            return RawValue(self.text[span.start.offset : span.end.offset], False, span)
        if self.decimal_mode is DecimalMode.COMMA and self._at("COMMA"):
            comma = self._peek()
            following = self._peek(1)
            if (
                following.kind == "WORD"
                and comma.span.start.offset == token.span.end.offset
                and following.span.start.offset == comma.span.end.offset
                and _looks_numeric(token.text)
                and _looks_numeric(following.text)
            ):
                self.index += 2
                span = SourceSpan(token.span.start, following.span.end)
                return RawValue(self.text[span.start.offset : span.end.offset], False, span)
        return RawValue(token.text, False, token.span)

    def _parse_complex_part(self, label: str) -> None:
        token = self._consume("WORD", f"expected the {label} part of a complex value")
        if _has_kind_suffix(token.text):
            self._error("kind suffixes are not permitted in namelist input constants", token.span)
        if token.text.lower().lstrip("+-") in {"nan", "snan"} and self._at("LPAREN"):
            self.index += 1
            while not self._at("RPAREN"):
                if self._at("EOF") or self._at("EOR"):
                    self._error("unterminated IEEE NaN input value", token.span)
                self.index += 1
            self.index += 1
        if self.decimal_mode is not DecimalMode.COMMA or not self._at("COMMA"):
            return
        comma = self._peek()
        following = self._peek(1)
        if (
            following.kind == "WORD"
            and comma.span.start.offset == token.span.end.offset
            and following.span.start.offset == comma.span.end.offset
            and _looks_numeric(token.text)
            and _looks_numeric(following.text)
        ):
            self.index += 2

    def _parse_designator(self) -> Designator:
        start_index = self.index
        first = self._parse_part()
        parts = [first]
        while self._at("PERCENT"):
            self.index += 1
            parts.append(self._parse_part())
        start = parts[0].span.start
        end = parts[-1].span.end
        if self.index == start_index:
            self._error("expected an object designator", self._peek().span)
        source_text = self.text[start.offset : end.offset]
        if any(char.isspace() for char in source_text):
            self._error(
                "an object designator must not contain embedded blanks",
                SourceSpan(start, end),
            )
        return Designator(
            tuple(parts),
            source_text,
            SourceSpan(start, end),
        )

    def _parse_part(self) -> DesignatorPart:
        name = self._consume("WORD", "expected an object or component name")
        if not _is_identifier(name.text):
            self._error(f"invalid object identifier {name.text!r}", name.span)
        groups: list[SelectorGroup] = []
        end = name.span.end
        while self._at("LPAREN"):
            group = self._parse_selector_group()
            groups.append(group)
            end = group.span.end
        return DesignatorPart(name.text, tuple(groups), SourceSpan(name.span.start, end))

    def _parse_selector_group(self) -> SelectorGroup:
        start = self._consume("LPAREN").span.start
        selectors: list[Selector] = []
        while True:
            selectors.append(self._parse_selector())
            if self._at("COMMA"):
                self.index += 1
                continue
            end = self._consume("RPAREN", "expected ')' after selector list").span.end
            return SelectorGroup(tuple(selectors), SourceSpan(start, end))

    def _parse_selector(self) -> Selector:
        start = self._peek().span.start
        lower = self._optional_selector_integer()
        if not self._at("COLON"):
            if lower is None:
                self._error("expected an integer subscript or section triplet", self._peek().span)
            assert lower is not None
            return ScalarSelector(lower, SourceSpan(start, self.tokens[self.index - 1].span.end))
        self.index += 1
        upper = self._optional_selector_integer()
        stride: int | None = None
        if self._at("COLON"):
            self.index += 1
            stride = self._optional_selector_integer()
            if stride is None:
                self._error("section stride must be an integer", self._peek().span)
            if stride == 0:
                self._error("section stride must not be zero", self.tokens[self.index - 1].span)
        end = self.tokens[self.index - 1].span.end
        return SectionSelector(lower, upper, stride, SourceSpan(start, end))

    def _optional_selector_integer(self) -> int | None:
        if not self._at("WORD"):
            return None
        token = self._peek()
        if not _is_signed_integer(token.text):
            self._error("namelist subscripts and bounds must be integer literals", token.span)
        if "_" in token.text:
            self._error("kind suffixes are not permitted in namelist subscripts", token.span)
        self.index += 1
        return int(token.text)

    def _starts_assignment(self) -> bool:
        if not self._at("WORD") or not _is_identifier(self._peek().text):
            return False
        saved = self.index
        try:
            self._parse_designator()
            return self._at("EQUAL")
        except NamelistSyntaxError:
            return False
        finally:
            self.index = saved

    def _at_value_separator(self) -> bool:
        if self.decimal_mode is DecimalMode.POINT:
            return self._at("COMMA")
        return self._at("SEMICOLON")

    def _skip_eor(self) -> None:
        while self._at("EOR"):
            self.index += 1

    def _peek(self, offset: int = 0) -> _Token:
        return self.tokens[min(self.index + offset, len(self.tokens) - 1)]

    def _at(self, kind: str) -> bool:
        return self._peek().kind == kind

    def _consume(self, kind: str, message: str | None = None) -> _Token:
        token = self._peek()
        if token.kind != kind:
            self._error(message or f"expected {kind.lower()}", token.span)
        self.index += 1
        return token

    def _error(self, message: str, span: SourceSpan) -> NoReturn:
        raise NamelistSyntaxError(message, source=self.source, span=span)


def _is_identifier(value: str) -> bool:
    return (
        bool(value)
        and value[0].isalpha()
        and all(char.isalnum() or char == "_" for char in value)
    )


def _is_signed_integer(value: str) -> bool:
    digits = value[1:] if value[:1] in {"+", "-"} else value
    return bool(digits) and digits.isdigit()


def _is_unsigned_integer(value: str) -> bool:
    return bool(value) and value.isdigit()


def _looks_numeric(value: str) -> bool:
    return any(char.isdigit() for char in value)


def _has_kind_suffix(value: str) -> bool:
    if "_" not in value:
        return False
    base, suffix = value.rsplit("_", 1)
    if not suffix or not (_is_identifier(suffix) or _is_unsigned_integer(suffix)):
        return False
    logical = base.lower()
    return _looks_numeric(base) or logical in {"t", "f", "true", "false", ".true.", ".false."}
