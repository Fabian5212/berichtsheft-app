"""Word-Vorlage analysieren und befüllen.

Erkennung der Vorlage
---------------------
* Tageszeilen: Zeilen, deren erste Zelle "Mo", "Di", "Mi", "Do" oder "Fr" ist
  (auch "Montag" usw.).
* Spalten der Tageszeile: python-docx liefert über ``row.cells`` verbundene
  Zellen mehrfach (eine Zelle mit gridSpan=6 erscheint sechsmal). Darum werten
  wir die echten ``<w:tc>``-Elemente aus und berechnen für jede Zelle ihre
  Startspalte im Tabellenraster:

  1. Gibt es eine Kopfzeile mit "Lernfeld" und "Std", werden Lernfeld- und
     Stundenzelle über deren Rasterspalte gefunden.
  2. Die Inhaltszelle ist die breiteste übrige Zelle (größter gridSpan).
  3. Ohne Kopfzeile gilt die alte Regel: Inhalt = 2. Zelle, Lernfeld =
     vorletzte, Stunden = letzte Zelle.

* Kopfdaten: Wert steht in der Zelle rechts neben "Ausbildungsnachweis Nr.",
  "...vom", "bis" und "Name des/der Auszubildenden".
* Platzhalter: ``{{NAME}}``, ``{{VOM}}`` … überall im Dokument (auch in Kopf-
  und Fußzeilen), auch wenn Word sie intern auf mehrere Runs verteilt hat.

Formatierung
------------
Beim Schreiben wird die vorhandene Schriftformatierung der Zelle übernommen
(erster Run bzw. Absatzmarke) statt mit ``cell.text = ""`` alles zu löschen.
Schriftgröße/Fett aus den Einstellungen werden nur gesetzt, wenn angegeben.
"""

from __future__ import annotations

import copy
import datetime as dt
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterator

from docx import Document
from docx.document import Document as DocxDocument
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Pt
from docx.table import Table
from docx.text.paragraph import Paragraph
from docx.text.run import Run

from .models import WORKDAY_CODES, Issue, Severity

PLACEHOLDER_RE = re.compile(r"\{\{\s*([A-Za-z_]+)\s*\}\}")
KNOWN_PLACEHOLDERS: tuple[str, ...] = (
    "NAME", "BERUF", "BETRIEB", "BILDUNGSTRAEGER", "AUSBILDER", "KLASSE",
    "NACHWEIS_NR", "VOM", "BIS", "JAHR", "DATUM", "DOZENT",
    *(f"TEXT_{c.upper()}" for c in WORKDAY_CODES),
    *(f"LF_{c.upper()}" for c in WORKDAY_CODES),
    *(f"DATUM_{c.upper()}" for c in WORKDAY_CODES),
)
DAY_NAMES = {
    "mo": "Mo", "montag": "Mo", "di": "Di", "dienstag": "Di", "mi": "Mi", "mittwoch": "Mi",
    "do": "Do", "donnerstag": "Do", "fr": "Fr", "freitag": "Fr",
}
SHORT_DATE_RE = re.compile(r"(\d{1,2})[.,](\d{1,2})[.,]?(\d{2,4})?")


# --------------------------------------------------------------------------- #
# Zellen-Helfer
# --------------------------------------------------------------------------- #

def _tc_text(tc) -> str:
    return "\n".join("".join(t.text or "" for t in p.iter(qn("w:t"))) for p in tc.iter(qn("w:p"))).strip()


def _row_cells(tr) -> list[tuple[int, int, object]]:
    """(Rasterstart, Spaltenbreite, tc) für jede echte Zelle der Zeile."""
    col = 0
    trPr = tr.trPr
    if trPr is not None:
        gb = trPr.find(qn("w:gridBefore"))
        if gb is not None:
            col = int(gb.get(qn("w:val"), "0"))
    out = []
    for tc in tr.tc_lst:
        span = tc.grid_span
        out.append((col, span, tc))
        col += span
    return out


def _is_vmerge_continue(tc) -> bool:
    tcPr = tc.tcPr
    if tcPr is None:
        return False
    vm = tcPr.find(qn("w:vMerge"))
    return vm is not None and vm.get(qn("w:val")) in (None, "continue")


