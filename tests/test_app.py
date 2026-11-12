import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from PySide6.QtCore import QStandardPaths
from PySide6.QtWidgets import QApplication, QFileDialog
from soundfont_edit.app import Window
from test_soundfont import fixture


class AppTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        QStandardPaths.setTestModeEnabled(True)
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setApplicationName("SoundFontEditStudioTests")

    def test_scan_edit_project_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            bank = tmp / "piano.sf2"
            project = tmp / "set.sfedit"
            fixture(bank)
            w = Window()
            # Test metadata never touches an existing user's library.
            w.meta = {"favorites": [], "tags": {}}
            w.settings = tmp / "library.json"
            w.cache = tmp / "cache.db"
            errors = []
            w.error = errors.append
            w.show()
            self.app.processEvents()
            w.scan([str(bank), str(bank)])
            deadline = time.monotonic() + 10
            while w.pending and time.monotonic() < deadline:
                self.app.processEvents()
                time.sleep(0.01)
            self.assertFalse(w.pending)
            self.assertEqual(len(w.library), 1)
            w.table.selectRow(0)
            self.app.processEvents()
            w.pname.setText("My Piano")
            w.bank.setValue(3)
            w.program.setValue(12)
            w.add_entry()
            self.assertEqual(
                (w.entries[0]["name"], w.entries[0]["bank"], w.entries[0]["program"]),
                ("My Piano", 3, 12),
            )
            self.assertEqual(w.entries[0]["source_bank"], 0)
            w.tags.setText("Acoustic")
            w.save_tags()
            w.search.setText("acoustic")
            self.assertEqual(w.table.rowCount(), 1)
            w.search.setText("missing")
            self.assertEqual(w.table.rowCount(), 0)
            w.search.clear()
            with patch.object(
                QFileDialog, "getSaveFileName", return_value=(str(project), "")
            ):
                w.save_project()
            self.assertFalse(w.dirty)
            self.assertTrue(project.exists())
            w.entries = []
            with patch.object(
                QFileDialog, "getOpenFileName", return_value=(str(project), "")
            ):
                w.open_project()
            self.assertEqual(w.entries[0]["name"], "My Piano")
            self.assertEqual(w.entries[0]["path"], str(bank.resolve()))
            w.language()
            self.assertEqual(w.export_button.text(), "Export SF2")
            self.assertEqual(errors, [])
            w.close()
            self.app.processEvents()
