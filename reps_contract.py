"""Shared scalar reps validation for the formal plan and v24 import paths."""

from __future__ import annotations

import re


_UNIT = r"(?:次(?:\s*/\s*侧)?|reps?)"
_SCALAR_RE = re.compile(r"^(\d+)\s*(?:" + _UNIT + r")?$", re.IGNORECASE)
# Do not use ``\w`` as a boundary: Python treats adjacent Chinese text as a
# word, while ``3组12次`` is a supported display grammar.  The unit itself is
# the boundary that matters here.
_RANGE_RE = re.compile(r"([+-]?\d+)\s*(?:-|–|—)\s*([+-]?\d+)\s*" + _UNIT, re.IGNORECASE)
_TOKEN_RE = re.compile(r"([+-]?\d+)\s*" + _UNIT, re.IGNORECASE)
_SIGNED_FRAGMENT_RE = re.compile(r"[+-]\s*\d+\s*" + _UNIT, re.IGNORECASE)
_FRACTION_RE = re.compile(r"\d+\.\d+\s*" + _UNIT, re.IGNORECASE)
_WORD_ADJACENT_RE = re.compile(r"[A-Za-z_.]\s*\d+\s*" + _UNIT, re.IGNORECASE)


def parse_scalar_reps(value: object) -> int | None:
    """Return a validated scalar or raise ``ValueError`` before mutation."""
    if value is None or not str(value).strip():
        return None
    raw = str(value).strip()
    match = _SCALAR_RE.fullmatch(raw)
    if match is None:
        raise ValueError("动作次数必须是 1 到 10000 的单一整数；范围值不能转换为单值")
    number = int(match.group(1))
    if not 1 <= number <= 10000:
        raise ValueError("动作次数必须在 1 到 10000 之间")
    return number


def parse_implicit_spec_reps(spec: object) -> int | None:
    """Parse only a real reps token in a free display specification.

    Dates and other arbitrary text are ignored unless a number is immediately
    followed by a reps unit.  A range, signed value, zero, or oversized value
    is rejected when no explicit typed ``reps`` field overrides the display.
    """
    text = str(spec or "")
    range_match = _RANGE_RE.search(text)
    if range_match:
        raise ValueError("动作 spec 中的次数范围不能隐式转换为单值")
    if _SIGNED_FRAGMENT_RE.search(text) or _FRACTION_RE.search(text) or _WORD_ADJACENT_RE.search(text):
        raise ValueError("动作 spec 中的次数 token 不是合法的单一整数")
    token = _TOKEN_RE.search(text)
    if token is None:
        return None
    return parse_scalar_reps(token.group(1))
