"""Parse ChatGPT conversations.json: tree traversal and content extraction."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from .models import Conversation, ImageReference, Message, ParsedContent


def load_conversations(path: Path) -> list[dict]:
    """Load and return raw conversation dicts from conversations.json."""
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _ts_to_dt(ts: float | None) -> datetime | None:
    if ts is None:
        return None
    try:
        return datetime.fromtimestamp(ts, tz=timezone.utc)
    except (OSError, ValueError):
        return None


def _traverse_to_root(mapping: dict, current_node: str) -> list[str]:
    """Walk backward from current_node to root, return node IDs root→leaf order."""
    path = []
    node_id = current_node
    visited = set()
    while node_id and node_id not in visited:
        visited.add(node_id)
        path.append(node_id)
        node = mapping.get(node_id)
        if node is None:
            break
        node_id = node.get("parent")
    path.reverse()
    return path


def _parse_image_pointer(part: dict) -> ImageReference:
    """Parse an image_asset_pointer dict into an ImageReference."""
    return ImageReference(
        asset_pointer=part.get("asset_pointer", ""),
        width=part.get("width"),
        height=part.get("height"),
        size_bytes=part.get("size_bytes"),
        content_type=part.get("content_type", "image_asset_pointer"),
    )


def _parse_content(content: dict) -> list[ParsedContent]:
    """Parse a message's content dict into a list of ParsedContent items."""
    ct = content.get("content_type", "text")

    if ct == "text":
        parts = content.get("parts", [])
        text = "\n".join(str(p) for p in parts if isinstance(p, str))
        if not text.strip():
            return []
        return [ParsedContent(content_type="text", text=text)]

    if ct == "multimodal_text":
        items = []
        parts = content.get("parts", [])
        for part in parts:
            if isinstance(part, str):
                if part.strip():
                    items.append(ParsedContent(content_type="text", text=part))
            elif isinstance(part, dict):
                part_ct = part.get("content_type", "")
                if part_ct == "image_asset_pointer":
                    img = _parse_image_pointer(part)
                    items.append(
                        ParsedContent(
                            content_type="image",
                            images=[img],
                        )
                    )
                # Other dict part types can be added here
        return items

    if ct == "code":
        text = content.get("text", "")
        lang = content.get("language", "")
        resp_fmt = content.get("response_format_name", "")
        if not text.strip():
            return []
        return [
            ParsedContent(
                content_type="code",
                text=text,
                language=lang if lang != "unknown" else "",
            )
        ]

    if ct == "thoughts":
        items = []
        for thought in content.get("thoughts", []):
            text = thought.get("content", "")
            summary = thought.get("summary", "")
            if text.strip():
                items.append(
                    ParsedContent(
                        content_type="thoughts",
                        text=text,
                        thought_summary=summary,
                    )
                )
        return items

    if ct == "reasoning_recap":
        text = content.get("content", "")
        if not text.strip():
            return []
        return [ParsedContent(content_type="reasoning_recap", text=text)]

    if ct == "execution_output":
        text = content.get("text", "")
        if not text.strip():
            return []
        return [ParsedContent(content_type="execution_output", text=text)]

    if ct == "tether_quote":
        text = content.get("text", "")
        url = content.get("url", "")
        domain = content.get("domain", "")
        return [
            ParsedContent(
                content_type="tether_quote", text=text, url=url, domain=domain
            )
        ]

    if ct == "tether_browsing_display":
        result = content.get("result", "")
        summary = content.get("summary", "")
        text = summary or result or ""
        if not text.strip():
            return []
        return [ParsedContent(content_type="tether_browsing_display", text=text)]

    if ct == "computer_output":
        screenshot = content.get("screenshot", {})
        items = []
        if screenshot and screenshot.get("asset_pointer", "").startswith("sediment://"):
            img = _parse_image_pointer(screenshot)
            items.append(
                ParsedContent(
                    content_type="computer_output",
                    text="[Computer use screenshot — may not be available in export]",
                    images=[img],
                )
            )
        else:
            items.append(
                ParsedContent(
                    content_type="computer_output",
                    text="[Computer use screenshot — not available in export]",
                )
            )
        return items

    if ct == "system_error":
        name = content.get("name", "Error")
        text = content.get("text", "")
        return [ParsedContent(content_type="system_error", text=f"{name}: {text}")]

    if ct == "user_editable_context":
        # System context — skip silently
        return []

    # Fallback for unknown types
    parts = content.get("parts", [])
    text = content.get("text", "")
    if parts:
        text = "\n".join(str(p) for p in parts if isinstance(p, str))
    if text.strip():
        return [ParsedContent(content_type=ct, text=text)]
    return []


def _parse_message(node: dict) -> Message | None:
    """Parse a mapping node into a Message, or None if not a real message."""
    msg_data = node.get("message")
    if msg_data is None:
        return None

    author = msg_data.get("author", {})
    role = author.get("role", "unknown")
    weight = msg_data.get("weight", 1.0)

    # Skip weight-0 messages (pruned branches)
    if weight == 0.0:
        return None

    content_data = msg_data.get("content", {})
    content_type = content_data.get("content_type", "text")
    parsed = _parse_content(content_data)

    # Skip empty messages
    if not parsed:
        return None

    create_time = _ts_to_dt(msg_data.get("create_time"))
    model_slug = (msg_data.get("metadata", {}).get("model_slug") or "")

    return Message(
        id=node.get("id", ""),
        role=role,
        content_type=content_type,
        content=parsed,
        create_time=create_time,
        model_slug=model_slug,
        weight=weight,
    )


def parse_conversation(raw: dict) -> Conversation:
    """Parse a single raw conversation dict into a Conversation model."""
    conv_id = raw.get("conversation_id") or raw.get("id", "")
    title = raw.get("title", "Untitled")
    create_time = _ts_to_dt(raw.get("create_time"))
    update_time = _ts_to_dt(raw.get("update_time"))
    model_slug = raw.get("default_model_slug", "")

    mapping = raw.get("mapping", {})
    current_node = raw.get("current_node", "")

    # Traverse from current_node to root
    node_path = _traverse_to_root(mapping, current_node)

    messages: list[Message] = []
    first_user_msg = ""

    for node_id in node_path:
        node = mapping.get(node_id, {})
        msg = _parse_message(node)
        if msg is None:
            continue

        # Skip system messages at the start
        if msg.role == "system" and not messages:
            continue

        messages.append(msg)

        if msg.role == "user" and not first_user_msg:
            # Grab text from first text content piece
            for pc in msg.content:
                if pc.content_type == "text" and pc.text.strip():
                    first_user_msg = pc.text.strip()[:200]
                    break

    return Conversation(
        id=conv_id,
        title=title,
        create_time=create_time,
        update_time=update_time,
        messages=messages,
        model_slug=model_slug,
        message_count=len(messages),
        first_user_message=first_user_msg,
    )
