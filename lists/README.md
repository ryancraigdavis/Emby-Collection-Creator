# Research Lists

Drop movie list files here (e.g. produced by a Claude research task), then turn one
into a TMDb list + synced Emby collection.

## Format

Any file where each movie line contains an IMDb ID. A markdown table works well:

```markdown
| # | Movie Title | Year | IMDb ID |
|---|-------------|------|---------|
| 1 | Mortal Kombat | 1995 | tt0113855 |
| 2 | Double Dragon | 1994 | tt0106761 |
```

Rules:

- Lines without an IMDb ID (`tt` + digits) are ignored, so headers and prose are fine.
- Column order doesn't matter; the year and title are detected per line.
- Duplicate IMDb IDs are collapsed.

## Workflow

1. Drop the file in this folder.
2. Dry run to see the verification report:
   `create_tmdb_list_from_file(file_path, name, dry_run=true)`
3. Review `unresolved` (bad IMDb IDs) and `mismatched` (ID points at a different
   year than the file claims).
4. Re-run without `dry_run` to create and populate the TMDb list.
5. Point a collection at it with `set_collection_criteria(collection_id, tmdb_list_id=...)`
   and `sync_collection`.
