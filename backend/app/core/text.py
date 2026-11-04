"""Persian text for search (ADR-0030): Arabic «ي/ك» and Persian «ی/ک», hamza forms, the
zero-width non-joiner and Persian/Arabic digits compare equal, in Python and in SQL alike.

The same table is used by the frontend (``lib/search.ts``); the visitor app folds a
subset of it on the phone (ی، ک، the non-joiner and digits).
"""

from __future__ import annotations

from sqlalchemy import ColumnElement, func, literal
from sqlalchemy.orm import InstrumentedAttribute

# (from, to): applied in this order, in Python and in SQL.
FOLD: tuple[tuple[str, str], ...] = (
    ("ي", "ی"),
    ("ى", "ی"),
    ("ئ", "ی"),
    ("ك", "ک"),
    ("ة", "ه"),
    ("أ", "ا"),
    ("إ", "ا"),
    ("ٱ", "ا"),
    ("ؤ", "و"),
    ("‌", ""),  # zero-width non-joiner
    ("ـ", ""),  # tatweel
    *((chr(0x06F0 + i), str(i)) for i in range(10)),  # Persian digits
    *((chr(0x0660 + i), str(i)) for i in range(10)),  # Arabic digits
)
BINARY = "Latin1_General_100_BIN2"
_TABLE = str.maketrans({a: b for a, b in FOLD})


def fold(text: str) -> str:
    """Search form of a text: letters and digits unified, spaces collapsed."""
    return " ".join(text.translate(_TABLE).split())


def fold_sql(column: ColumnElement[str] | InstrumentedAttribute[str]) -> ColumnElement[str]:
    """The same folding as an SQL expression (nested REPLACE)."""
    # A binary collation: under Persian_100_CI_AI and other Windows collations REPLACE
    # ignores zero-weight characters such as the non-joiner. The result goes back to the
    # database's collation, so comparisons stay case-insensitive for Latin letters.
    expr: ColumnElement[str] = column.collate(BINARY)
    for a, b in FOLD:
        expr = func.replace(expr, literal(a), literal(b))
    return expr.collate("DATABASE_DEFAULT")


def fold_ddl(column: str, length: int) -> str:
    """T-SQL for a persisted computed column holding ``fold(column)``."""
    expr = f"{column} COLLATE {BINARY}"
    for a, b in FOLD:
        expr = f"REPLACE({expr}, N'{a}', N'{b}')"
    return f"CAST({expr} AS NVARCHAR({length})) COLLATE DATABASE_DEFAULT"


def like_escape(term: str) -> str:
    """A user's text inside LIKE: % _ [ are literal (escape character \\)."""
    return term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_").replace("[", "\\[")


def matches(
    column: ColumnElement[str] | InstrumentedAttribute[str], text: str
) -> ColumnElement[bool]:
    """``column`` contains every word of ``text``, both folded (for tables without a
    stored folded column)."""
    from sqlalchemy import and_

    words = fold(text).split() or [""]
    folded = fold_sql(column)
    return and_(*(folded.like(f"%{like_escape(w)}%", escape="\\") for w in words))
