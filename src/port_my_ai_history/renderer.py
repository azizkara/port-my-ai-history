"""Shared rendering logic: content type dispatch, message filtering, slugification."""

from __future__ import annotations

import re
import unicodedata

from .models import Conversation, Message


def slugify(text: str, max_length: int = 60) -> str:
    """Convert text to a filesystem-safe slug."""
    # Normalize unicode
    text = unicodedata.normalize("NFKD", text)
    text = text.encode("ascii", "ignore").decode("ascii")
    # Lowercase, replace non-alphanumeric with hyphens
    text = re.sub(r"[^\w\s-]", "", text.lower())
    text = re.sub(r"[-\s]+", "-", text).strip("-")
    if not text:
        text = "untitled"
    return text[:max_length]


def output_filename(conv: Conversation, ext: str = ".md") -> str:
    """Generate output filename: {slug}_{id_prefix}{ext}."""
    slug = slugify(conv.title)
    id_prefix = conv.id[:8] if conv.id else "00000000"
    return f"{slug}_{id_prefix}{ext}"


def visible_messages(
    conv: Conversation, include_thoughts: bool = False
) -> list[Message]:
    """Filter messages to those that should appear in output."""
    result = []
    for msg in conv.messages:
        # Skip tool messages (browsing internals, code interpreter setup)
        if msg.role == "tool":
            # Keep execution_output and tether_quote from tool role
            visible_content = [
                pc
                for pc in msg.content
                if pc.content_type
                in ("execution_output", "tether_quote", "tether_browsing_display")
            ]
            if not visible_content:
                continue
            # Replace content with filtered version
            msg = Message(
                id=msg.id,
                role=msg.role,
                content_type=msg.content_type,
                content=visible_content,
                create_time=msg.create_time,
                model_slug=msg.model_slug,
                weight=msg.weight,
            )

        # Filter thoughts if not included
        if not include_thoughts:
            filtered = [pc for pc in msg.content if pc.content_type != "thoughts"]
            if not filtered:
                continue
            msg = Message(
                id=msg.id,
                role=msg.role,
                content_type=msg.content_type,
                content=filtered,
                create_time=msg.create_time,
                model_slug=msg.model_slug,
                weight=msg.weight,
            )

        result.append(msg)
    return result


def role_label(role: str) -> str:
    """Human-readable label for a message role."""
    return {
        "user": "You",
        "assistant": "ChatGPT",
        "system": "System",
        "tool": "Tool",
    }.get(role, role.title())