def _iter_tables(doc: DocxDocument) -> Iterator[Table]:
    def walk(tables: list[Table]) -> Iterator[Table]:
        for t in tables:
            yield t
            for row in t.rows:
                for cell in row.cells:
                    yield from walk(cell.tables)
    yield from walk(doc.tables)


def _iter_paragraphs(doc: DocxDocument) -> Iterator[Paragraph]:
    """Alle Absätze: Textkörper, Tabellen (ohne Duplikate), Kopf-/Fußzeilen."""
    # Elemente selbst merken (nicht id()): lxml-Proxys werden neu erzeugt,
    # ihre id() kann sonst wiederverwendet werden.
    seen: set = set()

    def from_part(element, parent) -> Iterator[Paragraph]:
        for p in list(element.iter(qn("w:p"))):
            if p in seen:
                continue
            seen.add(p)
            yield Paragraph(p, parent)

    yield from from_part(doc.element.body, doc)
    for section in doc.sections:
        for part in (section.header, section.footer, section.first_page_header,
                     section.first_page_footer, section.even_page_header, section.even_page_footer):
            # Achtung: Zugriff auf eine verknüpfte Kopfzeile würde sie anlegen
            if part.is_linked_to_previous:
                continue
            yield from from_part(part._element, part)


def _template_rpr(tc):
    """Schriftformatierung der Zelle ermitteln (erster Run, sonst Absatzmarke)."""
    for r in tc.iter(qn("w:r")):
        rpr = r.find(qn("w:rPr"))
        if rpr is not None:
            return copy.deepcopy(rpr)
    for p in tc.iter(qn("w:p")):
        ppr = p.find(qn("w:pPr"))
        if ppr is not None:
            rpr = ppr.find(qn("w:rPr"))
            if rpr is not None:
                new = copy.deepcopy(rpr)
                for tag in ("w:ins", "w:del", "w:moveFrom", "w:moveTo"):
                    for el in new.findall(qn(tag)):
                        new.remove(el)
                new.tag = qn("w:rPr")
                return new
    return None


def set_tc_text(tc, text: str, font_size: float | None = None, bold: bool | None = None) -> None:
    """Text in eine Zelle schreiben und dabei die Formatierung der Zelle behalten."""
    rpr = _template_rpr(tc)
    paragraphs = tc.findall(qn("w:p"))
    if not paragraphs:
        p = OxmlElement("w:p")
        tc.append(p)
        paragraphs = [p]
    first = paragraphs[0]
    for extra in paragraphs[1:]:
        tc.remove(extra)
    for child in list(first):
        if child.tag != qn("w:pPr"):
            first.remove(child)
    r = OxmlElement("w:r")
    if rpr is not None:
        r.append(rpr)
    first.append(r)
    run = Run(r, None)  # type: ignore[arg-type]
    lines = text.split("\n")
    for i, line in enumerate(lines):
        if i:
            r.append(OxmlElement("w:br"))
        t = OxmlElement("w:t")
        t.set(qn("xml:space"), "preserve")
        t.text = line
        r.append(t)
    if font_size:
        run.font.size = Pt(font_size)
    if bold is not None:
        run.bold = bold


def _set_tc_text_keep_runs(tc, text: str) -> None:
    """Kurzen Wert (Nr., Datum) setzen, Formatierung exakt behalten."""
    set_tc_text(tc, text)


# --------------------------------------------------------------------------- #
# Ersetzen über Run-Grenzen hinweg
# --------------------------------------------------------------------------- #

