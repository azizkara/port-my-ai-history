"""Resolve sediment:// asset pointers to local files in the ChatGPT export."""

from __future__ import annotations

import re
from pathlib import Path

from .models import ImageReference


class ImageResolver:
    """Builds a file index from the export directory and resolves sediment:// pointers."""

    def __init__(self, export_dir: Path) -> None:
        self.export_dir = export_dir
        self._index: dict[str, Path] = {}
        self._build_index()

    def _build_index(self) -> None:
        """Scan the export directory tree and index all files by their file ID prefix."""
        image_exts = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".svg"}

        for path in self.export_dir.rglob("*"):
            if not path.is_file():
                continue
            if path.suffix.lower() not in image_exts:
                continue

            name = path.name
            # Format 1: file_HEXID-sanitized.ext  (e.g. file_0000000026d871fda71ef4241895df64-sanitized.png)
            # Format 2: file_HEXID-UUID.ext  (e.g. file_000000000ab46230972f3aabf082ff8d-6acab26c-...-90.png)
            # Format 3: file-ALPHAID-*.ext  (e.g. file-YUUze1wx5ct3UsboScyA2E-dedc62b2-...-913.png)
            #
            # We extract the file ID and map it as a lookup key.

            if name.startswith("file_"):
                # Extract hex ID: everything between "file_" and the first "-"
                rest = name[5:]  # strip "file_"
                dash_pos = rest.find("-")
                if dash_pos > 0:
                    file_id = "file_" + rest[:dash_pos]
                    self._index[file_id] = path
                else:
                    # No dash — use the whole stem
                    file_id = path.stem
                    self._index[file_id] = path

            elif name.startswith("file-"):
                # Extract alpha ID: "file-XXXXX-rest"
                rest = name[5:]  # strip "file-"
                dash_pos = rest.find("-")
                if dash_pos > 0:
                    file_id = "file-" + rest[:dash_pos]
                    self._index[file_id] = path
                else:
                    file_id = path.stem
                    self._index[file_id] = path

    def resolve(self, asset_pointer: str) -> Path | None:
        """Resolve a sediment:// pointer to a local file path.

        Supported formats:
        - sediment://file_HEXID                         → direct lookup
        - sediment://hash#file_HEXID#page.ext           → extract file_HEXID
        - sediment://file-ALPHAID                       → direct lookup
        """
        if not asset_pointer.startswith("sediment://"):
            return None

        rest = asset_pointer[len("sediment://"):]

        # Format: hash#file_ID#page.ext
        if "#" in rest:
            parts = rest.split("#")
            for part in parts:
                if part.startswith("file_") or part.startswith("file-"):
                    # Strip any extension from page part (e.g. "p_5.jpg")
                    file_id = part
                    return self._index.get(file_id)
            return None

        # Direct: file_HEXID or file-ALPHAID
        file_id = rest
        return self._index.get(file_id)

    def resolve_reference(self, ref: ImageReference) -> ImageReference:
        """Resolve an ImageReference's asset_pointer and set resolved_path."""
        path = self.resolve(ref.asset_pointer)
        ref.resolved_path = path
        return ref

    @property
    def indexed_count(self) -> int:
        return len(self._index)
