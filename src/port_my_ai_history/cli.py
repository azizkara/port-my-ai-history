"""CLI interface: scan and generate subcommands."""

from __future__ import annotations

from pathlib import Path

import click
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn

from .image_resolver import ImageResolver
from .manifest import (
    conversation_to_entry,
    merge_manifest,
    read_manifest,
    read_projects,
    write_manifest,
)
from .parser import load_conversations, parse_conversation
from .renderer import output_filename

console = Console()


def _find_conversations_json(export_dir: Path) -> Path:
    """Locate conversations.json inside the export directory (may be nested)."""
    direct = export_dir / "conversations.json"
    if direct.exists():
        return direct
    # Search one level deep (ChatGPT exports have a hash-named subdirectory)
    for child in export_dir.iterdir():
        if child.is_dir():
            candidate = child / "conversations.json"
            if candidate.exists():
                return candidate
    raise click.ClickException(
        f"conversations.json not found in {export_dir} or its subdirectories"
    )


def _find_export_root(conversations_json: Path) -> Path:
    """Return the directory containing conversations.json (the actual export root)."""
    return conversations_json.parent


@click.group()
@click.version_option(package_name="port-my-ai-history")
def cli():
    """Convert ChatGPT data exports into portable Markdown or PDF documents."""


@cli.command()
@click.option(
    "--export-dir",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    required=True,
    help="Path to the ChatGPT data export directory.",
)
@click.option(
    "--output",
    "-o",
    type=click.Path(path_type=Path),
    default=Path("manifest.yaml"),
    show_default=True,
    help="Output path for the manifest YAML file.",
)
def scan(export_dir: Path, output: Path):
    """Scan a ChatGPT export and generate a manifest.yaml file.

    The manifest lists all conversations with metadata and empty project fields
    for you to fill in before generating output.
    """
    conversations_json = _find_conversations_json(export_dir)
    console.print(f"[bold]Loading[/bold] {conversations_json}")

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        console=console,
    ) as progress:
        raw_convs = load_conversations(conversations_json)
        task = progress.add_task("Parsing conversations...", total=len(raw_convs))

        entries = []
        for raw in raw_convs:
            conv = parse_conversation(raw)
            entry = conversation_to_entry(conv)
            entries.append(entry)
            progress.advance(task)

    # Merge with existing manifest if present
    existing_projects = None
    if output.exists():
        console.print(f"[yellow]Merging with existing manifest:[/yellow] {output}")
        existing_projects = read_projects(output) or None
        entries = merge_manifest(output, entries)

    write_manifest(entries, output, projects=existing_projects)

    included = sum(1 for e in entries if e.include)
    with_project = sum(1 for e in entries if e.project)

    console.print()
    console.print(f"[bold green]Manifest written:[/bold green] {output}")
    console.print(f"  Conversations: {len(entries)}")
    console.print(f"  Included: {included}")
    console.print(f"  With project assigned: {with_project}")
    console.print()
    console.print(
        "[dim]Next, categorize conversations into projects:[/dim]"
    )
    console.print(
        '[dim]  [bold]port-my-ai-history categorize --projects "Project1, Project2, ..."[/bold][/dim]'
    )