def replace_in_paragraph(p: Paragraph, pattern: re.Pattern[str], repl: Callable[[re.Match[str]], str | None]) -> int:
    """Regex-Ersetzung in einem Absatz, auch wenn der Treffer über mehrere Runs verteilt ist.

    ``repl`` gibt den neuen Text zurück oder ``None`` (= Treffer unverändert lassen).
    Formatierung des ersten betroffenen Runs bleibt erhalten.
    """
    runs = p.runs
    if not runs:
        return 0
    texts = [r.text for r in runs]
    full = "".join(texts)
    matches = list(pattern.finditer(full))
    if not matches:
        return 0
    starts: list[int] = []
    pos = 0
    for t in texts:
        starts.append(pos)
        pos += len(t)

    def run_at(offset: int) -> int:
        idx = 0
        for i, s in enumerate(starts):
            if s <= offset and (offset < s + len(texts[i]) or i == len(texts) - 1):
                idx = i
                if offset < s + len(texts[i]):
                    break
        return idx

    count = 0
    for m in reversed(matches):
        new = repl(m)
        if new is None:
            continue
        a, b = m.start(), m.end()
        ra, rb = run_at(a), run_at(b - 1)
        sa, sb = starts[ra], starts[rb]
        if ra == rb:
            texts[ra] = texts[ra][: a - sa] + new + texts[ra][b - sa:]
        else:
            texts[ra] = texts[ra][: a - sa] + new
            for i in range(ra + 1, rb):
                texts[i] = ""
            texts[rb] = texts[rb][b - sb:]
        count += 1
    for r, t in zip(runs, texts):
        if r.text != t:
            r.text = t
    return count


# --------------------------------------------------------------------------- #
# Analyse
# --------------------------------------------------------------------------- #

@dataclass
class DayRow:
    code: str
    day_tc: object
    content_tc: object
    lernfeld_tc: object | None
    hours_tc: object | None


@dataclass
class TemplateInfo:
    path: Path | None = None
    day_rows: dict[str, DayRow] = field(default_factory=dict)
    placeholders: list[str] = field(default_factory=list)
    unknown_placeholders: list[str] = field(default_factory=list)
    nachweis_nr: int | None = None
    vom: dt.date | None = None
    bis: dt.date | None = None
    nr_tc: object | None = None
    vom_tc: object | None = None
    bis_tc: object | None = None
    name_tc: object | None = None
    trainer_tc: object | None = None
    has_signature_date: bool = False
    column_method: str = ""
    issues: list[Issue] = field(default_factory=list)

    @property
    def usable(self) -> bool:
        return bool(self.day_rows) or any(p.startswith("TEXT_") for p in self.placeholders)

    def summary(self) -> str:
        parts = [f"{len(self.day_rows)} Tageszeilen gefunden"
                 + (f" ({', '.join(self.day_rows)})" if self.day_rows else "")]
        if self.placeholders:
            parts.append("Platzhalter: " + ", ".join(self.placeholders))
        else:
            parts.append("keine Platzhalter")
        found = []
        if self.nr_tc is not None:
            found.append("Nachweis-Nr." + (f" ({self.nachweis_nr})" if self.nachweis_nr else ""))
        if self.vom_tc is not None:
            found.append("vom" + (f" ({self.vom:%d.%m.%Y})" if self.vom else ""))
        if self.bis_tc is not None:
            found.append("bis" + (f" ({self.bis:%d.%m.%Y})" if self.bis else ""))
        if self.name_tc is not None:
            found.append("Name")
        if self.trainer_tc is not None:
            found.append("Trainer")
        if self.has_signature_date:
            found.append("Unterschriftsdatum")
        if found:
            parts.append("Felder: " + ", ".join(found))
        return "; ".join(parts)


def _parse_template_date(text: str, year_hint: int | None = None) -> dt.date | None:
    m = SHORT_DATE_RE.search(text)
    if not m:
        return None
    day, month, year = m.group(1), m.group(2), m.group(3)
    if year:
        y = int(year)
        if y < 100:
            y += 2000
    elif year_hint:
        y = year_hint
    else:
        return None
    try:
        return dt.date(y, int(month), int(day))
    except ValueError:
        return None


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


