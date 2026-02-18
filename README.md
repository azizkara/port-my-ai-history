# port-my-ai-history

A local Python CLI tool I built to convert my ChatGPT data export into readable Markdown and PDF files. Sharing it in case it's useful as a starting point for anyone doing the same thing.

**Not actively maintained.** This was built for my own export (277 conversations, ~430 files). Your export will likely have different content types or structures depending on how you use ChatGPT — OpenAI doesn't document the export format and changes it over time. Feel free to fork and adapt.

## Why this exists

Having used ChatGPT for some time, I found the best way to organize my interactions was through projects. Each project — Home Maintenance, for example — would have its own collection of chats and documents that ChatGPT could reference. When starting a new chat about something broken around the house, it would already know my capability as a DIYer and tell me if it was something I could handle.

Now that I'm exploring other platforms, I'd like to take that memory with me in an organized fashion and seed the new platform with this history so it can be equally context-aware — knowing what I've previously done and how I work.

Unfortunately, as of the time of release, OpenAI doesn't export project structure along with your chat history, so there's no easy way to regain that organization. It also needs to be in an easy-to-digest format for the target AI platform, hence the PDF export capability.

This is why port-my-ai-history exists — to help you rebuild that project structure and, in the process, recategorize any chats you might not have put into projects. If the tool missed some, it's easy to do a manual pass and move PDFs into their proper folders. Hope this helps!

## What it does

- Parses ChatGPT's `conversations.json` (which is a tree, not a flat list)
- Resolves `sediment://` image pointers to local files in the export
- Outputs **Markdown** (default) or **PDF** (optional, requires WeasyPrint)
- Generates a YAML manifest you can edit to organize conversations into project folders or exclude ones you don't want
- Optionally uses Claude to **auto-categorize** conversations into projects you define, with confidence scoring and interactive review for uncertain assignments — using your own Claude account
- Runs locally — categorization sends limited data to your own Claude account via the CLI, everything else has zero network calls

## What it handles

These are the content types that appeared in my export. Yours may differ:

| Content type | How it renders |
|---|---|
| `text` | Direct passthrough |
| `code` | Fenced code blocks with language tags |
| `multimodal_text` | Interleaved text + linked images |
| `thoughts` | Blockquotes (off by default, use `--include-thoughts`) |
| `reasoning_recap` | Italic line |
| `execution_output` | Fenced code block |
| `tether_quote` | Blockquote with source |
| `tether_browsing_display` | Italic summary |
| `computer_output` | Placeholder (screenshots from computer-use aren't in the export) |
| `system_error` | Bold error text |
| `user_editable_context` | Skipped |

Unknown content types are rendered as plain text rather than crashing.

## Setup

```bash
git clone <this-repo>
cd port-my-ai-history
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

For PDF output (requires system cairo/pango — `brew install cairo pango` on macOS):

```bash
pip install -e ".[pdf]"
```

For auto-categorization, you'll need [Claude Code](https://docs.anthropic.com/en/docs/claude-code) (the Claude CLI) installed and authenticated with your own Anthropic account. The categorize step makes API calls through the CLI using your account's usage.

## Usage

### 1. Export your ChatGPT data

ChatGPT Settings > Data Controls > Export Data. Extract the zip.

### 2. Scan

```bash
port-my-ai-history scan --export-dir /path/to/export
```

Creates `manifest.yaml` listing all conversations with metadata. You can optionally edit it to:
- Set `project: some-name` to organize conversations into folders
- Set `include: false` to skip conversations

Or just leave it as-is and everything goes into `_unsorted/`.

### 3. Categorize (optional)

If you have the Claude CLI installed and authenticated with your own account, you can auto-categorize conversations into projects. Use `--projects` and include the project names you had in ChatGPT — this lets the tool replicate the same structure you were already using:

```bash
port-my-ai-history categorize \
  --projects "Home Maintenance, Coding, Health and Fitness" \
  --export-dir /path/to/export
```

This sends conversation titles and content snippets to your Claude account, which assigns each conversation to a project (or leaves it unassigned if it doesn't fit). All API calls go through your own authenticated CLI session — nothing is shared with this tool's author or any third party. The tool runs two passes — a second pass re-evaluates any low-confidence assignments using descriptions it builds from the first pass results.

Anything still uncertain after both passes is presented for interactive review in the terminal, where you can accept, reassign, or leave each one unassigned.

You can also:
- Run `--dry-run` to preview what would be categorized without making any API calls
- Run `--force` to re-categorize conversations that already have a project assigned
- Skip this step entirely and assign projects by hand in the manifest

### 4. Generate

```bash
# Markdown
port-my-ai-history generate --export-dir /path/to/export --output-dir ./output

# PDF
port-my-ai-history generate --export-dir /path/to/export --output-dir ./output --format pdf
```

### Output

Markdown gives you a folder per conversation with a `conversation.md` and an `images/` directory:

```
output/_unsorted/
├── fix-login-bug_a1b2c3d4/
│   ├── conversation.md
│   └── images/
│       ├── img-001.png
│       └── img-002.jpg
└── some-other-chat_e5f6g7h8/
    └── conversation.md
```

PDF gives you a single styled file per conversation with embedded images.

## CLI options

```
port-my-ai-history scan --export-dir <path> [--output manifest.yaml]
port-my-ai-history categorize [--projects "A, B, C"] [--export-dir <path>] [options]
port-my-ai-history generate --export-dir <path> [options]
```

**scan**

| Option | Description |
|---|---|
| `--export-dir` | Path to the extracted ChatGPT export |
| `--output`, `-o` | Output manifest path (default: `manifest.yaml`) |

**categorize**

| Option | Description |
|---|---|
| `--projects` | Comma-separated list of project names |
| `--export-dir` | Path to export directory (for content-based categorization) |
| `--manifest`, `-m` | Path to manifest YAML (default: `manifest.yaml`) |
| `--force` | Re-categorize conversations that already have a project |
| `--batch-size` | Conversations per API call (default: 15) |
| `--dry-run` | Preview without making API calls |

**generate**

| Option | Description |
|---|---|
| `--export-dir` | Path to the extracted ChatGPT export |
| `--manifest`, `-m` | Path to manifest YAML (default: `manifest.yaml`) |
| `--output-dir`, `-o` | Output directory (default: `output`) |
| `--format` | `markdown` (default) or `pdf` |
| `--include-thoughts` | Include AI thinking/reasoning blocks |
| `--verbose`, `-v` | Show per-conversation progress |

## Privacy

- **Scan and generate are fully offline.** No data leaves your machine.
- **Categorize sends conversation titles and short text snippets to your own Claude account** via the CLI for classification. No full conversations are sent — just enough context to determine which project a conversation belongs to. All data goes to your account only.
- The categorize step is entirely optional. You can skip it and organize conversations manually in the manifest.
- Use `--dry-run` to preview exactly which conversations would be processed before making any API calls.
- Anthropic's [usage policy](https://www.anthropic.com/policies/usage-policy) applies to data sent through the Claude CLI.

## Known limitations

- **Your export will differ from mine.** ChatGPT features like Canvas, Deep Research, scheduled tasks, voice conversations, and custom GPTs may produce content types or structures this tool doesn't handle.
- **Image resolution is partial.** About half of image references in my export resolved to local files. Computer-use screenshots and some other images aren't included in ChatGPT's export at all.
- **The export format is undocumented and changes.** OpenAI may change the structure of `conversations.json` at any time.
- **Categorization is good, not perfect.** Claude does a solid job but some assignments will be debatable. The tool flags uncertain ones for you to review, and you can always move files around after generating.

## License

MIT — do whatever you want with it.
