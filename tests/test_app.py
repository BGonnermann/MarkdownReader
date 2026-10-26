from pathlib import Path

import pytest
from PySide6.QtCore import QSettings, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QFileDialog, QMessageBox

from markdown_reader import app
from markdown_reader.app import MarkdownWindow, read_markdown


@pytest.fixture
def settings_file(tmp_path):
    return tmp_path / "settings.ini"


@pytest.fixture
def window(qtbot, monkeypatch, settings_file):
    # Keep tests out of the real user settings (the Windows registry).
    monkeypatch.setattr(app, "QSettings", lambda *args: QSettings(str(settings_file), QSettings.Format.IniFormat))
    # A real modal dialog would hang the run, e.g. "Unsaved changes" when pytest-qt
    # closes a window that a test left dirty. Tests that care use answer_dialogs().
    monkeypatch.setattr(QMessageBox, "question", lambda *args, **kwargs: QMessageBox.StandardButton.Discard)
    monkeypatch.setattr(QMessageBox, "warning", lambda *args, **kwargs: QMessageBox.StandardButton.Cancel)
    monkeypatch.setattr(QMessageBox, "critical", lambda *args, **kwargs: QMessageBox.StandardButton.Ok)
    widget = MarkdownWindow()
    qtbot.addWidget(widget)
    return widget


@pytest.fixture
def opened(monkeypatch):
    urls: list[QUrl] = []
    monkeypatch.setattr(QDesktopServices, "openUrl", lambda url: urls.append(url) or True)
    return urls


def answer_dialogs(monkeypatch, button):
    asked: list[str] = []

    def reply(*args, **kwargs):
        asked.append(args[2])
        return button

    monkeypatch.setattr(QMessageBox, "question", reply)
    monkeypatch.setattr(QMessageBox, "warning", reply)
    return asked


def test_open_renders_markdown(window, tmp_path):
    source = tmp_path / "hello.md"
    source.write_text("# Hello\n\nThis is **bold**.", encoding="utf-8")

    assert window.open_path(source)

    assert window.current_path == source.resolve()
    assert window.editor.toPlainText().startswith("# Hello")
    assert "Hello" in window.preview.toPlainText()
    assert "bold" in window.preview.toPlainText()
    assert not window.dirty


def test_window_has_application_icon(window):
    assert not window.windowIcon().isNull()


def test_markdown_drop_events_reach_the_window(window):
    assert window.acceptDrops()
    assert not window.editor.acceptDrops()
    assert not window.editor.viewport().acceptDrops()
    assert not window.preview.acceptDrops()
    assert not window.preview.viewport().acceptDrops()


def test_edit_marks_dirty_and_save_writes_utf8(window, tmp_path):
    source = tmp_path / "notes.md"
    source.write_text("Original", encoding="utf-8")
    window.open_path(source)

    window.editor.setPlainText("Changed — café")
    assert window.dirty
    assert window.save()

    assert source.read_text(encoding="utf-8") == "Changed — café"
    assert not window.dirty


def test_save_as_adds_markdown_extension(window, tmp_path, monkeypatch):
    destination = tmp_path / "new-document"
    monkeypatch.setattr(
        QFileDialog,
        "getSaveFileName",
        lambda *args, **kwargs: (str(destination), "Markdown files (*.md)"),
    )
    window.new_document()
    window.editor.setPlainText("# New")

    saved_path = destination.with_suffix(".md")
    assert window.save_as()
    assert saved_path.read_text(encoding="utf-8") == "# New"
    assert window.settings.value("lastDirectory") == str(saved_path.parent)


def test_view_modes_and_zoom(window):
    window.set_view("preview")
    assert not window.editor.isVisible()
    assert window.preview_action.isChecked()
    window.set_view("editor")
    assert not window.preview.isVisible()
    assert window.edit_action.isChecked()
    window.set_view("split")
    assert window.split_action.isChecked()
    window.set_view("invalid")
    assert window.split_action.isChecked()

    window.zoom_in()
    assert window._zoom == 1
    window.zoom_reset()
    assert window._zoom == 0
    for _ in range(100):
        window.zoom_out()
    assert window._zoom == app.MIN_ZOOM