def _analyze(doc: DocxDocument, path: Path | None = None) -> TemplateInfo:
    info = TemplateInfo(path=path)

    # --- Platzhalter ---
    found: list[str] = []
    for p in _iter_paragraphs(doc):
        for m in PLACEHOLDER_RE.finditer(p.text):
            name = m.group(1).upper()
            if name not in found:
                found.append(name)
    info.placeholders = [n for n in found if n in KNOWN_PLACEHOLDERS]
    info.unknown_placeholders = [n for n in found if n not in KNOWN_PLACEHOLDERS]
    if info.unknown_placeholders:
        info.issues.append(Issue(Severity.WARNING, "Unbekannte Platzhalter: " + ", ".join(info.unknown_placeholders)))

    # --- Tabellen: Kopfdaten und Tageszeilen ---
    vom_raw = bis_raw = ""
    for table in _iter_tables(doc):
        lf_col = std_col = None
        for tr in table._tbl.tr_lst:
            cells = _row_cells(tr)
            texts = [_norm(_tc_text(tc)) for _, _, tc in cells]

            # Kopfzeile mit Lernfeld/Std merken (für Spaltenzuordnung)
            for (start, _span, _tc), t in zip(cells, texts):
                if t.startswith("lernfeld"):
                    lf_col = start
                elif t.startswith("std") or t.startswith("stunden"):
                    std_col = start

            for i, ((start, span, tc), t) in enumerate(zip(cells, texts)):
                nxt = cells[i + 1][2] if i + 1 < len(cells) else None
                if nxt is not None and PLACEHOLDER_RE.search(_tc_text(nxt)):
                    nxt = None  # Wertzelle mit Platzhalter wird über den Platzhalter befüllt
                if "ausbildungsnachweis" in t and "nr" in t and nxt is not None and info.nr_tc is None:
                    info.nr_tc = nxt
                    m = re.search(r"\d{1,4}", _tc_text(nxt))
                    info.nachweis_nr = int(m.group(0)) if m else None
                elif (t == "vom" or t.endswith(" vom")) and nxt is not None and info.vom_tc is None:
                    info.vom_tc = nxt
                    vom_raw = _tc_text(nxt)
                elif (t == "bis" or t.endswith(" bis")) and nxt is not None and info.bis_tc is None:
                    info.bis_tc = nxt
                    bis_raw = _tc_text(nxt)
                elif t.startswith("name") and "auszubildend" in t and nxt is not None and info.name_tc is None:
                    if not PLACEHOLDER_RE.search(_tc_text(nxt)):
                        info.name_tc = nxt
                elif (t.startswith("trainer") or t.startswith("dozent") or t.startswith("ausbilder")) and ":" in t \
                        and info.trainer_tc is None and not PLACEHOLDER_RE.search(_tc_text(tc)):
                    info.trainer_tc = tc

            # Tageszeile?
            if not cells:
                continue
            first = texts[0].rstrip(":. ")
            code = DAY_NAMES.get(first)
            if code is None or code in info.day_rows or len(cells) < 2:
                continue
            day_tc = cells[0][2]
            lf_tc = hours_tc = None
            method = ""
            if lf_col is not None:
                lf_tc = next((tc for s, _, tc in cells if s == lf_col), None)
                hours_tc = next((tc for s, _, tc in cells if s == std_col), None) if std_col is not None else None
                method = "Kopfzeile"
            rest = [(s, sp, tc) for s, sp, tc in cells[1:] if tc is not lf_tc and tc is not hours_tc]
            if lf_tc is None and len(cells) >= 4:
                lf_tc, hours_tc = cells[-2][2], cells[-1][2]
                rest = cells[1:-2]
                method = "Position (2. / vorletzte / letzte Zelle)"
            elif lf_tc is None and len(cells) == 3:
                lf_tc = cells[2][2]
                rest = cells[1:2]
                method = "Position (2. / letzte Zelle)"
            if not rest:
                continue
            content_tc = max(rest, key=lambda c: c[1])[2]
            info.day_rows[code] = DayRow(code, day_tc, content_tc, lf_tc, hours_tc)
            info.column_method = info.column_method or method

    # --- Datumsfelder ---
    bis = _parse_template_date(bis_raw)
    vom = _parse_template_date(vom_raw, bis.year if bis else None)
    if vom and bis and vom > bis:  # Jahreswechsel, z. B. 29.12. – 02.01.26
        vom = vom.replace(year=vom.year - 1)
    info.vom, info.bis = vom, bis

    # --- Unterschriftsdatum: Datum im Absatz direkt vor "...Unterschrift..." ---
    body_ps = [x for x in (Paragraph(p, doc) for p in doc.element.body.findall(qn("w:p"))) if x.text.strip()]
    for a, b in zip(body_ps, body_ps[1:]):
        if "unterschrift" in b.text.lower() and re.search(r"\d{1,2}\.\d{1,2}\.\d{2,4}", a.text):
            info.has_signature_date = True
            break

    missing = [c for c in WORKDAY_CODES if c not in info.day_rows]
    if not info.day_rows and not any(p.startswith("TEXT_") for p in info.placeholders):
        info.issues.append(Issue(Severity.ERROR, "Keine Tageszeilen (Mo–Fr in der ersten Spalte) und keine {{TEXT_MO}}-Platzhalter gefunden"))
    elif missing and info.day_rows:
        info.issues.append(Issue(Severity.WARNING, "Tageszeilen fehlen für: " + ", ".join(missing)))
    return info


