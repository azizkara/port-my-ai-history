"""Render conversations to Markdown files with linked images."""

from __future__ import annotations

import shutil
from pathlib import Path

from .image_resolver import ImageResolver
from .models import Conversation, ImageReference, Message, ParsedContent
from .renderer import output_filename, role_label, visible_messages


def _render_content_md(
    pc: ParsedContent,
    image_counter: list[int],
    images_dir: Path,
    resolver: ImageResolver | None,
) -> str:
    """Render a single ParsedContent to Markdown, copying images as needed."""

    if pc.content_type == "text":
        return pc.text + "\n"

    if pc.content_type == "image":
        lines = []
        for img in pc.images:
            path = _copy_image(img, image_counter, images_dir, resolver)
            if path:
                lines.append(f"![image]({path})\n")
            else:
                lines.append("*[Image not available in export]*\n")
        return "\n".join(lines)

    if pc.content_type == "code":
        lang = pc.language or ""
        return f"```{lang}\n{pc.text}\n```\n"

    if pc.content_type == "thoughts":
        header = f"*{pc.thought_summary}*\n\n" if pc.thought_summary else ""
        # Indent each line as blockquote
        quoted = "\n".join(f"> {line}" for line in pc.text.split("\n"))
        return f"{header}{quoted}\n"

    if pc.content_type == "reasoning_recap":
        return f"*{pc.text}*\n"

    if pc.content_type == "execution_output":
        return f"```output\n{pc.text}\n```\n"

    if pc.content_type == "tether_quote":
        quoted = "\n".join(f"> {line}" for line in pc.text.split("\n"))
        source = f"— {pc.domain}" if pc.domain else ""
        return f"{quoted}\n{source}\n"

    if pc.content_type == "tether_browsing_display":
        return f"*{pc.text.strip()}*\n"

    if pc.content_type == "computer_output":
        lines = [f"*{pc.text}*\n"]
        for img in pc.images:
            path = _copy_image(img, image_counter, images_dir, resolver)
            if path:
                lines.append(f"![screenshot]({path})\n")
        return "\n".join(lines)

    if pc.content_type == "system_error":
        return f"**{pc.text}**\n"

    # Fallback
    return pc.text + "\n"


def _copy_image(
    img: ImageReference,
    counter: list[int],
    images_dir: Path,
    resolver: ImageResolver | None,
) -> str | None:
    """Copy image to images/ dir, return relative path or None if unresolvable."""
    if resolver:
        resolver.resolve_reference(img)

    if img.resolved_path and img.resolved_path.exists():
        counter[0] += 1
        ext = img.resolved_path.suffix.lower()
        dest_name = f"img-{counter[0]:03d}{ext}"
        images_dir.mkdir(parents=True, exist_ok=True)
        dest = images_dir / dest_name
        shutil.copy2(img.resolved_path, dest)
        return f"./images/{dest_name}"

    return None


def render_conversation_markdown(
    conv: Conversation,
    output_dir: Path,
    resolver: ImageResolver | None = None,
    include_thoughts: bool = False,
) -> Path:
    """Render a conversation to a Markdown file in output_dir.

    Returns the path to the generated .md file.
    """
    slug = output_filename(conv, ext="")  # e.g. "fix-login-bug_a1b2c3d4"
    conv_dir = output_dir / slug
    md_path = conv_dir / "conversation.md"
    images_dir = conv_dir / "images"

    messages = visible_messages(conv, include_thoughts=include_thoughts)
    image_counter = [0]

    lines: list[str] = []

    # Header
    lines.append(f"# {conv.title}\n")
    if conv.create_time:
        lines.append(
            f"*Created: {conv.create_time.strftime('%Y-%m-%d %H:%M')} UTC*"
        )
    if conv.model_slug:
        lines.append(f"  \n*Model: {conv.model_slug}*")
    lines.append("\n---\n")

    for msg in messages:
        label = role_label(msg.role)
        lines.append(f"## {label}\n")

        for pc in msg.content:
            rendered = _render_content_md(pc, image_counter, images_dir, resolver)
            lines.append(rendered)

        lines.append("")  # blank line between messages

    md_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.write_text("\n".join(lines), encoding="utf-8")
    return md_path
