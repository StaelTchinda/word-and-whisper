#!/usr/bin/env python3
"""Bible book table: Logos abbreviation -> OSIS id, full name, canon, chapter count.

Shared by the per-source extractors so every dataset speaks the same reference
language. OSIS ids follow the OSIS 2.1.1 book list, which is what Bible APIs and
text corpora use, so `Gen.32.9` joins cleanly against outside data.

`chapters` is None for works the tradition numbers by verse only (Susanna, Bel,
Prayer of Manasseh, Prayer of Azariah). OSIS still addresses those with an
explicit chapter 1, e.g. `Sus.1.42`.
"""
import re
from typing import NamedTuple, Optional


class Book(NamedTuple):
    osis: str
    name: str
    canon: str  # OT | NT | DC
    chapters: Optional[int]


# Keyed by the abbreviation Logos/Faithlife prints. Alternates are folded in via
# ALIASES below rather than duplicated here.
BOOKS: dict[str, Book] = {
    # --- Old Testament -----------------------------------------------------
    "Ge": Book("Gen", "Genesis", "OT", 50),
    "Ex": Book("Exod", "Exodus", "OT", 40),
    "Le": Book("Lev", "Leviticus", "OT", 27),
    "Nu": Book("Num", "Numbers", "OT", 36),
    "Dt": Book("Deut", "Deuteronomy", "OT", 34),
    "Jos": Book("Josh", "Joshua", "OT", 24),
    "Jdg": Book("Judg", "Judges", "OT", 21),
    "Ru": Book("Ruth", "Ruth", "OT", 4),
    "1 Sa": Book("1Sam", "1 Samuel", "OT", 31),
    "2 Sa": Book("2Sam", "2 Samuel", "OT", 24),
    "1 Ki": Book("1Kgs", "1 Kings", "OT", 22),
    "2 Ki": Book("2Kgs", "2 Kings", "OT", 25),
    "1 Ch": Book("1Chr", "1 Chronicles", "OT", 29),
    "2 Ch": Book("2Chr", "2 Chronicles", "OT", 36),
    "Ezr": Book("Ezra", "Ezra", "OT", 10),
    "Ne": Book("Neh", "Nehemiah", "OT", 13),
    "Es": Book("Esth", "Esther", "OT", 10),
    "Job": Book("Job", "Job", "OT", 42),
    "Ps": Book("Ps", "Psalms", "OT", 150),
    "Pr": Book("Prov", "Proverbs", "OT", 31),
    "Ec": Book("Eccl", "Ecclesiastes", "OT", 12),
    "So": Book("Song", "Song of Songs", "OT", 8),
    "Is": Book("Isa", "Isaiah", "OT", 66),
    "Je": Book("Jer", "Jeremiah", "OT", 52),
    "La": Book("Lam", "Lamentations", "OT", 5),
    "Eze": Book("Ezek", "Ezekiel", "OT", 48),
    "Da": Book("Dan", "Daniel", "OT", 12),
    "Ho": Book("Hos", "Hosea", "OT", 14),
    "Joe": Book("Joel", "Joel", "OT", 3),
    "Am": Book("Amos", "Amos", "OT", 9),
    "Ob": Book("Obad", "Obadiah", "OT", 1),
    "Jon": Book("Jonah", "Jonah", "OT", 4),
    "Mic": Book("Mic", "Micah", "OT", 7),
    "Na": Book("Nah", "Nahum", "OT", 3),
    "Hab": Book("Hab", "Habakkuk", "OT", 3),
    "Zep": Book("Zeph", "Zephaniah", "OT", 3),
    "Hag": Book("Hag", "Haggai", "OT", 2),
    "Zec": Book("Zech", "Zechariah", "OT", 14),
    "Mal": Book("Mal", "Malachi", "OT", 4),
    # --- Deuterocanon / Apocrypha -----------------------------------------
    "Tob": Book("Tob", "Tobit", "DC", 14),
    "Jdt": Book("Jdt", "Judith", "DC", 16),
    "Add Es": Book("AddEsth", "Additions to Esther", "DC", 16),
    "Wis": Book("Wis", "Wisdom of Solomon", "DC", 19),
    "Sir": Book("Sir", "Sirach", "DC", 51),
    "Bar": Book("Bar", "Baruch", "DC", 5),
    "Ep Jer": Book("EpJer", "Letter of Jeremiah", "DC", None),
    "Song Thr": Book("PrAzar", "Prayer of Azariah and Song of the Three Jews", "DC", None),
    "Sus": Book("Sus", "Susanna", "DC", None),
    "Bel": Book("Bel", "Bel and the Dragon", "DC", None),
    "1 Mac": Book("1Macc", "1 Maccabees", "DC", 16),
    "2 Mac": Book("2Macc", "2 Maccabees", "DC", 15),
    "3 Mac": Book("3Macc", "3 Maccabees", "DC", 7),
    "4 Mac": Book("4Macc", "4 Maccabees", "DC", 18),
    "Pr Man": Book("PrMan", "Prayer of Manasseh", "DC", None),
    "1 Esd": Book("1Esd", "1 Esdras", "DC", 9),
    "2 Esd": Book("2Esd", "2 Esdras", "DC", 16),
    # --- New Testament -----------------------------------------------------
    "Mt": Book("Matt", "Matthew", "NT", 28),
    "Mk": Book("Mark", "Mark", "NT", 16),
    "Lk": Book("Luke", "Luke", "NT", 24),
    "Jn": Book("John", "John", "NT", 21),
    "Ac": Book("Acts", "Acts", "NT", 28),
    "Ro": Book("Rom", "Romans", "NT", 16),
    "1 Co": Book("1Cor", "1 Corinthians", "NT", 16),
    "2 Co": Book("2Cor", "2 Corinthians", "NT", 13),
    "Ga": Book("Gal", "Galatians", "NT", 6),
    "Eph": Book("Eph", "Ephesians", "NT", 6),
    "Php": Book("Phil", "Philippians", "NT", 4),
    "Col": Book("Col", "Colossians", "NT", 4),
    "1 Th": Book("1Thess", "1 Thessalonians", "NT", 5),
    "2 Th": Book("2Thess", "2 Thessalonians", "NT", 3),
    "1 Ti": Book("1Tim", "1 Timothy", "NT", 6),
    "2 Ti": Book("2Tim", "2 Timothy", "NT", 4),
    "Tt": Book("Titus", "Titus", "NT", 3),
    "Phm": Book("Phlm", "Philemon", "NT", 1),
    "Heb": Book("Heb", "Hebrews", "NT", 13),
    "Jas": Book("Jas", "James", "NT", 5),
    "1 Pe": Book("1Pet", "1 Peter", "NT", 5),
    "2 Pe": Book("2Pet", "2 Peter", "NT", 3),
    "1 Jn": Book("1John", "1 John", "NT", 5),
    "2 Jn": Book("2John", "2 John", "NT", 1),
    "3 Jn": Book("3John", "3 John", "NT", 1),
    "Jud": Book("Jude", "Jude", "NT", 1),
    "Re": Book("Rev", "Revelation", "NT", 22),
}