def analyze_template(path: Path) -> TemplateInfo:
    """Vorlage prüfen und melden, was erkannt wurde."""
    try:
        doc = Document(str(path))
    except Exception as exc:  # noqa: BLE001
        info = TemplateInfo(path=path)
        info.issues.append(Issue(Severity.ERROR, f"Vorlage kann nicht geöffnet werden – ist es eine .docx-Datei? ({type(exc).__name__})"))
        return info
    return _analyze(doc, path)


# --------------------------------------------------------------------------- #
# Befüllen
# --------------------------------------------------------------------------- #

@dataclass
class DayContent:
    date: dt.date | None
    text: str
    lernfeld: str = ""


@dataclass
class ReportData:
    nachweis_nr: int | None
    vom: dt.date | None
    bis: dt.date | None
    days: dict[str, DayContent]
    trainers: list[str] = field(default_factory=list)
    profile_values: dict[str, str] = field(default_factory=dict)
    signature_date: dt.date | None = None


@dataclass
class WriteOptions:
    overwrite_existing: bool = False
    content_font_size: float | None = 8.0
    content_bold: bool | None = True
    lernfeld_font_size: float | None = 12.0
    lernfeld_bold: bool | None = True
    write_lernfeld: bool = True
    write_header_fields: bool = True
    write_hours: bool = False
    hours_value: str = ""
    update_signature_date: bool = True


def _format_like(existing: str, date: dt.date) -> str:
    """Datum im Stil des vorhandenen Werts schreiben ("15.06." / "19.06.26" / "19.06.2026")."""
    e = existing.strip()
    if re.fullmatch(r"\d{1,2}\.\d{1,2}\.?", e):
        return f"{date:%d.%m.}"
    if re.fullmatch(r"\d{1,2}\.\d{1,2}\.\d{4}", e):
        return f"{date:%d.%m.%Y}"
    return f"{date:%d.%m.%y}"


def placeholder_values(data: ReportData) -> dict[str, str]:
    values = {k.upper(): v for k, v in data.profile_values.items()}
    values["NACHWEIS_NR"] = str(data.nachweis_nr) if data.nachweis_nr is not None else ""
    values["VOM"] = f"{data.vom:%d.%m.%Y}" if data.vom else ""
    values["BIS"] = f"{data.bis:%d.%m.%Y}" if data.bis else ""
    values["JAHR"] = str((data.vom or data.bis).year) if (data.vom or data.bis) else ""
    sig = data.signature_date or data.bis
    values["DATUM"] = f"{sig:%d.%m.%Y}" if sig else ""
    values["DOZENT"] = ", ".join(data.trainers)
    for code in WORKDAY_CODES:
        day = data.days.get(code)
        values[f"TEXT_{code.upper()}"] = day.text if day else ""
        values[f"LF_{code.upper()}"] = day.lernfeld if day else ""
        values[f"DATUM_{code.upper()}"] = f"{day.date:%d.%m.%Y}" if day and day.date else ""
    return values


