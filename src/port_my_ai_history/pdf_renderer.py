"""Render conversations to PDF via Jinja2 + WeasyPrint."""

from __future__ import annotations

import base64
import html
from pathlib import Path

from .image_resolver import ImageResolver
from .models import Conversation, ImageReference, ParsedContent
from .renderer import output_filename, role_label, visible_messages

try:
    from jinja2 import Environment, FileSystemLoader
    import weasyprint

    HAS_PDF_DEPS = True
except ImportError:
    HAS_PDF_DEPS = False


TEMPLATES_DIR = Path(__file__).parent / "templates"
MAX_IMAGE_WIDTH = 800


def _image_to_base64(img: ImageReference, resolver: ImageResolver | None) -> str | None:
    """Resolve and base64-encode an image, resizing if too wide."""
    if resolver:
        resolver.resolve_reference(img)

    if not img.resolved_path or not img.resolved_path.exists():
        return None

    try:
        from PIL import Image
        import io

        with Image.open(img.resolved_path) as pil_img:
            if pil_img.width > MAX_IMAGE_WIDTH:
                ratio = MAX_IMAGE_WIDTH / pil_img.width
                new_height = int(pil_img.height * ratio)
                pil_img = pil_img.resize(
                    (MAX_IMAGE_WIDTH, new_height), Image.LANCZOS
                )

            buf = io.BytesIO()
            fmt = "PNG" if img.resolved_path.suffix.lower() == ".png" else "JPEG"
            if pil_img.mode in ("RGBA", "P") and fmt == "JPEG":
                pil_img = pil_img.convert("RGB")
            pil_img.save(buf, format=fmt, quality=85)
            b64 = base64.b64encode(buf.getvalue()).decode("ascii")
            mime = "image/png" if fmt == "PNG" else "image/jpeg"
            return f"data:{mime};base64,{b64}"
    except Exception:
        return None


def _render_content_html(
    pc: ParsedContent, resolver: ImageResolver | None
) -> str:
    """Render a ParsedContent block to HTML for the PDF template."""
    from .markdown_converter import md_to_html

    if pc.content_type == "text":
        return md_to_html(pc.text)

    if pc.content_type == "image":
        parts = []
        for img in pc.images:
            data_uri = _image_to_base64(img, resolver)
            if data_uri:
                parts.append(f'<img src="{data_uri}" alt="image">')
            else:
                parts.append('<div class="image-unavailable">Image not available in export</div>')
        return "\n".join(parts)

    if pc.content_type == "code":
        lang = pc.language or ""
        escaped = html.escape(pc.text)
        return f'<pre><code class="language-{lang}">{escaped}</code></pre>'

    if pc.content_type == "thoughts":
        summary_html = (
            f'<div class="thought-summary">{html.escape(pc.thought_summary)}</div>'
            if pc.thought_summary
            else ""
        )
        return f'<div class="thoughts">{summary_html}{md_to_html(pc.text)}</div>'

    if pc.content_type == "reasoning_recap":
        return f"<p><em>{html.escape(pc.text)}</em></p>"

    if pc.content_type == "execution_output":
        return f"<pre>{html.escape(pc.text)}</pre>"

    if pc.content_type == "tether_quote":
        source = f"<footer>— {html.escape(pc.domain)}</footer>" if pc.domain else ""
        return f"<blockquote>{md_to_html(pc.text)}{source}</blockquote>"

    if pc.content_type == "tether_browsing_display":
        return f"<p><em>{html.escape(pc.text.strip())}</em></p>"

    if pc.content_type == "computer_output":
        parts = [f"<p><em>{html.escape(pc.text)}</em></p>"]
        for img in pc.images:
            data_uri = _image_to_base64(img, resolver)
            if data_uri:
                parts.append(f'<img src="{data_uri}" alt="screenshot">')
        return "\n".join(parts)

    if pc.content_type == "system_error":
        return f'<p class="system-error">{html.escape(pc.text)}</p>'

    # Fallback
    return f"<p>{html.escape(pc.text)}</p>"


def render_conversation_pdf(
    conv: Conversation,
    output_dir: Path,
    resolver: ImageResolver | None = None,
    include_thoughts: bool = False,
) -> Path:
    """Render a conversation to a PDF file in output_dir.

    Returns the path to the generated .pdf file.
    Requires jinja2 and weasyprint (install with pip install port-my-ai-history[pdf]).
    """
    if not HAS_PDF_DEPS:
        raise RuntimeError(
            "PDF dependencies not installed. Run: pip install port-my-ai-history[pdf]"
        )

    filename = output_filename(conv, ext=".pdf")
    pdf_path = output_dir / filename
    pdf_path.parent.mkdir(parents=True, exist_ok=True)

    messages = visible_messages(conv, include_thoughts=include_thoughts)

    # Build template data
    template_messages = []
    for msg in messages:
        blocks = []
        for pc in msg.content:
            blocks.append(_render_content_html(pc, resolver))
        template_messages.append(
            {
                "role": msg.role,
                "label": role_label(msg.role),
                "blocks": blocks,
            }
        )

    # Load CSS
    css_path = TEMPLATES_DIR / "styles.css"
    css = css_path.read_text(encoding="utf-8")

    # Render HTML
    env = Environment(
        loader=FileSystemLoader(str(TEMPLATES_DIR)), autoescape=False
    )
    template = env.get_template("conversation.html.j2")
    html_content = template.render(
        title=conv.title,
        created=conv.create_time.strftime("%Y-%m-%d %H:%M") if conv.create_time else "",
        model=conv.model_slug,
        messages=template_messages,
        css=css,
    )

    # Generate PDF
    wp = weasyprint.HTML(string=html_content)
    wp.write_pdf(str(pdf_path))

    return pdf_path