# Spellings other sources may use for the same book.
ALIASES: dict[str, str] = {
    "Gen": "Ge", "Exo": "Ex", "Lev": "Le", "Num": "Nu", "Deu": "Dt",
    "Jsh": "Jos", "Jdgs": "Jdg", "Rth": "Ru", "1Sa": "1 Sa", "2Sa": "2 Sa",
    "1Ki": "1 Ki", "2Ki": "2 Ki", "1Ch": "1 Ch", "2Ch": "2 Ch",
    "Neh": "Ne", "Est": "Es", "Psa": "Ps", "Psalm": "Ps", "Psalms": "Ps",
    "Pro": "Pr", "Ecc": "Ec", "Sng": "So", "Isa": "Is", "Jer": "Je",
    "Lam": "La", "Ezk": "Eze", "Dan": "Da", "Hos": "Ho", "Jol": "Joe",
    "Oba": "Ob", "Nam": "Na", "Zph": "Zep", "Zch": "Zec",
    "Mat": "Mt", "Mar": "Mk", "Luk": "Lk", "Joh": "Jn", "Act": "Ac",
    "Rom": "Ro", "Rev": "Re",
}

# Full book names, for sources that spell them out (Lockyer writes "I Samuel").
NAME_INDEX: dict[str, str] = {book.name: key for key, book in BOOKS.items()}
NAME_ALIASES: dict[str, str] = {
    "Song of Solomon": "So", "Canticles": "So", "Psalm": "Ps",
    "Acts of the Apostles": "Ac", "Revelations": "Re", "Apocalypse": "Re",
    "Ecclesiasticus": "Sir", "Wisdom": "Wis", "The Song of the Three": "Song Thr",
}

_ROMAN = {"I": "1", "II": "2", "III": "3"}
_ROMAN_RE = re.compile(r"^(I{1,3})\s+(?=[A-Z])")

# Longest first so "1 Sa" beats "1 S", and "Judges" beats "Jude".
_SORTED_KEYS = sorted(
    list(BOOKS) + list(ALIASES) + list(NAME_INDEX) + list(NAME_ALIASES),
    key=len, reverse=True,
)


def normalise_roman(text: str) -> str:
    """'I Samuel 1:11' -> '1 Samuel 1:11'. Leaves 'Isaiah' alone (no space)."""
    m = _ROMAN_RE.match(text.strip())
    return _ROMAN[m.group(1)] + " " + text.strip()[m.end():] if m else text.strip()


def lookup(name: str) -> Book:
    """Resolve an abbreviation or a full book name (either numbering style)."""
    name = normalise_roman(name)
    key = NAME_ALIASES.get(name) or NAME_INDEX.get(name) or ALIASES.get(name, name)
    if key not in BOOKS:
        raise KeyError(f"unknown book: {name!r}")
    return BOOKS[key]


def split_book(text: str) -> tuple[str, str]:
    """Split 'Ge 32:9' or 'I Samuel 1:11' into (book_key, rest).

    Raises KeyError when no known book name starts the string.
    """
    text = normalise_roman(text)
    for key in _SORTED_KEYS:
        if text.startswith(key + " "):
            return key, text[len(key) + 1:].strip()
    raise KeyError(f"no known book at start of reference: {text!r}")
