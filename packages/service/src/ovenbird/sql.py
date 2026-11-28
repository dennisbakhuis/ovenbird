"""Build SQL text from validated identifier constants.

Statements are written as plain string literals with ``{name}`` slots. A slot is filled
with a column list or a table name (checked against a strict identifier grammar) or, when
given an integer, with that many ``?`` placeholders. Values still travel as bound
parameters; only names and placeholder counts are ever spliced into the text.
"""

from __future__ import annotations

import re
from typing import Final

IDENTIFIER: Final = re.compile(r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)?")


def identifiers(names: str) -> str:
    """Return a comma-separated identifier list, or raise when an entry is not an identifier.

    Parameters
    ----------
    names
        One identifier or several separated by commas (``schema.table`` and ``alias.column``
        are allowed).

    Returns
    -------
    str
        The list normalised to ``", "`` separators.

    Raises
    ------
    ValueError
        When an entry is empty or has characters outside the identifier grammar.
    """
    parts = [part.strip() for part in names.split(",")]
    for part in parts:
        if IDENTIFIER.fullmatch(part) is None:
            raise ValueError(f"not an SQL identifier: {part!r}")
    return ", ".join(parts)


def qualified(names: str, alias: str) -> str:
    """Return the identifier list with every entry prefixed by ``alias.``.

    Parameters
    ----------
    names
        Comma-separated column names.
    alias
        Table alias to put in front.

    Returns
    -------
    str
        For example ``"f.a, f.b"``.
    """
    return ", ".join(f"{identifiers(alias)}.{part}" for part in identifiers(names).split(", "))


def placeholders(count: int) -> str:
    """Return ``count`` comma-separated ``?`` placeholders."""
    if count < 0:
        raise ValueError("placeholder count must not be negative")
    return ", ".join("?" for _ in range(count))


def sql(template: str, /, **slots: str | int) -> str:
    """Fill the ``{name}`` slots of ``template`` with validated names or placeholders.

    Parameters
    ----------
    template
        Statement text with ``{name}`` slots.
    **slots
        A string fills its slot as an identifier list; an integer fills it with that many
        ``?`` placeholders.

    Returns
    -------
    str
        The statement text.
    """
    parts = {
        key: placeholders(value) if isinstance(value, int) else identifiers(value)
        for key, value in slots.items()
    }
    return template.format(**parts)