def fill_template(template_path: Path, out_path: Path, data: ReportData, options: WriteOptions) -> list[Issue]:
    """Vorlage kopieren und befüllen. Gibt Meldungen zurück (wirft nur bei Dateifehlern)."""
    issues: list[Issue] = []
    doc = Document(str(template_path))
    info = _analyze(doc, template_path)
    issues.extend(i for i in info.issues if i.severity is Severity.ERROR)
    if not info.usable:
        return issues

    # 1. Platzhalter
    values = placeholder_values(data)
    for p in _iter_paragraphs(doc):
        replace_in_paragraph(p, PLACEHOLDER_RE, lambda m: values.get(m.group(1).upper()) if m.group(1).upper() in values else None)

    # 2. Kopfzellen (nur wenn dort kein Platzhalter stand)
    if options.write_header_fields:
        if info.nr_tc is not None and data.nachweis_nr is not None:
            _set_tc_text_keep_runs(info.nr_tc, str(data.nachweis_nr))
        if info.vom_tc is not None and data.vom:
            _set_tc_text_keep_runs(info.vom_tc, _format_like(_tc_text(info.vom_tc), data.vom))
        if info.bis_tc is not None and data.bis:
            _set_tc_text_keep_runs(info.bis_tc, _format_like(_tc_text(info.bis_tc), data.bis))
        name = data.profile_values.get("NAME") or data.profile_values.get("name")
        if info.name_tc is not None and name:
            _set_tc_text_keep_runs(info.name_tc, name)
        if info.trainer_tc is not None and data.trainers:
            label = _tc_text(info.trainer_tc).split(":", 1)[0]
            _set_tc_text_keep_runs(info.trainer_tc, f"{label}: {', '.join(data.trainers)}")

    # 3. Unterschriftsdatum
    sig = data.signature_date or data.bis
    if options.update_signature_date and sig and info.has_signature_date:
        body_ps = [x for x in (Paragraph(p, doc) for p in doc.element.body.findall(qn("w:p"))) if x.text.strip()]
        for a, b in zip(body_ps, body_ps[1:]):
            if "unterschrift" in b.text.lower():
                n = replace_in_paragraph(
                    a, re.compile(r"\d{1,2}\.\d{1,2}\.\d{2,4}"),
                    lambda m: _format_like(m.group(0), sig),
                )
                if n:
                    break

    # 4. Tageszeilen
    for code, row in info.day_rows.items():
        day = data.days.get(code)
        if day is None:
            continue
        existing = _tc_text(row.content_tc)
        if existing and not PLACEHOLDER_RE.search(existing) and not options.overwrite_existing:
            issues.append(Issue(Severity.INFO, f"{code} hat schon Inhalt und wird nicht überschrieben"))
        elif day.text:
            set_tc_text(row.content_tc, day.text, options.content_font_size or None, options.content_bold)
        if options.write_lernfeld and row.lernfeld_tc is not None and day.lernfeld:
            set_tc_text(row.lernfeld_tc, day.lernfeld, options.lernfeld_font_size or None, options.lernfeld_bold)
        if options.write_hours and row.hours_tc is not None and options.hours_value:
            set_tc_text(row.hours_tc, options.hours_value)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(out_path))
    return issues


# --------------------------------------------------------------------------- #
# Dateiname
# --------------------------------------------------------------------------- #

def safe_filename(name: str) -> str:
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "-", name)
    name = re.sub(r"\s+", " ", name).strip(" .")
    return name or "Berichtsheft.docx"


def build_filename(pattern: str, nr: int | None, vom: dt.date | None, bis: dt.date | None) -> str:
    """``Berichtsheft Woche {NR} ({VOM}-{BIS}).docx`` -> ``Berichtsheft Woche 55 (29.06.26-03.07.26).docx``."""
    name = pattern
    name = name.replace("{NR}", str(nr) if nr is not None else "0")
    name = name.replace("{VOM}", f"{vom:%d.%m.%y}" if vom else "")
    name = name.replace("{BIS}", f"{bis:%d.%m.%y}" if bis else "")
    name = name.replace("{JAHR}", str(vom.year) if vom else "")
    name = name.replace("(-)", "").replace("()", "")
    if name.lower().endswith(".docx"):
        name = name[:-5]
    name = re.sub(r"\s+", " ", name).strip() + ".docx"
    return safe_filename(name)