def test_pdf_export_creates_nonempty_file(window, tmp_path, monkeypatch):
    source = tmp_path / "report.md"
    output = tmp_path / "report.pdf"
    source.write_text("# Report\n\nPDF body.", encoding="utf-8")
    window.open_path(source)
    monkeypatch.setattr(
        QFileDialog,
        "getSaveFileName",
        lambda *args, **kwargs: (str(output), "PDF files (*.pdf)"),
    )

    window.export_pdf()

    assert output.exists()
    assert output.stat().st_size > 100
    assert output.read_bytes().startswith(b"%PDF")


def test_markdown_link_opens_in_the_app(window, tmp_path, opened):
    source = tmp_path / "index.md"
    source.write_text("[Details](chapter.md#details)", encoding="utf-8")
    target = tmp_path / "chapter.md"
    target.write_text("# Details", encoding="utf-8")
    window.open_path(source)

    window._open_link(QUrl("chapter.md#details"))

    assert opened == []
    assert window.current_path == target.resolve()


def test_open_link_keeps_document_anchor_in_preview(window, tmp_path, opened):
    source = tmp_path / "index.md"
    source.write_text("# Details\n\n[Jump to details](#details)", encoding="utf-8")
    window.open_path(source)

    window._open_link(QUrl("#details"))

    assert opened == []


def test_anchor_link_works_in_unsaved_document(window, opened):
    window.new_document()
    window.editor.setPlainText("# Top\n\n[Back to top](#top)")

    window._open_link(QUrl("#top"))

    assert opened == []


def test_link_to_local_program_asks_before_running(window, tmp_path, opened, monkeypatch):
    source = tmp_path / "index.md"
    source.write_text("[Click me](payload.exe)", encoding="utf-8")
    (tmp_path / "payload.exe").write_bytes(b"MZ")
    window.open_path(source)
    asked = answer_dialogs(monkeypatch, QMessageBox.StandardButton.Cancel)

    window._open_link(QUrl("payload.exe"))
    window._open_link(QUrl("ms-settings:privacy"))

    assert opened == []
    assert len(asked) == 2

    answer_dialogs(monkeypatch, QMessageBox.StandardButton.Open)
    window._open_link(QUrl("payload.exe"))
    assert Path(opened[0].toLocalFile()) == (tmp_path / "payload.exe").resolve()
    assert "?" not in opened[0].toString()


def test_web_links_open_without_prompt(window, opened, monkeypatch):
    asked = answer_dialogs(monkeypatch, QMessageBox.StandardButton.Cancel)

    window._open_link(QUrl("https://example.com/page"))

    assert [url.toString() for url in opened] == ["https://example.com/page"]
    assert asked == []


def test_save_keeps_original_line_endings(window, tmp_path):
    unix = tmp_path / "unix.md"
    unix.write_bytes(b"one\ntwo\n")
    windows = tmp_path / "windows.md"
    windows.write_bytes(b"one\r\ntwo\r\n")

    for path in (unix, windows):
        window.open_path(path)
        window.editor.setPlainText(window.editor.toPlainText() + "three\n")
        assert window.save()

    assert unix.read_bytes() == b"one\ntwo\nthree\n"
    assert windows.read_bytes() == b"one\r\ntwo\r\nthree\r\n"


def test_legacy_encoding_survives_a_save(window, tmp_path):
    source = tmp_path / "legacy.md"
    source.write_bytes("Café naïve".encode("cp1252"))

    window.open_path(source)
    assert window.editor.toPlainText() == "Café naïve"
    window.editor.setPlainText("Café naïve!")
    assert window.save()

    assert source.read_bytes() == "Café naïve!".encode("cp1252")


