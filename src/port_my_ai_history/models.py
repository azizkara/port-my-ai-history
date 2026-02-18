"""Data models for parsed ChatGPT conversations."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path


@dataclass
class ImageReference:
    """An image referenced in a conversation message."""

    asset_pointer: str  # e.g. "sediment://file_00000000..."
    width: int | None = None
    height: int | None = None
    size_bytes: int | None = None
    resolved_path: Path | None = None  # set after resolution
    content_type: str = "image_asset_pointer"  # or "dall_e" etc.


@dataclass
class ParsedContent:
    """A single piece of rendered content from a message."""

    content_type: str  # text, code, multimodal_text, thoughts, etc.
    text: str = ""
    language: str = ""  # for code blocks
    images: list[ImageReference] = field(default_factory=list)
    url: str = ""  # for tether_quote
    domain: str = ""  # for tether_quote
    thought_summary: str = ""  # for thoughts


@dataclass
class Message:
    """A single message in a conversation."""

    id: str
    role: str  # user, assistant, system, tool
    content_type: str
    content: list[ParsedContent]
    create_time: datetime | None = None
    model_slug: str = ""
    weight: float = 1.0


@dataclass
class Conversation:
    """A fully parsed conversation."""

    id: str
    title: str
    create_time: datetime | None = None
    update_time: datetime | None = None
    messages: list[Message] = field(default_factory=list)
    model_slug: str = ""
    message_count: int = 0
    first_user_message: str = ""


@dataclass
class ManifestEntry:
    """An entry in the YAML manifest representing one conversation."""

    id: str
    title: str
    create_time: str  # ISO format string
    update_time: str
    message_count: int
    model: str
    preview: str  # first user message preview
    project: str = ""
    tags: list[str] = field(default_factory=list)
    include: bool = True
