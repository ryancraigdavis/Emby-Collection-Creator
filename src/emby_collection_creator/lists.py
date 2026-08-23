"""Parsing and resolving research list files into TMDb IDs."""

import re
import unicodedata

from attrs import define, field

IMDB_RE = re.compile(r"\btt\d{6,}\b")
YEAR_RE = re.compile(r"^(19|20)\d{2}$")
STOPWORDS = {
    "the", "and", "for", "aka", "dir", "vol", "with", "from",
    "il", "la", "le", "lo", "gli", "un", "una", "del", "della", "di",
}


@define
class ListEntry:
    """A single movie parsed from a research list file."""

    imdb_id: str
    title: str
    year: int | None
    row_text: str = field(default="", eq=False)


def parse_list_file(text: str) -> list[ListEntry]:
    """Extract entries from a list file. Lines without an IMDb ID are ignored."""
    entries: list[ListEntry] = []
    seen: set[str] = set()
    for line in text.splitlines():
        match = IMDB_RE.search(line)
        if not match:
            continue
        imdb_id = match.group(0)
        if imdb_id in seen:
            continue
        seen.add(imdb_id)
        cells = [c.strip() for c in line.split("|") if c.strip()]
        entries.append(
            ListEntry(
                imdb_id=imdb_id,
                title=_pick_title(cells, imdb_id),
                year=_pick_year(cells),
                row_text=line.replace(imdb_id, " "),
            )
        )
    return entries


def _pick_year(cells: list[str]) -> int | None:
    for cell in cells:
        if YEAR_RE.match(cell):
            return int(cell)
    return None


def _pick_title(cells: list[str], imdb_id: str) -> str:
    if len(cells) >= 4 and cells[0].isdigit():
        titled = cells[1]
        if imdb_id not in titled and not YEAR_RE.match(titled):
            return titled
    candidates = []
    for cell in cells:
        text = cell.replace(imdb_id, "").strip(" -|\t")
        if not text or text.isdigit() or YEAR_RE.match(text):
            continue
        candidates.append(text)
    return max(candidates, key=len) if candidates else ""


def _release_year(release_date: str | None) -> int | None:
    if not release_date:
        return None
    return int(release_date[:4])


def _norm_tokens(text: str) -> set[str]:
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = re.sub(r"[^a-z0-9 ]+", " ", text.lower())
    return {t for t in text.split() if len(t) >= 3 and t not in STOPWORDS}


def _is_year_mismatch(entry_year: int | None, found_year: int | None) -> bool:
    """Flag entries whose stated year is well off the TMDb release year."""
    if entry_year is None or found_year is None:
        return False
    return abs(entry_year - found_year) > 1


def _is_title_mismatch(row_text: str, found: dict) -> bool:
    """Flag when none of the TMDb title's significant words appear in the row.

    Compares against both the localized title and the original title, so a
    row listing the English name, the original name, or both will match. A
    wrong ID that resolves to an unrelated film shares no words and is flagged.
    """
    tmdb_tokens = _norm_tokens(found.get("title", "")) | _norm_tokens(
        found.get("original_title", "")
    )
    if not tmdb_tokens:
        return False
    return tmdb_tokens.isdisjoint(_norm_tokens(row_text))


async def resolve_entries(tmdb, entries: list[ListEntry]) -> dict:
    """Resolve IMDb IDs to TMDb IDs, reporting unresolved and mismatched entries.

    'mismatched' entries resolved to a movie whose year or title disagrees with
    the file — a wrong ID pointing at a real but unrelated film. They are kept
    in 'resolved' but callers should exclude them from an import by default.
    """
    resolved: list[dict] = []
    unresolved: list[dict] = []
    mismatched: list[dict] = []

    for entry in entries:
        found = await tmdb.find_by_imdb_id(entry.imdb_id)
        if not found:
            unresolved.append({"imdb_id": entry.imdb_id, "title": entry.title})
            continue

        found_year = _release_year(found.get("release_date"))
        resolved.append({"imdb_id": entry.imdb_id, "tmdb_id": str(found["id"])})

        reasons = []
        if _is_year_mismatch(entry.year, found_year):
            reasons.append("year")
        if _is_title_mismatch(entry.row_text or entry.title, found):
            reasons.append("title")
        if reasons:
            mismatched.append(
                {
                    "imdb_id": entry.imdb_id,
                    "expected": f"{entry.title} ({entry.year})",
                    "tmdb_says": f"{found.get('title', '')} ({found_year})",
                    "reason": "+".join(reasons),
                }
            )

    return {
        "resolved": resolved,
        "unresolved": unresolved,
        "mismatched": mismatched,
    }