def test_legacy_file_switches_to_utf8_when_needed(window, tmp_path):
    source = tmp_path / "legacy.md"
    source.write_bytes("Café".encode("cp1252"))
    window.open_path(source)

    window.editor.setPlainText("Café → 日本")
    assert window.save()

    assert source.read_text(encoding="utf-8") == "Café → 日本"
    assert window.encoding == "utf-8"


def test_utf8_bom_is_preserved(window, tmp_path):
    source = tmp_path / "bom.md"
    source.write_bytes(b"\xef\xbb\xbf# Title\n")

    assert read_markdown(source) == ("# Title\n", "utf-8-sig", "\n")
    window.open_path(source)
    window.editor.setPlainText("# New title\n")
    window.save()

    assert source.read_bytes() == b"\xef\xbb\xbf# New title\n"


def test_preview_keeps_scroll_position_while_typing(window, qtbot, tmp_path):
    source = tmp_path / "long.md"
    source.write_text("\n\n".join(f"Paragraph {i}" for i in range(400)), encoding="utf-8")
    window.show()
    window.open_path(source)
    bar = window.preview.verticalScrollBar()
    bar.setValue(bar.maximum() // 2)
    position = bar.value()

    window.editor.insertPlainText("x")
    qtbot.waitUntil(lambda: not window._render_timer.isActive())

    assert position > 0
    assert bar.value() == position


def test_find_searches_preview_when_editor_hidden(window, tmp_path):
    source = tmp_path / "find.md"
    source.write_text("alpha\n\nneedle here", encoding="utf-8")
    window.open_path(source)
    window.set_view("preview")

    window.find_input.setText("needle")
    window.find_next()

    assert window.preview.textCursor().selectedText() == "needle"


def test_external_change_reloads_clean_document(window, tmp_path):
    source = tmp_path / "watched.md"
    source.write_text("before", encoding="utf-8")
    window.open_path(source)
    assert str(source.resolve()) in window.watcher.files()

    source.write_text("after", encoding="utf-8")
    window._on_file_changed(str(source.resolve()))

    assert window.editor.toPlainText() == "after"
    assert not window.dirty


def test_external_change_asks_before_discarding_edits(window, tmp_path, monkeypatch):
    source = tmp_path / "watched.md"
    source.write_text("before", encoding="utf-8")
    window.open_path(source)
    window.editor.setPlainText("my edits")
    asked = answer_dialogs(monkeypatch, QMessageBox.StandardButton.No)

    source.write_text("after", encoding="utf-8")
    window._on_file_changed(str(source.resolve()))

    assert len(asked) == 1
    assert window.editor.toPlainText() == "my edits"
    assert window.dirty


def test_own_save_does_not_trigger_reload_prompt(window, tmp_path, monkeypatch):
    source = tmp_path / "watched.md"
    source.write_text("before", encoding="utf-8")
    window.open_path(source)
    window.editor.setPlainText("saved text")
    window.save()
    asked = answer_dialogs(monkeypatch, QMessageBox.StandardButton.No)

    window._on_file_changed(str(source.resolve()))

    assert asked == []


def test_view_mode_and_zoom_are_remembered(qtbot, window):
    window.set_view("preview")
    window.zoom_in()
    window.zoom_in()
    window.close()

    reopened = MarkdownWindow()
    qtbot.addWidget(reopened)

    assert reopened.view_mode == "preview"
    assert reopened.preview_action.isChecked()
    assert reopened._zoom == 2


def test_status_bar_shows_position_and_format(window, tmp_path):
    source = tmp_path / "status.md"
    source.write_bytes(b"one two\r\nthree\r\n")

    window.open_path(source)

    assert "3 words" in window.position_label.text()
    assert "CRLF" in window.position_label.text()
    assert "Ln 1, Col 1" in window.position_label.text()


def test_preview_blocks_unc_and_remote_references(window, tmp_path):
    source = tmp_path / "tracker.md"
    source.write_text("![pixel](//attacker/share/pixel.png)\n", encoding="utf-8")

    window.open_path(source)
    window.show()
    window.preview.repaint()

    assert window.preview.blocked_resources > 0


@pytest.mark.parametrize(
    ("url", "allowed"),
    [
        (QUrl.fromLocalFile("C:/docs/image.png"), True),
        (QUrl("image.png"), True),
        (QUrl("data:image/png;base64,AAAA"), True),
        (QUrl(), True),
        (QUrl("//attacker/share/pixel.png"), False),
        (QUrl("file://attacker/share/pixel.png"), False),
        (QUrl("http://example.com/pixel.png"), False),
        (QUrl("https://example.com/pixel.png"), False),
        (QUrl("ftp://example.com/pixel.png"), False),
    ],
)
def test_preview_resource_policy(url, allowed):
    assert app.PreviewBrowser._is_allowed(url) is allowed


def test_heading_anchors_let_in_document_links_jump(window, tmp_path):
    source = tmp_path / "toc.md"
    source.write_text(
        "# Title\n\n[Go](#deep-section)\n\n" + "filler\n\n" * 80 + "## Deep Section\n\nend\n",
        encoding="utf-8",
    )

    window.open_path(source)
    window.show()
    window.preview.resize(500, 300)
    window._open_link(QUrl("#deep-section"))

    assert window.preview.verticalScrollBar().value() > 0


def test_repeated_headings_get_distinct_anchors(window):
    window.editor.setPlainText("# Notes\n\ntext\n\n# Notes\n")
    window._render_editor()

    names = []
    block = window.preview.document().begin()
    while block.isValid():
        if block.blockFormat().headingLevel():
            names.extend(block.begin().fragment().charFormat().anchorNames())
        block = block.next()

    assert names == ["notes", "notes-1"]


def test_failed_save_keeps_the_original_file(window, tmp_path, monkeypatch):
    source = tmp_path / "keep.md"
    source.write_text("original\n", encoding="utf-8")
    window.open_path(source)
    window.editor.setPlainText("replacement")
    monkeypatch.setattr(app.os, "replace", lambda *args: (_ for _ in ()).throw(OSError("disk full")))

    assert window.save() is False

    assert source.read_text(encoding="utf-8") == "original\n"
    assert list(tmp_path.glob(".*.saving")) == []


def test_classic_mac_line_endings_are_preserved(window, tmp_path):
    source = tmp_path / "mac.md"
    source.write_bytes(b"one\rtwo\r")

    window.open_path(source)
    assert window.newline == "\r"
    assert "CR" in window.position_label.text()

    window.editor.setPlainText("one\ntwo\nthree")
    assert window.save()
    assert source.read_bytes() == b"one\rtwo\rthree"


def test_split_divider_survives_a_view_switch(qtbot, window):
    window.show()
    window.splitter.setSizes([300, 800])
    window._remember_split()
    dragged = window.splitter.sizes()

    window.set_view("preview")
    window.set_view("split")
    assert window.splitter.sizes() == dragged

    window.close()
    reopened = MarkdownWindow()
    qtbot.addWidget(reopened)
    assert reopened._split_sizes == dragged


def test_raw_html_does_not_blank_the_preview(window, tmp_path):
    # A void tag such as the <img> in a centred README header used to swallow
    # every following block, leaving the preview empty.
    source = tmp_path / "with-html.md"
    source.write_text(
        '<p align="center">\n  <img src="logo.png" width="80">\n</p>\n\n'
        "# Real heading\n\nProse that must still be readable.\n",
        encoding="utf-8",
    )

    window.open_path(source)

    rendered = window.preview.toPlainText()
    assert "Real heading" in rendered
    assert "Prose that must still be readable." in rendered


def test_markdown_still_renders_around_raw_html(window):
    window.editor.setPlainText("Text with <br> a void tag and **bold** after it.")
    window._render_editor()

    rendered = window.preview.toPlainText()
    assert "bold" in rendered
    assert "a void tag" in rendered
