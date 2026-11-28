import pytest

from ovenbird.sql import identifiers, placeholders, qualified, sql


def test_slots_take_names_and_placeholder_counts() -> None:
    """Strings fill a slot as identifier lists and integers as placeholders."""
    text = sql(
        "INSERT INTO {table} ({columns}) VALUES ({marks})", table="t", columns="a, b", marks=2
    )
    assert text == "INSERT INTO t (a, b) VALUES (?, ?)"


def test_qualified_prefixes_every_column() -> None:
    """Every column of the list gets the alias."""
    assert qualified("a, b", "f") == "f.a, f.b"


def test_schema_prefixed_names_are_identifiers() -> None:
    """``schema.table`` is accepted."""
    assert identifiers("live.signal") == "live.signal"


@pytest.mark.parametrize("bad", ["a; DROP TABLE x", "a b", "", "a,", "1a", "a--", "a'b"])
def test_other_text_is_refused(bad: str) -> None:
    """Anything outside the identifier grammar raises."""
    with pytest.raises(ValueError, match="not an SQL identifier"):
        sql("SELECT {names} FROM t", names=bad)


def test_empty_placeholder_list_is_empty() -> None:
    """Zero placeholders give an empty list, as an empty ``IN ()`` always did."""
    assert placeholders(0) == ""
    with pytest.raises(ValueError, match="negative"):
        placeholders(-1)
