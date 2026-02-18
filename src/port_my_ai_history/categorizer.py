"""Categorize conversations into projects using the Claude CLI."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .models import ManifestEntry


@dataclass
class CategoryResult:
    """Result of categorizing a single conversation."""

    id: str
    project: str
    tags: list[str]
    confidence: int = 100  # 0-100, how confident the model is in the assignment


def _check_claude_cli() -> str:
    """Find the claude CLI binary, or exit with a helpful message."""
    path = shutil.which("claude")
    if not path:
        raise SystemExit(
            "The 'claude' CLI is required for categorization but was not found.\n"
            "Install it from: https://docs.anthropic.com/en/docs/claude-code"
        )
    return path


def extract_conversation_snippets(
    conversations_json: Path, max_chars: int = 500
) -> dict[str, str]:
    """Load conversations.json and extract a text snippet from each conversation.

    Returns a dict mapping conversation ID to a snippet of the first few user messages.
    """
    with open(conversations_json, encoding="utf-8") as f:
        raw_convs = json.load(f)

    snippets: dict[str, str] = {}

    for raw in raw_convs:
        conv_id = raw.get("conversation_id") or raw.get("id", "")
        if not conv_id:
            continue

        mapping = raw.get("mapping", {})
        current_node = raw.get("current_node", "")

        # Walk backward to get node path
        path = []
        node_id = current_node
        visited = set()
        while node_id and node_id not in visited:
            visited.add(node_id)
            path.append(node_id)
            node = mapping.get(node_id, {})
            node_id = node.get("parent")
        path.reverse()

        # Extract text from user messages
        texts = []
        total = 0
        for nid in path:
            node = mapping.get(nid, {})
            msg = node.get("message")
            if not msg:
                continue
            role = msg.get("author", {}).get("role", "")
            if role != "user":
                continue
            parts = msg.get("content", {}).get("parts", [])
            for part in parts:
                if isinstance(part, str) and part.strip():
                    texts.append(part.strip())
                    total += len(part)
                    if total >= max_chars:
                        break
            if total >= max_chars:
                break

        snippet = "\n".join(texts)[:max_chars]
        if snippet:
            snippets[conv_id] = snippet

    return snippets


def _call_claude(claude_path: str, prompt: str) -> str:
    """Run a prompt through the Claude CLI and return the text response."""
    env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}

    result = subprocess.run(
        [claude_path, "-p", prompt, "--output-format", "json"],
        capture_output=True,
        text=True,
        timeout=300,
        env=env,
    )

    if result.returncode != 0:
        raise RuntimeError(f"Claude CLI failed: {result.stderr.strip()}")

    envelope = json.loads(result.stdout)
    return envelope.get("result", "")


def generate_project_descriptions(
    claude_path: str,
    projects: list[str],
    entries: list[ManifestEntry],
    snippets: dict[str, str] | None = None,
) -> dict[str, str]:
    """Ask Claude to describe each project based on conversations already assigned to it."""
    # Build a sample of conversations per project
    by_project: dict[str, list[dict]] = {p: [] for p in projects}
    for e in entries:
        if e.project in by_project and len(by_project[e.project]) < 8:
            sample: dict = {"title": e.title}
            if snippets and e.id in snippets:
                sample["content"] = snippets[e.id][:200]
            elif e.preview:
                sample["preview"] = e.preview
            by_project[e.project].append(sample)

    project_samples = json.dumps(by_project, indent=2)

    prompt = f"""\
Below are project names and sample conversations assigned to each project. \
Write a 1-2 sentence description of what each project is actually about, \
based on the conversation content. Focus on what distinguishes this project \
from general conversations on similar topics.

{project_samples}

