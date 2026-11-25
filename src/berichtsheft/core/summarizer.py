"""Aus den Unterrichtsstunden eines Tages einen Berichtsheft-Text formulieren.

Ablauf:
1. Zeilen bereinigen (Leerzeichen, Satzzeichen, Ersetzungstabelle)
2. Dozent, Ignorierliste und Doppelte entfernen
3. Wiederholungen bündeln:
   - Überschrift, die in mehreren Stunden vorkommt ("Arbeiten am Projekt")
     -> "Arbeiten am Projekt: Planungsphase, Risikoanalyse und Soll-Konzept."
   - gemeinsamer Anfang mehrerer Einträge ("Vorlagenerstellung Testfälle",
     "Vorlagenerstellung PSP") -> "Vorlagenerstellung: Testfälle und PSP."
4. Sätze bauen und auf die Maximallänge kürzen – es werden ganze Einträge
   weggelassen, nie mitten im Wort oder Satz abgeschnitten.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .models import Issue, Lesson, Severity

ARTICLES = {"der", "die", "das", "den", "dem", "des", "ein", "eine", "einer", "eines", "einem", "einen"}


@dataclass(frozen=True)
class Replacement:
    """Eine Zeile der Ersetzungstabelle (falsch -> richtig)."""

    wrong: str
    right: str
    regex: bool = False
    ignore_case: bool = False

    def apply(self, text: str) -> str:
        if not self.wrong:
            return text
        flags = re.I if self.ignore_case else 0
        if self.regex:
            return re.sub(self.wrong, self.right, text, flags=flags)
        # Nur ganze Wörter/Phrasen ersetzen, nie Wortteile
        # (sonst wird z. B. aus "wiederherstellen" -> "wiederhErstellen").
        pattern = rf"(?<![\wÄÖÜäöüß]){re.escape(self.wrong)}(?![\wÄÖÜäöüß])"
        return re.sub(pattern, lambda _m: self.right, text, flags=flags)


@dataclass
class Phrases:
    intro: str = "Behandelt wurden"
    more: str = "Außerdem wurden"
    more_verb: str = "bearbeitet"
    deepen: str = "Die Inhalte wurden anschließend mit Unterlagen und Labs vertieft."
    only_deepen: str = "Die zuvor behandelten Inhalte wurden mit Unterlagen und Labs vertieft."
    empty: str = "Unterrichtsinhalte wurden behandelt und anhand von Übungen vertieft."


@dataclass
class SummarizerSettings:
    max_chars: int = 430
    replacements: list[Replacement] = field(default_factory=list)
    ignore_lines: list[str] = field(default_factory=list)
    low_priority: list[str] = field(default_factory=list)
    drop_patterns: list[str] = field(default_factory=lambda: ["rückblick auf die themen"])
    deepen_patterns: list[str] = field(default_factory=lambda: ["vertiefen der inhalte"])
    phrases: Phrases = field(default_factory=Phrases)


# --------------------------------------------------------------------------- #
# Bereinigen
# --------------------------------------------------------------------------- #

def clean_line(line: str, replacements: list[Replacement] | None = None) -> str:
    """Leerzeichen/Satzzeichen normalisieren und Ersetzungen anwenden."""
    line = re.sub(r"\s+", " ", line).strip()
    for rep in replacements or []:
        line = rep.apply(line)
    line = re.sub(r"\s+([,;:!?])", r"\1", line)        # keine Lücke vor Satzzeichen
    line = re.sub(r"([,;])(?=[^\s\d])", r"\1 ", line)   # Lücke nach Komma/Semikolon
    line = re.sub(r"(?<=\w)--+(?=[/\w])", "-", line)    # "Kosten--/Plan" -> "Kosten-/Plan"
    line = re.sub(r"\s+", " ", line).strip()
    return line.strip(" ,;.")


def _key(text: str) -> str:
    return re.sub(r"[^\wäöüß]+", " ", text.lower()).strip()


def _words(text: str) -> set[str]:
    return set(_key(text).split())


def _capitalize_item(item: str) -> str:
    """Erstes Wort einer Aufzählung nach "Behandelt wurden": Artikel klein, sonst groß."""
    if not item:
        return item
    first, _, rest = item.partition(" ")
    if first.lower() in ARTICLES:
        return first.lower() + (" " + rest if rest else "")
    # Nominalisierte Verben groß ("erstellen von …" -> "Erstellen von …"),
    # Adjektive bleiben klein ("erweiterte Bearbeitung").
    if first[:1].islower() and first.endswith("en"):
        return item[0].upper() + item[1:]
    return item


def join_natural(items: list[str]) -> str:
    items = [x.strip(" ,;.") for x in items if x.strip(" ,;.")]
    if not items:
        return ""
    if len(items) == 1:
        return items[0]
    return ", ".join(items[:-1]) + " und " + items[-1]


# --------------------------------------------------------------------------- #
# Struktur des Tages
# --------------------------------------------------------------------------- #

CONTINUATION_WORDS = ("wie ", "und ", "sowie ", "oder ", "inkl", "z. b", "zb ", "bzw")


@dataclass
class _Item:
    text: str
    lesson: int  # Index der Stunde, aus der der Eintrag stammt


@dataclass
class _Group:
    heading: str
    items: list[_Item] = field(default_factory=list)


_Piece = _Item | _Group


def _matches_any(text: str, patterns: list[str]) -> bool:
    low = text.lower()
    return any(p and p.lower() in low for p in patterns)


def _clean_lessons(lessons: list[Lesson], trainers: list[str], settings: SummarizerSettings) -> tuple[list[list[str]], bool]:
    ignore = {_key(x) for x in settings.ignore_lines if x.strip()}
    trainer_keys = {_key(t) for t in trainers if t}
    for lesson in lessons:
        if lesson.trainer:
            trainer_keys.add(_key(lesson.trainer))
    has_deepen = False
    result: list[list[str]] = []
    for lesson in lessons:
        lines: list[str] = []
        for raw in lesson.topics:
            line = clean_line(raw, settings.replacements)
            if not line:
                continue
            k = _key(line)
            if k in ignore or k in trainer_keys:
                continue
            if _matches_any(line, settings.drop_patterns):
                continue
            if _matches_any(line, settings.deepen_patterns):
                has_deepen = True
                continue
            # "wie z. B. …" / "und …" setzt die vorige Zeile fort
            if lines and line[:1].islower() and line.lower().startswith(CONTINUATION_WORDS):
                lines[-1] = f"{lines[-1]} {line}"
                continue
            lines.append(line)
        result.append(lines)
    return result, has_deepen


def _find_headings(lessons: list[list[str]]) -> set[str]:
    """Überschrift = Zeile, die in >= 2 Stunden vorne steht und unter der
    unterschiedliche Unterpunkte folgen ("Arbeiten am Projekt")."""
    followers: dict[str, set[str]] = {}
    occurrences: dict[str, int] = {}
    for lines in lessons:
        for k in {_key(x) for x in lines}:
            occurrences[k] = occurrences.get(k, 0) + 1
    for lines in lessons:
        if not lines:
            continue
        k = _key(lines[0])
        followers.setdefault(k, set()).update(_key(x) for x in lines[1:])
    return {k for k, f in followers.items() if occurrences.get(k, 0) >= 2 and len(f - {k}) >= 2}


def _build_pieces(lessons: list[list[str]]) -> list[_Piece]:
    headings = _find_headings(lessons)
    pieces: list[_Piece] = []
    groups: dict[str, _Group] = {}
    seen: set[str] = set()

    for li, lines in enumerate(lessons):
        current: _Group | None = None
        for line in lines:
            k = _key(line)
            if k in headings:
                if k not in groups:
                    groups[k] = _Group(line)
                    pieces.append(groups[k])
                current = groups[k]
                continue
            if current is not None:
                existing = {_key(x.text) for x in current.items}
                for part in re.split(r",\s*", line):
                    part = part.strip(" ,;.")
                    pk = _key(part)
                    if pk and pk not in existing and pk not in headings and pk not in seen:
                        current.items.append(_Item(part, li))
                        existing.add(pk)
            elif k and k not in seen:
                seen.add(k)
                pieces.append(_Item(line, li))
    # Einträge, die schon als Unterpunkt einer Überschrift vorkommen, nicht doppelt nennen
    sub_keys = {_key(it.text) for g in groups.values() for it in g.items}
    return [p for p in pieces if not (isinstance(p, _Item) and _key(p.text) in sub_keys)]


def _prefix_groups(pieces: list[_Piece]) -> list[_Piece]:
    """Einträge mit gemeinsamem Anfang zusammenfassen
    ("Vorlagenerstellung Testfälle", "Vorlagenerstellung PSP" -> "Vorlagenerstellung: Testfälle und PSP")."""
    items = [p for p in pieces if isinstance(p, _Item)]
    by_first: dict[str, list[_Item]] = {}
    for it in items:
        first = it.text.split(" ")[0].rstrip(":").lower()
        if len(first) >= 4:
            by_first.setdefault(first, []).append(it)

    replace: dict[int, _Group] = {}
    for members in by_first.values():
        if len(members) < 2:
            continue
        tokens = [m.text.split(" ") for m in members]
        prefix: list[str] = []
        for parts in zip(*tokens):
            if len({p.rstrip(":").lower() for p in parts}) == 1:
                prefix.append(parts[0].rstrip(":"))
            else:
                break
        if not prefix:
            continue
        if len(prefix) == 1 and (len(prefix[0]) < 10 or len(members) < 3):
            continue
        rests = [" ".join(t[len(prefix):]).strip(" :,") for t in tokens]
        if any(not r for r in rests):
            continue
        group = _Group(" ".join(prefix), [_Item(r, m.lesson) for r, m in zip(rests, members)])
        for m in members:
            replace[id(m)] = group

    out: list[_Piece] = []
    placed: set[int] = set()
    for p in pieces:
        if isinstance(p, _Item) and id(p) in replace:
            g = replace[id(p)]
            if id(g) not in placed:
                placed.add(id(g))
                out.append(g)
            continue
        out.append(p)
    return out


def _drop_contained(pieces: list[_Piece]) -> list[_Piece]:
    """Eintrag weglassen, wenn ein anderer ihn vollständig enthält
    ("Entwickeln der zeitlichen Abläufe" ⊂ "Entwickeln der zeitlichen Abläufe PSP")."""
    loose = [p for p in pieces if isinstance(p, _Item)]
    out: list[_Piece] = []
    for p in pieces:
        if isinstance(p, _Item):
            w = _words(p.text)
            if any(o is not p and w < _words(o.text) for o in loose):
                continue
        else:
            p.items = [it for it in p.items
                       if not any(o is not it and _words(it.text) < _words(o.text) for o in p.items)]
        out.append(p)
    return out


# --------------------------------------------------------------------------- #
# Sätze
# --------------------------------------------------------------------------- #

def _render(pieces: list[_Piece], has_deepen: bool, ph: Phrases) -> str:
    sentences: list[str] = []
    first_group = next((i for i, p in enumerate(pieces) if isinstance(p, _Group)), None)

    if first_group is None:
        items = [p.text for p in pieces if isinstance(p, _Item)]
        if len(items) > 3:
            half = (len(items) + 1) // 2
            before, after = items[:half], items[half:]
        else:
            before, after = items, []
        groups: list[_Group] = []
    else:
        before = [p.text for p in pieces[:first_group] if isinstance(p, _Item)]
        after = [p.text for p in pieces[first_group:] if isinstance(p, _Item)]
        groups = [p for p in pieces if isinstance(p, _Group)]

    if before:
        sentences.append(f"{ph.intro} {join_natural([_capitalize_item(x) for x in before])}.")
    for g in groups:
        heading = g.heading[0].upper() + g.heading[1:]
        if g.items:
            sentences.append(f"{heading}: {join_natural([i.text for i in g.items])}.")
        else:
            sentences.append(f"{heading}.")
    if after:
        listed = join_natural([_capitalize_item(x) for x in after])
        if sentences:
            sentences.append(f"{ph.more} {listed} {ph.more_verb}.")
        else:
            sentences.append(f"{ph.intro} {listed}.")
    if has_deepen:
        sentences.append(ph.deepen if sentences else ph.only_deepen)
    if not sentences:
        return ph.empty
    return " ".join(sentences)


def _all_items(pieces: list[_Piece]) -> list[tuple[_Piece, _Item]]:
    out: list[tuple[_Piece, _Item]] = []
    for p in pieces:
        if isinstance(p, _Item):
            out.append((p, p))
        else:
            out.extend((p, it) for it in p.items)
    return out


def _remove(pieces: list[_Piece], owner: _Piece, item: _Item) -> None:
    if owner is item:
        pieces.remove(item)
    else:
        assert isinstance(owner, _Group)
        owner.items.remove(item)


def _shrink_once(pieces: list[_Piece], low_priority: list[str]) -> bool:
    """Einen Eintrag entfernen. False, wenn nichts mehr entfernt werden kann.

    Reihenfolge: unwichtige Einträge (Agenda, Wiederholung …) -> aus der Stunde
    mit den meisten verbleibenden Einträgen den letzten (so bleibt jede Stunde
    vertreten) -> zuletzt ganze Einträge von hinten.
    """
    entries = _all_items(pieces)
    if len(entries) <= 1:
        return False
    for owner, item in reversed(entries):
        if _matches_any(item.text, low_priority):
            _remove(pieces, owner, item)
            return True
    per_lesson: dict[int, list[tuple[_Piece, _Item]]] = {}
    for owner, item in entries:
        per_lesson.setdefault(item.lesson, []).append((owner, item))
    _lesson, bucket = max(per_lesson.items(), key=lambda kv: (len(kv[1]), kv[0]))
    if len(bucket) > 1:
        _remove(pieces, *bucket[-1])
        return True
    owner, item = entries[-1]
    _remove(pieces, owner, item)
    return True


def summarize(lessons: list[Lesson], trainers: list[str], settings: SummarizerSettings) -> tuple[str, list[Issue]]:
    """Text für eine Tageszeile erzeugen. Gibt Text und Meldungen zurück."""
    issues: list[Issue] = []
    cleaned, has_deepen = _clean_lessons(lessons, trainers, settings)
    pieces = _build_pieces(cleaned)
    pieces = _prefix_groups(pieces)
    pieces = _drop_contained(pieces)

    text = _render(pieces, has_deepen, settings.phrases)
    shortened = False
    while settings.max_chars > 0 and len(text) > settings.max_chars:
        if not _shrink_once(pieces, settings.low_priority):
            break
        shortened = True
        text = _render(pieces, has_deepen, settings.phrases)
    if shortened:
        issues.append(Issue(Severity.INFO, f"Text auf {settings.max_chars} Zeichen gekürzt – bitte prüfen"))
    if settings.max_chars > 0 and len(text) > settings.max_chars:
        issues.append(Issue(Severity.WARNING, f"Text ist länger als {settings.max_chars} Zeichen"))
    if not any(cleaned) and not has_deepen:
        issues.append(Issue(Severity.WARNING, "Keine Lehrinhalte gefunden"))
    return text, issues
