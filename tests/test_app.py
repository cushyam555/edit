import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch, Mock
from PySide6.QtCore import QStandardPaths, QMimeData, Qt, QPoint, QLocale, QTimer
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QInputDialog,
    QMessageBox,
    QLineEdit,
    QSpinBox,
    QMenu,
)
from PySide6.QtTest import QTest
from soundfont_edit.app import Window
from soundfont_edit.preset_tree import PresetTree, MIME
from soundfont_edit.soundfont import SoundFont, export_sf2
from test_soundfont import fixture


class AppTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        QStandardPaths.setTestModeEnabled(True)
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setApplicationName("SoundFontEditStudioTests02")

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.folder = Path(self.temp.name).resolve()
        self.window = Window()
        self.window.meta = {"favorites": [], "tags": {}}
        self.window.settings = self.folder / "library.json"
        self.window.cache = self.folder / "cache.db"
        self.errors = []
        self.window.error = self.errors.append
        self.window.show()
        self.app.processEvents()

    def tearDown(self):
        self.wait()
        self.window.dirty = False
        self.window.close()
        self.app.processEvents()
        self.temp.cleanup()

    def wait(self):
        deadline = time.monotonic() + 10
        while (
            self.window.pending or self.window.busy()
        ) and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(0.01)
        self.app.processEvents()
        self.assertFalse(self.window.pending)
        self.assertFalse(self.window.busy())

    def add_fixture(self, name="Piano", bank=0, program=0):
        path = self.folder / (name + ".sf2")
        fixture(path, name, bank=bank, program=program)
        self.window.scan([str(path), str(path)])
        self.wait()
        return path

    def choose_source(self, path):
        w = self.window
        w.source_files.setCurrentIndex(w.source_files.findData(str(path)))
        w.source_tree.clearSelection()
        w.source_tree.rows[0].setSelected(True)
        self.app.processEvents()

    def begin_inline(self, column):
        tree = self.window.destination_tree
        tree.setFocus()
        tree.setCurrentItem(tree.rows[0], column)
        tree.editItem(tree.rows[0], column)
        self.app.processEvents()
        kind = QLineEdit if column == 1 else QSpinBox
        editor = next(
            editor for editor in tree.findChildren(kind) if editor.isVisible()
        )
        self.assertGreaterEqual(editor.width(), editor.sizeHint().width())
        return editor

    def test_inline_name_paste_escape_and_immediate_save(self):
        w = self.window
        path = self.add_fixture()
        self.choose_source(path)
        w.copy_selected()
        tree = w.destination_tree
        item = tree.rows[0]
        # Exercise the real double-click path, not just the document mutation.
        point = QPoint(
            tree.header().sectionViewportPosition(1) + 30,
            tree.visualItemRect(item).center().y(),
        )
        QTest.mouseClick(tree.viewport(), Qt.LeftButton, pos=point)
        QTest.mouseDClick(tree.viewport(), Qt.LeftButton, pos=point)
        self.app.processEvents()
        editor = next(e for e in tree.findChildren(QLineEdit) if e.isVisible())
        QApplication.clipboard().setText("Pasted GM name")
        editor.selectAll()
        QTest.keyClick(editor, Qt.Key_V, Qt.ControlModifier)
        QTest.keyClick(editor, Qt.Key_Return)
        # Save before servicing refresh timers: document edits must be synchronous.
        project = self.folder / "inline.sfedit"
        with patch.object(
            QFileDialog, "getSaveFileName", return_value=(str(project), "")
        ):
            w.save_project()
        self.assertEqual(
            json.loads(project.read_text("utf-8"))["entries"][0]["name"],
            "Pasted GM name",
        )
        self.app.processEvents()
        editor = self.begin_inline(1)
        editor.selectAll()
        QTest.keyClicks(editor, "Cancelled")
        QTest.keyClick(editor, Qt.Key_Escape)
        self.app.processEvents()
        self.assertEqual(w.entries[0]["name"], "Pasted GM name")
        self.assertFalse(w.dirty)
        self.assertEqual(self.errors, [])
        editor = self.begin_inline(1)
        editor.selectAll()
        QTest.keyClicks(editor, "Saved while focused")
        with patch.object(
            QFileDialog, "getSaveFileName", return_value=(str(project), "")
        ):
            w.save_project()
        self.assertEqual(
            json.loads(project.read_text("utf-8"))["entries"][0]["name"],
            "Saved while focused",
        )
        self.app.processEvents()

    def test_inline_bank_id_numbering_and_original_preview(self):
        w = self.window
        path = self.add_fixture()
        self.choose_source(path)
        w.copy_selected()
        editor = self.begin_inline(2)
        editor.setValue(3)
        QTest.keyClick(editor, Qt.Key_Return)
        self.app.processEvents()
        self.assertEqual(w.entries[0]["bank"], 3)
        w.numbering.setChecked(True)
        editor = self.begin_inline(0)
        self.assertEqual((editor.minimum(), editor.maximum()), (1, 128))
        editor.setValue(34)
        QTest.keyClick(editor, Qt.Key_Return)
        self.app.processEvents()
        self.assertEqual(w.entries[0]["program"], 33)
        self.assertEqual(w.destination_tree.rows[0].text(0), "034")
        self.assertEqual(w.destination_tree.rows[0].text(3), "Electric Bass (finger)")
        self.assertEqual(
            (w.entries[0]["source_bank"], w.entries[0]["source_program"]), (0, 0)
        )
        w.player.select = Mock()
        w.player.on = Mock()
        w.note_on(60)
        w.player.select.assert_called_with(str(path), 0, 0, drums=False)
        self.assertEqual(self.errors, [])

    def test_gm_copy_keyboard_and_apply_names(self):
        w = self.window
        path = self.add_fixture()
        self.choose_source(path)
        w.copy_selected()
        tree = w.destination_tree
        tree.setCurrentItem(tree.rows[0], 3)
        QTest.keyClick(tree, Qt.Key_C, Qt.ControlModifier)
        self.assertEqual(QApplication.clipboard().text(), "Acoustic Grand Piano")
        w.use_gm_names()
        self.assertEqual(w.entries[0]["name"], "Acoustic Grand Piano")
        self.assertEqual(tree.rows[0].text(3), "Acoustic Grand Piano")
        self.assertIsNone(
            tree.itemDelegate().createEditor(
                tree.viewport(), None, tree.indexFromItem(tree.rows[0], 3)
            )
        )
        source = w.source_tree
        source.setCurrentItem(source.rows[0], 2)
        QApplication.clipboard().setText("stale")
        QTest.keyClick(source, Qt.Key_C, Qt.ControlModifier)
        self.assertEqual(QApplication.clipboard().text(), "Acoustic Grand Piano")
        self.assertEqual(self.errors, [])

    def test_inline_conflict_cancel_replace_and_empty_name(self):
        w = self.window
        a = self.add_fixture("A")
        b = self.add_fixture("B", program=1)
        self.choose_source(a)
        w.copy_selected()
        self.choose_source(b)
        w.copy_selected()
        key = w.entries[0]["_uid"]
        before = [dict(e) for e in w.entries]
        with patch.object(w, "resolve_collision", return_value=("cancel", None)):
            w.edit_destination_cell(key, 0, 1)
        self.assertEqual(w.entries, before)
        w.edit_destination_cell(key, 1, "  ")
        self.assertEqual(w.entries, before)
        self.assertTrue(self.errors)
        self.errors.clear()
        with patch.object(w, "resolve_collision", return_value=("replace", None)):
            w.edit_destination_cell(key, 0, 1)
        self.app.processEvents()
        self.assertEqual(len(w.entries), 1)
        self.assertEqual(w.entries[0]["path"], str(a))
        self.assertEqual(w.entries[0]["program"], 1)
        self.assertEqual(w.entries[0]["source_program"], 0)
        self.assertEqual(self.errors, [])

    def test_context_delete_multiselect_and_clicked_row(self):
        w = self.window
        a = self.add_fixture("A")
        b = self.add_fixture("B", program=1)
        self.choose_source(a)
        w.copy_selected()
        self.choose_source(b)
        w.copy_selected()
        tree = w.destination_tree

        def delete():
            menu = next(
                menu
                for menu in self.app.topLevelWidgets()
                if isinstance(menu, QMenu) and menu.isVisible()
            )
            action = next(
                action
                for action in menu.actions()
                if action.text() == "ลบเสียงที่เลือก"
            )
            self.assertTrue(action.isEnabled())
            action.trigger()
            menu.close()

        # Right-clicking a different row deletes the clicked preset, not a stale selection.
        tree.setCurrentItem(tree.rows[0])
        point = tree.visualItemRect(tree.rows[1]).center()
        QTimer.singleShot(0, delete)
        w.destination_context(point)
        self.assertEqual([e["name"] for e in w.entries], ["A"])
        self.choose_source(b)
        w.copy_selected()
        tree.selectAll()
        point = tree.visualItemRect(tree.rows[0]).center()
        QTimer.singleShot(0, delete)
        w.destination_context(point)
        self.assertEqual(w.entries, [])
        self.assertTrue(w.dirty)
        self.assertEqual(self.errors, [])

    def test_ascii_digits_despite_non_latin_system_locale(self):
        previous = QLocale()
        try:
            QLocale.setDefault(QLocale("ar_EG"))
            other = Window()
            other.meta = {"favorites": [], "tags": {}}
            self.assertEqual(other.locale().zeroDigit(), "0")
            self.assertEqual(
                [spin.text() for spin in other.findChildren(QSpinBox)], ["100"]
            )
            other.close()
            path = self.add_fixture()
            self.choose_source(path)
            self.window.copy_selected()
            editor = self.begin_inline(0)
            editor.setValue(127)
            self.assertEqual(editor.text(), "127")
            QTest.keyClick(editor, Qt.Key_Escape)
        finally:
            QLocale.setDefault(previous)

    def test_copy_edit_and_project_roundtrip(self):
        w = self.window
        path = self.add_fixture()
        self.choose_source(path)
        w.copy_selected()
        self.assertEqual(len(w.entries), 1)
        w.destination_tree.rows[0].setSelected(True)
        with patch.object(QInputDialog, "getText", return_value=("My Piano", True)):
            w.rename()
        with patch.object(w, "ask_slot", return_value=(3, 12)):
            w.change_slot()
        self.assertEqual(
            (w.entries[0]["name"], w.entries[0]["bank"], w.entries[0]["program"]),
            ("My Piano", 3, 12),
        )
        w.player.select = Mock()
        w.player.on = Mock()
        w.note_on(60)
        w.player.select.assert_called_with(str(path), 0, 0, drums=False)
        project = self.folder / "set.sfedit"
        with patch.object(
            QFileDialog, "getSaveFileName", return_value=(str(project), "")
        ):
            w.save_project()
        self.assertFalse(w.dirty)
        payload = json.loads(project.read_text("utf-8"))
        self.assertEqual(payload["version"], 2)
        self.assertNotIn("_uid", payload["entries"][0])
        w.new_destination()
        self.assertEqual(w.entries, [])
        with patch.object(
            QFileDialog, "getOpenFileName", return_value=(str(project), "")
        ):
            w.open_project()
        self.wait()
        self.assertEqual(w.entries[0]["name"], "My Piano")
        self.assertEqual(w.entries[0]["path"], str(path))
        w.language()
        self.assertEqual(w.export_button.text(), "Save as new SF2")
        self.assertEqual(self.errors, [])

    def test_open_existing_destination_replace_and_export(self):
        w = self.window
        original = self.folder / "existing.sf2"
        fixture(original, "Old Piano")
        before = original.read_bytes()
        w.load_destination(str(original))
        self.wait()
        self.assertEqual(w.entries[0]["name"], "Old Piano")
        source = self.add_fixture("New Piano")
        self.choose_source(source)
        with patch.object(w, "resolve_collision", return_value=("replace", None)):
            w.copy_selected()
        self.assertEqual(len(w.entries), 1)
        self.assertEqual(w.entries[0]["path"], str(source))
        out = self.folder / "result.sf2"
        with (
            patch.object(QFileDialog, "getSaveFileName", return_value=(str(out), "")),
            patch.object(QMessageBox, "question", return_value=QMessageBox.Yes),
        ):
            w.export()
        self.wait()
        self.assertEqual(SoundFont(out).presets[0].name, "New Piano")
        self.assertEqual(original.read_bytes(), before)
        self.assertFalse(w.dirty)
        with patch.object(
            QFileDialog, "getSaveFileName", return_value=(str(original), "")
        ):
            w.export()
        self.assertTrue(self.errors)
        self.assertEqual(original.read_bytes(), before)

    def test_source_file_isolation_and_multiselect_copy(self):
        w = self.window
        a = self.add_fixture("A")
        b = self.add_fixture("B", program=10)
        self.choose_source(a)
        self.assertEqual(len(w.source_tree.rows), 1)
        self.assertEqual(w.source_tree.selected_entries()[0]["name"], "A")
        w.copy_selected()
        self.choose_source(b)
        w.copy_selected()
        self.assertEqual([e["program"] for e in w.entries], [0, 10])
        w.destination_tree.selectAll()
        w.remove()
        self.assertEqual(w.entries, [])
        self.assertEqual(self.errors, [])

    def test_multiselect_copy_and_cancel_leave_destination_unchanged(self):
        w = self.window
        a = self.folder / "a.sf2"
        b = self.folder / "b.sf2"
        combined = self.folder / "combined.sf2"
        fixture(a, "A", program=2)
        fixture(b, "B", program=10)
        export_sf2(
            [
                dict(path=str(a), index=0, name="A", bank=0, program=2),
                dict(path=str(b), index=0, name="B", bank=0, program=10),
            ],
            combined,
        )
        w.scan([str(combined)])
        self.wait()
        w.source_tree.selectAll()
        w.copy_selected()
        self.assertEqual([e["program"] for e in w.entries], [2, 10])
        before = [dict(e) for e in w.entries]
        with patch.object(w, "resolve_collision", return_value=("cancel", None)):
            w.copy_selected()
        self.assertEqual(w.entries, before)
        self.assertEqual(self.errors, [])

    def test_legacy_project_and_drop_share_collision_path(self):
        w = self.window
        source = self.add_fixture()
        project = self.folder / "old.sfedit"
        project.write_text(
            json.dumps(
                {
                    "version": 1,
                    "entries": [
                        dict(
                            path=source.name, index=0, name="Legacy", bank=2, program=33
                        )
                    ],
                }
            ),
            "utf-8",
        )
        with patch.object(
            QFileDialog, "getOpenFileName", return_value=(str(project), "")
        ):
            w.open_project()
        self.wait()
        self.assertEqual(w.entries[0]["name"], "Legacy")
        self.assertEqual(w.entries[0]["source_bank"], 0)
        w.drop_source([[str(source), 0]])
        self.assertEqual([e["program"] for e in w.entries], [0, 33])
        self.assertEqual(self.errors, [])

    def test_tree_numeric_sort_gm_toggle_and_drag_identity(self):
        tree = PresetTree("window-one")
        rows = [
            dict(path="a.sf2", index=i, name="Custom", bank=b, program=p)
            for i, (b, p) in enumerate([(0, 10), (128, 0), (0, 2), (2, 0)])
        ]
        tree.populate(rows)
        self.assertEqual(
            [item.text(0) for item in tree.rows], ["002", "010", "000", "000"]
        )
        tree.populate(rows, "id:2")
        self.assertEqual(len(tree.rows), 1)
        tree.populate(rows, "", True)
        self.assertEqual(tree.rows[0].text(0), "003")
        self.assertEqual(rows[2]["program"], 2)
        data = QMimeData()
        data.setData(
            MIME, json.dumps({"token": "window-one", "keys": [["a.sf2", 0]]}).encode()
        )
        self.assertEqual(tree.payload(data), [["a.sf2", 0]])
        other = PresetTree("another-window", True)
        self.assertIsNone(other.payload(data))
