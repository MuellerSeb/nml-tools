# mypy: disable-error-code="attr-defined, import-not-found, misc"
"""Fortran namelist highlighting driven by the packaged TextMate grammar."""

from __future__ import annotations

import json
import pkgutil
from collections.abc import Sequence
from typing import Any, Mapping, cast

from qtpy.QtCore import QRegularExpression
from qtpy.QtGui import QColor, QFont, QSyntaxHighlighter, QTextCharFormat, QTextDocument

_GRAMMAR = "Resources/Fortran-Namelist.tmLanguage.json"
_STYLES = (
    ("comment.", "#4ddd48", False, True),
    ("string.regexp", "#ac9b01", False, True),
    ("string.", "#ab2b2c", False, False),
    ("constant.numeric", "#258a62", False, False),
    ("constant.character", "#b31d28", False, False),
    ("keyword.boolean", "#2700ff", True, False),
    ("keyword.control", "#be11dc", True, False),
    ("keyword.operator", "#24292e", True, False),
    ("variable.", "#091c91", False, False),
)


def _grammar() -> Mapping[str, Any]:
    raw = pkgutil.get_data("nml_tools.gui.ui", _GRAMMAR)
    if raw is None:
        raise RuntimeError(f"missing syntax grammar '{_GRAMMAR}'")
    data = json.loads(raw.decode("utf-8"))
    if not isinstance(data, Mapping):
        raise RuntimeError("namelist syntax grammar must be an object")
    return cast(Mapping[str, Any], data)


def _rule_pattern(rule: Mapping[str, Any]) -> str | None:
    match = rule.get("match")
    if isinstance(match, str):
        pattern = match
    else:
        begin, end = rule.get("begin"), rule.get("end")
        if not isinstance(begin, str) or not isinstance(end, str):
            return None
        nested = rule.get("patterns", ())
        if not isinstance(nested, Sequence) or isinstance(nested, (str, bytes)):
            nested = ()
        escapes = [
            item["match"]
            for item in nested
            if isinstance(item, Mapping) and isinstance(item.get("match"), str)
        ]
        alternatives = "|".join(f"(?:{item})" for item in escapes)
        body = f"{alternatives}|(?!(?:{end}))." if alternatives else f"(?!(?:{end}))."
        pattern = f"(?:{begin})(?:{body})*(?:{end}|$)"
    return f"(?i:{pattern})" if "i" in str(rule.get("flags", "")).lower() else pattern


def _text_format(scope: str) -> QTextCharFormat:
    result = QTextCharFormat()
    for prefix, colour, bold, italic in _STYLES:
        if scope.startswith(prefix):
            result.setForeground(QColor(colour))
            result.setFontWeight(QFont.Bold if bold else QFont.Normal)
            result.setFontItalic(italic)
            break
    return result


class NamelistHighlighter(QSyntaxHighlighter):
    """Apply the packaged TextMate patterns to a Qt text document."""

    def __init__(self, document: QTextDocument) -> None:
        super().__init__(document)
        patterns = _grammar().get("patterns", ())
        self.rules: list[tuple[int, str, QRegularExpression, QTextCharFormat]] = []
        if not isinstance(patterns, Sequence) or isinstance(patterns, (str, bytes)):
            raise RuntimeError("namelist syntax grammar patterns must be an array")
        for rule in patterns:
            if not isinstance(rule, Mapping):
                continue
            scope = rule.get("name")
            pattern = _rule_pattern(rule)
            if not isinstance(scope, str) or pattern is None:
                continue
            expression = QRegularExpression(pattern)
            if not expression.isValid():
                raise RuntimeError(f"invalid namelist syntax pattern: {expression.errorString()}")
            priority = 2 if scope.startswith("comment.") else int(scope.startswith("string."))
            self.rules.append((priority, scope, expression, _text_format(scope)))
        self.rules.sort(key=lambda item: item[0])

    def highlightBlock(self, text: str) -> None:
        """Highlight every grammar match in one document block."""
        quoted = []
        for _priority, scope, expression, _text_format in self.rules:
            if not scope.startswith("string.quoted."):
                continue
            matches = expression.globalMatch(text)
            while matches.hasNext():
                match = matches.next()
                quoted.append((match.capturedStart(), match.capturedEnd()))
        for _priority, scope, expression, text_format in self.rules:
            matches = expression.globalMatch(text)
            while matches.hasNext():
                match = matches.next()
                if scope.startswith("comment.") and any(
                    start <= match.capturedStart() < end for start, end in quoted
                ):
                    continue
                self.setFormat(match.capturedStart(), match.capturedLength(), text_format)
