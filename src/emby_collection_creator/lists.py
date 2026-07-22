"""Parsing and resolving research list files into TMDb IDs."""

import re

from attrs import define

IMDB_RE = re.compile(r"\btt\d{6,}\b")
YEAR_RE = re.compile(r"^(19|20)\d{2}$")


@define
class ListEntry:
    """A single movie parsed from a research list file."""

    imdb_id: str
    title: str
    year: int | None


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
            )
        )
    return entries


def _pick_year(cells: list[str]) -> int | None:
    for cell in cells:
        if YEAR_RE.match(cell):
            return int(cell)
    return None


def _pick_title(cells: list[str], imdb_id: str) -> str:
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


def _is_year_mismatch(entry_year: int | None, found_year: int | None) -> bool:
    """Flag entries whose stated year is well off the TMDb release year."""
    if entry_year is None or found_year is None:
        return False
    return abs(entry_year - found_year) > 1


async def resolve_entries(tmdb, entries: list[ListEntry]) -> dict:
    """Resolve IMDb IDs to TMDb IDs, reporting unresolved and mismatched entries."""
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

        if _is_year_mismatch(entry.year, found_year):
            mismatched.append(
                {
                    "imdb_id": entry.imdb_id,
                    "expected": f"{entry.title} ({entry.year})",
                    "tmdb_says": f"{found.get('title', '')} ({found_year})",
                }
            )

    return {
        "resolved": resolved,
        "unresolved": unresolved,
        "mismatched": mismatched,
    }