@cli.command()
@click.option(
    "--export-dir",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    required=True,
    help="Path to the ChatGPT data export directory.",
)
@click.option(
    "--manifest",
    "-m",
    type=click.Path(exists=True, path_type=Path),
    default=Path("manifest.yaml"),
    show_default=True,
    help="Path to the manifest YAML file.",
)
@click.option(
    "--output-dir",
    "-o",
    type=click.Path(path_type=Path),
    default=Path("output"),
    show_default=True,
    help="Output directory for generated files.",
)
@click.option(
    "--format",
    "output_format",
    type=click.Choice(["markdown", "pdf"]),
    default="markdown",
    show_default=True,
    help="Output format.",
)
@click.option(
    "--include-thoughts",
    is_flag=True,
    default=False,
    help="Include thinking/reasoning blocks in output.",
)
@click.option(
    "--verbose", "-v", is_flag=True, default=False, help="Show detailed progress."
)
def generate(
    export_dir: Path,
    manifest: Path,
    output_dir: Path,
    output_format: str,
    include_thoughts: bool,
    verbose: bool,
):
    """Generate Markdown or PDF files from the manifest.

    Reads the manifest to determine which conversations to include,
    then generates output files organized into project folders.
    """
    conversations_json = _find_conversations_json(export_dir)
    export_root = _find_export_root(conversations_json)

    # Read manifest
    entries = read_manifest(manifest)
    included = [e for e in entries if e.include]
    if not included:
        raise click.ClickException("No conversations marked include: true in manifest")

    console.print(
        f"[bold]Generating {output_format}[/bold] for {len(included)} conversations"
    )

    # Build lookup of included IDs
    included_ids = {e.id for e in included}
    project_by_id = {e.id: e.project for e in included}

    # Load all conversations
    raw_convs = load_conversations(conversations_json)

    # Build image resolver
    console.print("[dim]Indexing image files...[/dim]")
    resolver = ImageResolver(export_root)
    console.print(f"[dim]Indexed {resolver.indexed_count} image files[/dim]")

    # Select renderer
    if output_format == "pdf":
        from .pdf_renderer import render_conversation_pdf

        render_fn = render_conversation_pdf
        ext = ".pdf"
    else:
        from .markdown_renderer import render_conversation_markdown

        render_fn = render_conversation_markdown
        ext = ".md"

    generated = 0
    skipped = 0
    errors = 0

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("Generating...", total=len(included))

        for raw in raw_convs:
            conv_id = raw.get("conversation_id") or raw.get("id", "")
            if conv_id not in included_ids:
                continue

            project = project_by_id.get(conv_id, "")
            folder = project if project else "_unsorted"

            conv = parse_conversation(raw)
            conv_output_dir = output_dir / folder

            try:
                out_path = render_fn(
                    conv,
                    conv_output_dir,
                    resolver=resolver,
                    include_thoughts=include_thoughts,
                )
                generated += 1
                if verbose:
                    progress.console.print(
                        f"  [green]✓[/green] {out_path.relative_to(output_dir)}"
                    )
            except Exception as e:
                errors += 1
                progress.console.print(
                    f"  [red]✗[/red] {conv.title[:50]}: {e}"
                )

            progress.advance(task)

    console.print()
    console.print(f"[bold green]Done![/bold green]")
    console.print(f"  Generated: {generated}")
    if errors:
        console.print(f"  [red]Errors: {errors}[/red]")
    console.print(f"  Output: {output_dir.resolve()}")