Respond with ONLY a JSON object mapping each project name to its description string. No other text."""

    response = _call_claude(claude_path, prompt)
    return json.loads(_parse_response_text(response))


def _parse_response_text(text: str) -> str:
    """Strip optional markdown code fences from a response."""
    text = text.strip()
    match = re.match(r"```(?:json)?\s*\n?(.*?)\n?\s*```", text, re.DOTALL)
    if match:
        text = match.group(1).strip()
    return text


def _build_prompt(
    projects: list[str],
    entries: list[ManifestEntry],
    snippets: dict[str, str] | None = None,
    project_descriptions: dict[str, str] | None = None,
) -> str:
    if project_descriptions:
        project_list = "\n".join(
            f"- {p}: {project_descriptions.get(p, '')}" for p in projects
        )
    else:
        project_list = "\n".join(f"- {p}" for p in projects)
    items = []
    for e in entries:
        item: dict = {"id": e.id, "title": e.title}
        if snippets and e.id in snippets:
            item["content"] = snippets[e.id]
        else:
            item["preview"] = e.preview
        items.append(item)
    conversations_json = json.dumps(items, indent=2)

    return f"""\
You are a strict conversation categorizer. Assign each conversation to a project ONLY if it is specifically about that project's domain.

Allowed project names:
{project_list}

For each conversation:
1. Assign exactly ONE primary project as "project" — but ONLY if the conversation is specifically about that project
2. Optionally assign secondary projects as "tags" — only where >=80% confident
3. Provide a "confidence" score (0-100) for your project assignment:
   - 90-100: Clearly belongs to this project, no doubt
   - 70-89: Likely belongs but could be debatable
   - 50-69: Uncertain, could go either way
   - 0-49: Weak match, mostly guessing
   - If project is "" (unassigned), set confidence to 100 (you're confident it doesn't fit)

CRITICAL: Be very selective. Most people have many casual conversations that don't belong to any project. These MUST be left unassigned:
- General knowledge questions (science, math, history, trivia, explanations)
- Generic health/medical questions not tied to a specific fitness program
- Cooking, recipes, food questions
- General shopping/product recommendations
- Household tips (cleaning, stain removal, etc.) unless clearly tied to a specific home renovation project
- Entertainment discussions (TV shows, movies, books, sports rules)
- General financial questions (savings, investments, taxes) unless specifically about a listed project
- School homework, essays, worksheets
- Travel planning, trip itineraries
- Image generation requests (DALL-E)
- Generic tech questions not tied to a specific coding project

Only assign a project when the conversation is CLEARLY and DIRECTLY about work being done on that specific project. When in doubt, leave it unassigned.

Rules:
- Only use project names from the list above — do not invent new ones
- Set "project" to "" (empty string) if no project is a clear fit — do NOT force a match
- "tags" should NOT include the primary project
- "tags" can be empty

Respond with ONLY a JSON array. Each element must have:
- "id": the conversation id (string)
- "project": the best-match project name, or "" if no good fit (string)
- "tags": list of secondary project names (array of strings, can be empty)
- "confidence": how confident you are in the project assignment (integer, 0-100)

Here are the conversations to categorize:

{conversations_json}"""


def _parse_response(text: str) -> list[dict]:
    """Parse the CLI response as a JSON array, handling optional markdown code fences."""
    return json.loads(_parse_response_text(text))


def categorize_batch(
    claude_path: str,
    entries: list[ManifestEntry],
    projects: list[str],
    snippets: dict[str, str] | None = None,
    project_descriptions: dict[str, str] | None = None,
    max_retries: int = 2,
) -> list[CategoryResult]:
    """Categorize a batch of conversations with a single CLI call."""
    project_set = set(projects)
    prompt = _build_prompt(projects, entries, snippets, project_descriptions)

    raw = None
    for attempt in range(max_retries + 1):
        try:
            response_text = _call_claude(claude_path, prompt)
            raw = _parse_response(response_text)
            break
        except (json.JSONDecodeError, RuntimeError, subprocess.TimeoutExpired):
            if attempt == max_retries:
                return []  # skip this batch after all retries exhausted

    if raw is None:
        return []

    results = []
    entry_ids = {e.id for e in entries}
    for item in raw:
        cid = item.get("id", "")
        if cid not in entry_ids:
            continue
        project = item.get("project", "")
        if project not in project_set:
            project = ""
        tags = [t for t in item.get("tags", []) if t in project_set and t != project]
        confidence = int(item.get("confidence", 100))
        confidence = max(0, min(100, confidence))
        results.append(CategoryResult(id=cid, project=project, tags=tags, confidence=confidence))

    return results


@dataclass
class CategorizeSummary:
    """Summary of a categorization run, including items needing review."""

    categorized: int
    needs_review: list[CategoryResult]


def categorize_entries(
    entries: list[ManifestEntry],
    projects: list[str],
    force: bool = False,
    batch_size: int = 15,
    snippets: dict[str, str] | None = None,
    on_progress: Callable[[int, int], None] | None = None,
    on_status: Callable[[str], None] | None = None,
    review_threshold: int = 80,
) -> CategorizeSummary:
    """Categorize manifest entries using the Claude CLI.

    If some entries are already categorized, generates project descriptions
    from them to provide richer context for the model.

    Updates entries in place. Returns a summary with count and review items.
    """
    to_categorize = [e for e in entries if force or not e.project]

    if not to_categorize:
        return CategorizeSummary(categorized=0, needs_review=[])

    claude_path = _check_claude_cli()
    entry_by_id = {e.id: e for e in entries}

    # If there are already some categorized entries, generate project descriptions
    # from them to give the model better context
    project_descriptions = None
    already_categorized = [e for e in entries if e.project]
    if already_categorized:
        if on_status:
            on_status("Generating project descriptions...")
        project_descriptions = generate_project_descriptions(
            claude_path, projects, already_categorized, snippets
        )

    if on_status:
        on_status("Categorizing...")

    categorized = 0
    low_confidence: list[CategoryResult] = []
    batches = [
        to_categorize[i : i + batch_size]
        for i in range(0, len(to_categorize), batch_size)
    ]

    total_batches = len(batches)

    for batch_idx, batch in enumerate(batches):
        results = categorize_batch(
            claude_path, batch, projects, snippets, project_descriptions
        )
        for result in results:
            entry = entry_by_id.get(result.id)
            if entry:
                entry.project = result.project
                entry.tags = result.tags
                if result.project:
                    categorized += 1
                    if result.confidence < review_threshold:
                        low_confidence.append(result)
        if on_progress:
            on_progress(batch_idx + 1, total_batches)

    # --- Second pass: re-categorize low-confidence items with project descriptions ---
    if low_confidence:
        if on_status:
            on_status("Re-evaluating low-confidence assignments...")

        # Build project descriptions from the high-confidence results
        all_categorized = [e for e in entries if e.project]
        if all_categorized:
            review_descriptions = generate_project_descriptions(
                claude_path, projects, all_categorized, snippets
            )
        else:
            review_descriptions = project_descriptions

        # Gather the entries that need a second look
        review_entries = [entry_by_id[r.id] for r in low_confidence if r.id in entry_by_id]

        # Clear their assignments so the model starts fresh
        for e in review_entries:
            e.project = ""
            e.tags = []
            categorized -= 1  # undo the count from pass 1

        review_batches = [
            review_entries[i : i + batch_size]
            for i in range(0, len(review_entries), batch_size)
        ]

        still_uncertain: list[CategoryResult] = []
        for batch_idx, batch in enumerate(review_batches):
            results = categorize_batch(
                claude_path, batch, projects, snippets, review_descriptions
            )
            for result in results:
                entry = entry_by_id.get(result.id)
                if entry:
                    entry.project = result.project
                    entry.tags = result.tags
                    if result.project:
                        categorized += 1
                        if result.confidence < review_threshold:
                            still_uncertain.append(result)
            if on_progress:
                on_progress(total_batches + batch_idx + 1,
                            total_batches + len(review_batches))

        needs_review = sorted(still_uncertain, key=lambda r: r.confidence)
    else:
        needs_review = []

    return CategorizeSummary(categorized=categorized, needs_review=needs_review)
