"""Alarm and message words of the ntfy notifications."""

from __future__ import annotations

import pytest

from ovenbird.notify.text import EN, NL, WORDS, AlarmText, Language, alarm_text, word


def test_every_english_alarm_has_a_dutch_one_and_the_reverse() -> None:
    assert set(EN) == set(NL)


def test_every_alarm_text_is_complete_in_both_languages() -> None:
    for texts in (EN, NL):
        for code, text in texts.items():
            assert text.name.strip(), code
            assert text.now.strip(), code
            assert text.you.strip(), code


def test_word_tables_have_the_same_keys_in_both_languages() -> None:
    assert set(WORDS["en"]) == set(WORDS["nl"])
    assert all(value.strip() for table in WORDS.values() for value in table.values())


@pytest.mark.parametrize("language", ["en", "nl"])
def test_alarm_text_returns_the_table_entry(language: Language) -> None:
    table = NL if language == "nl" else EN
    code = next(iter(table))
    assert alarm_text(code, language) is table[code]


def test_english_and_dutch_differ() -> None:
    assert alarm_text("mode_mismatch", "en").name == "Pump mode mismatch"
    assert alarm_text("mode_mismatch", "nl").name != alarm_text("mode_mismatch", "en").name


def test_an_unknown_code_falls_back_to_the_readable_code() -> None:
    assert alarm_text("brand_new_alarm", "en") == AlarmText("brand new alarm", "", "")
    assert alarm_text("brand_new_alarm", "nl") == AlarmText("brand new alarm", "", "")


def test_word_returns_the_phrase_or_the_key() -> None:
    assert word("critical", "en") == "Critical"
    assert word("critical", "nl") != "Critical"
    assert word("no_such_word", "en") == "no_such_word"
    assert word("no_such_word", "nl") == "no_such_word"