@cli.command()
@click.option(
    "--manifest",
    "-m",
    type=click.Path(exists=True, path_type=Path),
    default=Path("manifest.yaml"),
    show_default=True,
    help="Path to the manifest YAML file.",
)
@click.option(
    "--export-dir",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    default=None,
    help="Path to the ChatGPT export directory (for richer content-based categorization).",
)
@click.option(
    "--projects",
    type=str,
    default=None,
    help="Comma-separated list of project names (overrides manifest projects).",
)
@click.option(
    "--force",
    is_flag=True,
    default=False,
    help="Re-categorize conversations that already have a project assigned.",
)
@click.option(
    "--batch-size",
    type=int,
    default=15,
    show_default=True,
    help="Number of conversations per API call.",
)
@click.option(
    "--dry-run",
    is_flag=True,
    default=False,
    help="Show what would be categorized without making API calls.",
)
def categorize(
    manifest: Path,
    export_dir: Path | None,
    projects: str | None,
    force: bool,
    batch_size: int,
    dry_run: bool,
):
    """Categorize conversations into projects using Claude AI.

    Reads the project list from the manifest's `projects:` key, or from the
    --projects flag. Uses Claude to assign each conversation a primary
    project and optional secondary tags.

    Pass --export-dir to include conversation content for more accurate results.
    """
    from .categorizer import CategorizeSummary, categorize_entries, extract_conversation_snippets

    # Resolve project list
    if projects:
        project_list = [p.strip() for p in projects.split(",") if p.strip()]
    else:
        project_list = read_projects(manifest)

    if not project_list:
        raise click.ClickException(
            "No projects defined. Either add a 'projects:' list to your manifest "
            "or pass --projects 'Project1, Project2, ...'"
        )

    entries = read_manifest(manifest)
    to_process = [e for e in entries if force or not e.project]

    console.print(f"[bold]Projects:[/bold] {', '.join(project_list)}")
    console.print(f"[bold]Conversations to categorize:[/bold] {len(to_process)} / {len(entries)}")

    if dry_run:
        console.print()
        console.print("[yellow]Dry run — no API calls will be made.[/yellow]")
        console.print()
        for e in to_process:
            preview = e.preview[:80] + "..." if len(e.preview) > 80 else e.preview
            console.print(f"  [dim]{e.id[:8]}[/dim] {e.title}")
            if preview:
                console.print(f"           [dim]{preview}[/dim]")
        return

    if not to_process:
        console.print("[green]All conversations already categorized.[/green] Use --force to re-categorize.")
        return

    # Load conversation snippets if export dir provided
    snippets = None
    if export_dir:
        conversations_json = _find_conversations_json(export_dir)
        console.print(f"[dim]Loading conversation content from {conversations_json}...[/dim]")
        snippets = extract_conversation_snippets(conversations_json)
        console.print(f"[dim]Loaded content snippets for {len(snippets)} conversations[/dim]")

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        console=console,
    ) as progress:
        task = None

        def on_status(msg: str):
            nonlocal task
            if task is not None:
                progress.remove_task(task)
            task = progress.add_task(msg, total=None)

        def on_progress(done: int, total: int):
            if task is not None:
                progress.update(task, total=total, completed=done)

        summary = categorize_entries(
            entries,
            project_list,
            force=force,
            batch_size=batch_size,
            snippets=snippets,
            on_progress=on_progress,
            on_status=on_status,
        )

    # Write back, preserving the project list
    write_manifest(entries, manifest, projects=project_list)

    tagged = sum(1 for e in entries if e.tags)
    entry_by_id = {e.id: e for e in entries}

    console.print()
    console.print(f"[bold green]Categorization complete![/bold green]")
    console.print(f"  Categorized: {summary.categorized}")
    console.print(f"  With tags: {tagged}")
    console.print(f"  Manifest updated: {manifest}")

    if summary.needs_review:
        console.print()
        console.print(
            f"[yellow bold]Needs review ({len(summary.needs_review)}):[/yellow bold] "
            "These assignments were uncertain even after re-evaluation."
        )
        console.print()
        for item in summary.needs_review:
            entry = entry_by_id.get(item.id)
            title = entry.title if entry else item.id
            console.print(
                f"  [yellow]{item.confidence}%[/yellow] "
                f"[dim]{item.id[:8]}[/dim] {title} "
                f"→ [cyan]{item.project}[/cyan]"
            )

        console.print()
        if not click.confirm("  Review these individually?", default=True):
            console.print("[dim]Keeping suggestions as-is.[/dim]")
            return

        # Build choice list
        choices = {str(i + 1): p for i, p in enumerate(project_list)}
        skip_key = "s"

        changed = 0
        for idx, item in enumerate(summary.needs_review):
            entry = entry_by_id.get(item.id)
            title = entry.title if entry else item.id
            preview = ""
            if entry and entry.preview:
                preview = entry.preview[:100] + ("..." if len(entry.preview) > 100 else "")

            console.print()
            console.print(
                f"  [dim]({idx + 1}/{len(summary.needs_review)})[/dim] "
                f"[bold]{title}[/bold]"
            )
            if preview:
                console.print(f"  [dim]{preview}[/dim]")
            console.print()

            for num, proj in choices.items():
                marker = " [cyan]◀[/cyan]" if proj == item.project else ""
                console.print(f"    [{num}] {proj}{marker}")
            console.print(f"    [{skip_key}] Leave unassigned")
            console.print(f"    [Enter] Accept suggestion ([cyan]{item.project}[/cyan])")

            valid_keys = set(choices.keys()) | {skip_key, ""}
            while True:
                choice = click.prompt("  Choice", default="").strip().lower()
                if choice in valid_keys:
                    break
                console.print(f"  [red]Invalid choice.[/red]")

            if choice == "":
                pass  # keep suggestion
            elif choice == skip_key:
                if entry:
                    entry.project = ""
                    entry.tags = []
                changed += 1
            else:
                picked = choices[choice]
                if entry and picked != item.project:
                    entry.project = picked
                    entry.tags = []
                    changed += 1

        if changed:
            write_manifest(entries, manifest, projects=project_list)
            console.print()
            console.print(f"[green]Updated {changed} conversations. Manifest saved.[/green]")
        else:
            console.print()
            console.print("[green]No changes made.[/green]")
