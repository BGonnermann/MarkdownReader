<p align="center">
  <img src="docs/markdown-reader-logo.png" width="190" alt="Markdown Reader logo">
</p>

<h1 align="center">Markdown Reader</h1>

<p align="center">
  A simple, lightweight desktop application for reading and editing Markdown files on Windows.
</p>

<p align="center">
  <a href="https://github.com/BGonnermann/MarkdownReader/actions/workflows/tests.yml"><img src="https://github.com/BGonnermann/MarkdownReader/actions/workflows/tests.yml/badge.svg" alt="Tests"></a>
  <img src="https://img.shields.io/badge/Python-3.11%2B-3776AB?logo=python&logoColor=white" alt="Python 3.11+">
  <img src="https://img.shields.io/badge/License-MIT-8B5CF6" alt="MIT License">
</p>

Markdown Reader gives you a live rendered preview beside the Markdown source, accepts files by drag-and-drop, and can export the finished document directly to PDF. It is built with Python and PySide6 and does not require a web browser or server.

## Features

- Drag-and-drop `.md`, `.markdown`, `.mdown`, and `.mkd` files
- Live GitHub-style Markdown preview while editing
- Split view, preview-only view, and editor-only view
- New, Open, Close, Save, and Save As commands
- Export the rendered document as a PDF
- Zoom in, zoom out, and reset zoom
- Find text and move between matches (works in preview-only view too)
- Undo, redo, cut, copy, paste, and select all
- Recent-files menu
- Unsaved-change protection
- Local images and links resolved relative to the Markdown file; links to other Markdown files open in the app
- Asks before a link launches a local program or a non-web protocol, so an untrusted document can't run an `.exe` with one click
- Never fetches anything off the machine: an image pointing at a network share or a remote URL is refused, so a document can't use a tracking pixel to leak your Windows credentials
- In-document links to headings (`[Section](#section)`) jump to them
- Automatically reloads a file when another program changes it (asks first if you have unsaved edits)
- Keeps each file's original encoding (UTF-8, UTF-8 with BOM, Windows-1252) and line endings (LF, CRLF, CR) when saving
- Saves through a temporary file, so a failed save can't leave the original truncated
- Status bar with line, column, word count, encoding, and line endings
- Remembers your view mode, zoom level, and the split divider position
- Familiar Windows keyboard shortcuts

## Download for Windows

For the easiest setup, open the [latest GitHub Release](https://github.com/BGonnermann/MarkdownReader/releases/latest), download `MarkdownReader-v0.1.4-windows-x64.zip`, extract the entire folder, and run **`Markdown Reader.exe`**.

The portable release does not require Python, `uv`, or an installer.

## Requirements for running from source

- Windows 10 or Windows 11
- Python 3.11 or newer
- [`uv`](https://docs.astral.sh/uv/getting-started/installation/)

## Run from source

1. Download or clone this repository:

   ```bash
   git clone https://github.com/BGonnermann/MarkdownReader.git
   cd MarkdownReader
   ```

2. Double-click **`run_markdown_reader.bat`**.

On the first run, the launcher creates an isolated virtual environment and installs the required packages. Later launches reuse that environment.

You can also start it from a terminal:

```bash
uv sync --extra dev
uv run markdown-reader
```

To open a file immediately:

```bash
uv run markdown-reader path/to/document.md
```

A sample document is included as `sample.md`.

## Keyboard shortcuts

| Shortcut | Action |
|---|---|
| `Ctrl+N` | New document |
| `Ctrl+O` | Open file |
| `Ctrl+S` | Save |
| `Ctrl+Shift+S` | Save As |
| `Ctrl+W` | Close file |
| `Ctrl+P` | Export as PDF |
| `Ctrl+F` | Find |
| `F3` / `Shift+F3` | Find next/previous |
| `Esc` | Close the find bar |
| `Ctrl++` / `Ctrl+-` / `Ctrl+Wheel` | Zoom in/out |
| `Ctrl+0` | Reset zoom |
| `Ctrl+1` | Split view |
| `Ctrl+2` | Preview only |
| `Ctrl+3` | Editor only |

## Build a standalone Windows application

Double-click **`build_exe.bat`**, or run:

```bash
uv sync --extra dev
uv run pyinstaller --noconfirm --clean --windowed --name "Markdown Reader" --paths src --icon src/markdown_reader/assets/icon.ico --add-data "src/markdown_reader/assets/icon.png;markdown_reader/assets" src/markdown_reader/app.py
```

The portable application will be created at:

```text
dist/Markdown Reader/Markdown Reader.exe
```

Copy the entire `dist/Markdown Reader` directory when moving the application to another Windows computer.

## Cutting a release

Releases are built by GitHub Actions, not by hand. Bump the version in both
`pyproject.toml` and `src/markdown_reader/__init__.py`, run `uv lock`, merge that
to `main`, then push a matching tag:

```bash
git tag v0.1.5
git push origin v0.1.5
```

The workflow refuses to build if the tag and the two version strings disagree. It
lints, runs the tests, builds the portable package on a clean runner, checks that
the archive extracts complete, attests the result, and leaves a draft release for
you to write notes on and publish.

Because zip archives embed timestamps, the same sources do not produce the same
checksum twice, so the archive is not bit-for-bit reproducible. What is verifiable
is its provenance - the signed attestation ties the published file to the commit
and workflow that produced it:

```bash
gh attestation verify MarkdownReader-v0.1.5-windows-x64.zip --repo BGonnermann/MarkdownReader
```

## Development and tests

Install the development dependencies and run the test suite:

```bash
uv sync --extra dev
uv run ruff check .
uv run pytest
```

The tests cover drag-and-drop routing, Markdown loading and rendering, encoding and line-ending preservation, atomic saves, Save As, link safety, the preview's refusal to fetch off-machine resources, heading anchors, reloading on external changes, find, view and zoom controls, and real PDF generation.

## Technology

- Python 3.11+
- PySide6 / Qt 6
- pytest and pytest-qt
- PyInstaller for optional Windows packaging

## License

Markdown Reader is available under the [MIT License](LICENSE).
