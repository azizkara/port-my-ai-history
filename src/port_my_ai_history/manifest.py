"""YAML manifest generation, reading, and merge logic."""

from __future__ import annotations

from pathlib import Path

from ruamel.yaml import YAML

from .models import Conversation, ManifestEntry


def _yaml() -> YAML:
    y = YAML()
    y.default_flow_style = False
    y.width = 120
    y.preserve_quotes = True
    return y


def conversation_to_entry(conv: Conversation) -> ManifestEntry:
    """Convert a parsed Conversation into a ManifestEntry."""
    create_str = (
        conv.create_time.strftime("%Y-%m-%d %H:%M") if conv.create_time else "unknown"
    )
    update_str = (
        conv.update_time.strftime("%Y-%m-%d %H:%M") if conv.update_time else "unknown"
    )
    return ManifestEntry(
        id=conv.id,
        title=conv.title,
        create_time=create_str,
        update_time=update_str,
        message_count=conv.message_count,
        model=conv.model_slug,
        preview=conv.first_user_message[:150] if conv.first_user_message else "",
        project="",
        include=True,
    )


def _entry_to_dict(entry: ManifestEntry) -> dict:
    d = {
        "id": entry.id,
        "title": entry.title,
        "created": entry.create_time,
        "updated": entry.update_time,
        "messages": entry.message_count,
        "model": entry.model,
        "preview": entry.preview,
        "project": entry.project,
    }
    if entry.tags:
        d["tags"] = entry.tags
    d["include"] = entry.include
    return d


def _dict_to_entry(d: dict) -> ManifestEntry:
    return ManifestEntry(
        id=d.get("id", ""),
        title=d.get("title", ""),
        create_time=str(d.get("created", "")),
        update_time=str(d.get("updated", "")),
        message_count=d.get("messages", 0),
        model=d.get("model", ""),
        preview=d.get("preview", ""),
        project=d.get("project", ""),
        tags=list(d.get("tags", [])),
        include=d.get("include", True),
    )


def write_manifest(
    entries: list[ManifestEntry],
    path: Path,
    projects: list[str] | None = None,
) -> None:
    """Write a manifest YAML file, sorted by date (newest first)."""
    # Sort by create_time descending
    sorted_entries = sorted(entries, key=lambda e: e.create_time, reverse=True)
    data: dict = {"version": 1}
    if projects:
        data["projects"] = projects
    data["conversations"] = [_entry_to_dict(e) for e in sorted_entries]
    y = _yaml()
    with open(path, "w", encoding="utf-8") as f:
        y.dump(data, f)


def read_manifest(path: Path) -> list[ManifestEntry]:
    """Read manifest entries from an existing YAML file."""
    y = _yaml()
    with open(path, encoding="utf-8") as f:
        data = y.load(f)
    if data is None:
        return []
    return [_dict_to_entry(d) for d in data.get("conversations", [])]


def merge_manifest(
    existing_path: Path, new_entries: list[ManifestEntry]
) -> list[ManifestEntry]:
    """Merge new scan results with an existing manifest, preserving user edits.

    User-editable fields (project, include) are kept from the existing manifest.
    Metadata (title, message count, etc.) is updated from the new scan.
    New conversations are added; removed conversations are dropped.
    """
    existing = read_manifest(existing_path)
    existing_by_id = {e.id: e for e in existing}

    merged: list[ManifestEntry] = []
    for new_entry in new_entries:
        old = existing_by_id.get(new_entry.id)
        if old:
            # Preserve user edits
            new_entry.project = old.project
            new_entry.tags = old.tags
            new_entry.include = old.include
        merged.append(new_entry)

    return merged


def read_projects(path: Path) -> list[str]:
    """Read the projects list from a manifest YAML file."""
    y = _yaml()
    with open(path, encoding="utf-8") as f:
        data = y.load(f)
    if data is None:
        return []
    return list(data.get("projects", []))
