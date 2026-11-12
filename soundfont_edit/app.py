import json
import os
import sys
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from PySide6.QtCore import Qt, QTimer, Signal, QObject
from PySide6.QtWidgets import (
    QApplication,
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QLabel,
    QLineEdit,
    QTableWidget,
    QTableWidgetItem,
    QSplitter,
    QFileDialog,
    QMessageBox,
    QSpinBox,
    QFormLayout,
    QComboBox,
    QSlider,
    QHeaderView,
    QListWidget,
)
from .soundfont import SoundFont, export_sf2
from .cache import read_presets
from .piano import Piano


class Signals(QObject):
    scanned = Signal(object, object, object)
    exported = Signal(str, str)


class Player:
    def __init__(self):
        self.synth = None
        self.loaded = {}
        self.selected = None
        self.volume = 89
        self.velocity = 100
        self.dll_handle = None

    def select(self, path, bank, program):
        if self.synth is None:
            dll = (
                Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
                / "vendor"
            )
            if sys.platform == "win32" and dll.exists():
                self.dll_handle = os.add_dll_directory(str(dll))
                os.environ["PATH"] = str(dll) + os.pathsep + os.environ.get("PATH", "")
            import fluidsynth

            self.synth = fluidsynth.Synth()
            self.synth.start(driver=None if sys.platform == "win32" else "pulseaudio")
            if not self.synth.audio_driver:
                self.synth.delete()
                self.synth = None
                raise RuntimeError("No audio output device is available")
        if path not in self.loaded:
            ident = self.synth.sfload(path)
            if ident < 0:
                raise RuntimeError("FluidSynth cannot load this SoundFont")
            self.loaded[path] = ident
        if self.selected == (path, bank, program):
            return
        self.synth.all_sounds_off(0)
        if self.synth.program_select(0, self.loaded[path], bank, program) < 0:
            raise RuntimeError("Cannot select preset")
        self.selected = (path, bank, program)
        self.synth.cc(0, 7, self.volume)

    def on(self, n):
        if self.synth:
            self.synth.noteon(0, n, self.velocity)

    def off(self, n):
        if self.synth:
            self.synth.noteoff(0, n)

    def close(self):
        if self.synth:
            self.synth.delete()


class Window(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("SoundFont Edit Studio")
        self.resize(1400, 900)
        self.library = []
        self.entries = []
        self.sources = set()
        self.project = None
        self.dirty = False
        self.th = True
        self.labels = []
        self.player = Player()
        self.executor = ThreadPoolExecutor(max_workers=1)
        self.signals = Signals()
        self.signals.scanned.connect(self.scan_done)
        self.signals.exported.connect(self.export_done)
        self.exporting = False
        self.active = None
        self.pending = set()
        from PySide6.QtCore import QStandardPaths

        storage = Path(QStandardPaths.writableLocation(QStandardPaths.AppDataLocation))
        storage.mkdir(parents=True, exist_ok=True)
        self.settings = storage / "library.json"
        self.cache = storage / "presets.sqlite3"
        try:
            self.meta = json.loads(self.settings.read_text("utf-8"))
        except (OSError, ValueError):
            self.meta = {"favorites": [], "tags": {}}
        root = QWidget()
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        brand = QLabel("SoundFont Edit Studio")
        brand.setStyleSheet("font-size:23px;font-weight:600;padding:8px;color:#087e73")
        layout.addWidget(brand)
        top = QHBoxLayout()
        layout.addLayout(top)
        self.button(top, "เพิ่มโฟลเดอร์", "Add folder", self.add_folder)
        self.button(top, "เพิ่มไฟล์", "Add files", self.add_files)
        self.button(top, "เปิดโปรเจกต์", "Open project", self.open_project)
        self.button(top, "บันทึกโปรเจกต์", "Save project", self.save_project)
        self.export_button = self.button(
            top, "ส่งออก SF2", "Export SF2", self.export, True
        )
        top.addStretch()
        lang = QPushButton("TH / EN")
        lang.clicked.connect(self.language)
        top.addWidget(lang)
        split = QSplitter()
        layout.addWidget(split, 1)
        side = QWidget()
        sv = QVBoxLayout(side)
        split.addWidget(side)
        sv.addWidget(QLabel("SoundFont Library"))
        self.filter = QComboBox()
        self.filter.addItems(["All", "Favorites"])
        self.filter.currentIndexChanged.connect(self.refresh)
        sv.addWidget(self.filter)
        self.button(sv, "รายการโปรด ☆", "Toggle favorite ☆", self.favorite)
        self.tags = QLineEdit()
        self.tags.setPlaceholderText("Tags: Piano, Acoustic")
        sv.addWidget(self.tags)
        self.button(sv, "บันทึกแท็ก", "Save tags", self.save_tags)
        sv.addWidget(QLabel("SF2 / SF3\nBank 0–128\nProgram 0–127"))
        sv.addWidget(QLabel("โฟลเดอร์ / Folders"))
        self.folders = QListWidget()
        self.folders.currentTextChanged.connect(self.refresh)
        sv.addWidget(self.folders)
        sv.addStretch()
        center = QWidget()
        cv = QVBoxLayout(center)
        split.addWidget(center)
        self.search = QLineEdit()
        self.search.setPlaceholderText(
            "ค้นหา / Search: preset, file, tag, bank:0, program:0"
        )
        self.search.textChanged.connect(self.refresh)
        cv.addWidget(self.search)
        self.table = self.make_table(["Name", "Bank", "Program", "Source"])
        cv.addWidget(self.table, 3)
        self.table.itemSelectionChanged.connect(self.select)
        cv.addWidget(QLabel("ชุดเสียงของฉัน / My sound set"))
        self.settable = self.make_table(["Name", "Bank", "Program", "Source", "Status"])
        cv.addWidget(self.settable, 2)
        self.settable.itemSelectionChanged.connect(self.select_entry)
        actions = QHBoxLayout()
        cv.addLayout(actions)
        self.button(actions, "นำออกจากชุด", "Remove from set", self.remove)
        self.button(actions, "ขึ้น ↑", "Move up ↑", lambda: self.move_entry(-1))
        self.button(actions, "ลง ↓", "Move down ↓", lambda: self.move_entry(1))
        right = QWidget()
        form = QFormLayout(right)
        split.addWidget(right)
        form.addRow(QLabel("รายละเอียด / Details"))
        self.pname = QLineEdit()
        self.bank = QSpinBox()
        self.bank.setRange(0, 128)
        self.program = QSpinBox()
        self.program.setRange(0, 127)
        form.addRow("Name", self.pname)
        form.addRow("Bank", self.bank)
        form.addRow("Program", self.program)
        for th, en, fn in [
            ("ฟังเสียง", "Preview", self.preview),
            ("เพิ่มเข้าชุด", "Add to set", self.add_entry),
            ("แก้ไขรายการในชุด", "Apply to set item", self.apply_entry),
        ]:
            b = QPushButton(th)
            b.clicked.connect(fn)
            form.addRow(b)
            self.labels.append((b, th, en))
        split.setSizes([180, 850, 270])
        audio = QHBoxLayout()
        layout.addLayout(audio)
        audio.addWidget(QLabel("MIDI Input"))
        self.midi = QComboBox()
        self.midi.addItem("None")
        audio.addWidget(self.midi)
        self.midi.currentTextChanged.connect(self.midi_select)
        self.button(audio, "ค้นหา MIDI", "Refresh MIDI", self.midi_refresh)
        audio.addStretch()
        audio.addWidget(QLabel("Volume"))
        volume = QSlider(Qt.Horizontal)
        volume.setRange(0, 100)
        volume.setValue(70)
        volume.valueChanged.connect(self.volume)
        volume.setMaximumWidth(220)
        audio.addWidget(volume)
        audio.addWidget(QLabel("Velocity"))
        velocity = QSpinBox()
        velocity.setRange(1, 127)
        velocity.setValue(100)
        velocity.valueChanged.connect(lambda v: setattr(self.player, "velocity", v))
        audio.addWidget(velocity)
        self.button(audio, "หยุดเสียง", "Stop sound", self.stop_sound)
        self.piano = Piano()
        self.piano.pressed.connect(self.note_on)
        self.piano.released.connect(self.player.off)
        layout.addWidget(self.piano)
        self.statusBar().showMessage("Ready — add SoundFont files")
        self.midiport = None
        self.timer = QTimer()
        self.timer.timeout.connect(self.poll_midi)
        self.timer.start(10)
        QTimer.singleShot(
            0,
            lambda: self.scan(
                [p for p in self.meta.get("sources", []) if Path(p).is_file()]
            ),
        )
        self.setStyleSheet(
            "QMainWindow,QWidget{background:#f7f8f8;color:#243331;font-size:14px} QPushButton{padding:10px;border:1px solid #c8d6d3;border-radius:6px;background:white} QPushButton:hover{background:#d6efea} QLineEdit,QSpinBox,QComboBox{padding:8px;background:white;border:1px solid #c8d6d3;border-radius:5px} QTableWidget{background:white;border:1px solid #d0dcda;selection-background-color:#bfe8df;selection-color:#163b34} QHeaderView::section{background:#edf3f1;padding:8px;border:0}"
        )

    def button(self, layout, th, en, fn, primary=False):
        b = QPushButton(th)
        b.clicked.connect(fn)
        layout.addWidget(b)
        self.labels.append((b, th, en))
        if primary:
            b.setStyleSheet("background:#008c80;color:white")
        return b

    def language(self):
        self.th = not self.th
        for b, th, en in self.labels:
            b.setText(th if self.th else en)
        self.table.setHorizontalHeaderLabels(
            ["ชื่อ", "Bank", "Program", "ไฟล์ต้นทาง"]
            if self.th
            else ["Name", "Bank", "Program", "Source"]
        )
        self.settable.setHorizontalHeaderLabels(
            ["ชื่อ", "Bank", "Program", "ไฟล์ต้นทาง", "สถานะ"]
            if self.th
            else ["Name", "Bank", "Program", "Source", "Status"]
        )

    def make_table(self, headers):
        t = QTableWidget(0, len(headers))
        t.setHorizontalHeaderLabels(headers)
        t.setSelectionBehavior(QTableWidget.SelectRows)
        t.setSelectionMode(QTableWidget.SingleSelection)
        t.setEditTriggers(QTableWidget.NoEditTriggers)
        t.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        return t

    def error(self, exc):
        QMessageBox.warning(self, "SoundFont Edit Studio", str(exc))

    def add_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "SoundFont folder")
        if folder:
            self.scan(
                [
                    str(p)
                    for p in Path(folder).rglob("*")
                    if p.suffix.lower() in [".sf2", ".sf3"]
                ]
            )

    def add_files(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self, "SoundFonts", "", "SoundFont (*.sf2 *.sf3)"
        )
        self.scan(paths)

    def scan(self, paths):
        paths = list(dict.fromkeys(str(Path(p).resolve()) for p in paths))
        paths = [p for p in paths if p not in self.sources and p not in self.pending]
        self.pending.update(paths)
        if not paths:
            return
        self.statusBar().showMessage("Scanning…")

        def work():
            rows = []
            errors = []
            for path in paths:
                try:
                    rows.extend(read_presets(path, self.cache))
                except Exception as e:
                    errors.append(f"{Path(path).name}: {e}")
            self.signals.scanned.emit(rows, errors, paths)

        self.executor.submit(work)

    def scan_done(self, rows, errors, paths):
        self.pending.difference_update(paths)
        existing = {(e["path"], e["index"]) for e in self.library}
        self.library.extend(e for e in rows if (e["path"], e["index"]) not in existing)
        self.sources.update(r["path"] for r in rows)
        selected = (
            self.folders.currentItem().text() if self.folders.currentItem() else ""
        )
        self.folders.blockSignals(True)
        self.folders.clear()
        self.folders.addItems(
            ["All"] + sorted({str(Path(p).parent) for p in self.sources})
        )
        items = self.folders.findItems(selected, Qt.MatchExactly)
        self.folders.setCurrentRow(self.folders.row(items[0]) if items else 0)
        self.folders.blockSignals(False)
        self.refresh()
        self.statusBar().showMessage(
            f"{len(self.sources)} files · {len(self.library)} presets"
        )
        self.meta["sources"] = sorted(self.sources)
        self.persist()
        if errors:
            self.error("\n".join(errors[:12]))

    def ident(self, e):
        return f"{e['path']}|{e['index']}"

    def refresh(self):
        terms = self.search.text().lower().split()
        self.visible = []
        for e in self.library:
            folder = (
                self.folders.currentItem().text() if self.folders.currentItem() else ""
            )
            if folder and folder != "All" and str(Path(e["path"]).parent) != folder:
                continue
            if (
                self.filter.currentIndex() == 1
                and self.ident(e) not in self.meta["favorites"]
            ):
                continue
            hay = f"{e['name']} {e['path']} {self.meta['tags'].get(self.ident(e),'')} bank:{e['bank']} program:{e['program']}".lower()
            if all(t in hay for t in terms):
                self.visible.append(e)
        self.fill(self.table, self.visible)

    def fill(self, table, rows):
        table.blockSignals(True)
        table.setRowCount(len(rows))
        counts = {}
        for e in rows:
            counts[(e["bank"], e["program"])] = (
                counts.get((e["bank"], e["program"]), 0) + 1
            )
        for i, e in enumerate(rows):
            vals = [e["name"], e["bank"], e["program"], Path(e["path"]).name]
            if table is self.settable:
                vals += ["Duplicate" if counts[(e["bank"], e["program"])] > 1 else "OK"]
            for col, val in enumerate(vals):
                table.setItem(i, col, QTableWidgetItem(str(val)))
        table.blockSignals(False)

    def current(self):
        i = self.table.currentRow()
        return self.visible[i] if 0 <= i < len(self.visible) else None

    def select(self):
        e = self.current()
        if e:
            self.show_entry(e)
            self.tags.setText(self.meta["tags"].get(self.ident(e), ""))

    def show_entry(self, e):
        self.active = e
        self.pname.setText(e["name"])
        self.bank.setValue(e["bank"])
        self.program.setValue(e["program"])

    def select_entry(self):
        i = self.settable.currentRow()
        if 0 <= i < len(self.entries):
            self.show_entry(self.entries[i])

    def edited(self, e):
        return dict(
            e,
            source_bank=e.get("source_bank", e["bank"]),
            source_program=e.get("source_program", e["program"]),
            name=self.pname.text().strip() or e["name"],
            bank=self.bank.value(),
            program=self.program.value(),
        )

    def add_entry(self):
        e = self.active
        if e:
            self.entries.append(self.edited(e))
            self.changed()

    def apply_entry(self):
        i = self.settable.currentRow()
        if 0 <= i < len(self.entries):
            self.entries[i] = self.edited(self.entries[i])
            self.changed()

    def remove(self):
        i = self.settable.currentRow()
        if 0 <= i < len(self.entries):
            self.entries.pop(i)
            self.changed()

    def move_entry(self, delta):
        i = self.settable.currentRow()
        target = i + delta
        if 0 <= i < len(self.entries) and 0 <= target < len(self.entries):
            self.entries[i], self.entries[target] = (
                self.entries[target],
                self.entries[i],
            )
            self.changed()
            self.settable.selectRow(target)

    def stop_sound(self):
        if self.player.synth:
            self.player.synth.all_sounds_off(0)

    def changed(self):
        self.dirty = True
        self.fill(self.settable, self.entries)
        self.setWindowTitle("SoundFont Edit Studio *")

    def persist(self):
        self.settings.write_text(
            json.dumps(self.meta, ensure_ascii=False), encoding="utf-8"
        )

    def favorite(self):
        e = self.current()
        if e:
            key = self.ident(e)
            lst = self.meta["favorites"]
            lst.remove(key) if key in lst else lst.append(key)
            self.persist()
            self.refresh()

    def save_tags(self):
        e = self.current()
        if e:
            self.meta["tags"][self.ident(e)] = self.tags.text()
            self.persist()
            self.refresh()

    def may_discard(self):
        return (
            not self.dirty
            or QMessageBox.question(
                self,
                "Unsaved project",
                "Discard unsaved project changes?",
                QMessageBox.Yes | QMessageBox.No,
            )
            == QMessageBox.Yes
        )

    def project_path(self, path, base):
        try:
            return os.path.relpath(path, base)
        except ValueError:
            return str(Path(path).resolve())

    def save_project(self):
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Save project",
            self.project or "My sound set.sfedit",
            "SF Edit project (*.sfedit)",
        )
        if not path:
            return
        try:
            if str(Path(path).resolve()) in self.sources or Path(
                path
            ).suffix.lower() in (".sf2", ".sf3"):
                raise ValueError(
                    "Save projects as .sfedit; source banks cannot be overwritten"
                )
            base = Path(path).resolve().parent
            entries = [
                dict(e, path=self.project_path(e["path"], base)) for e in self.entries
            ]
            temp = Path(path + ".tmp")
            temp.write_text(
                json.dumps(
                    {"version": 1, "entries": entries}, ensure_ascii=False, indent=2
                ),
                encoding="utf-8",
            )
            temp.replace(path)
            self.project = path
            self.dirty = False
            self.setWindowTitle("SoundFont Edit Studio")
        except Exception as exc:
            self.error(exc)

    def open_project(self):
        if not self.may_discard():
            return
        path, _ = QFileDialog.getOpenFileName(
            self, "Open project", "", "SF Edit project (*.sfedit)"
        )
        if not path:
            return
        try:
            data = json.loads(Path(path).read_text("utf-8"))
            if data["version"] != 1:
                raise ValueError("Unsupported project version")
            entries = []
            for e in data["entries"]:
                source = str((Path(path).parent / e["path"]).resolve())
                sf = SoundFont(source)
                if not 0 <= int(e["index"]) < len(sf.presets):
                    raise ValueError("Invalid preset index")
                entries.append(dict(e, path=source))
            self.entries = entries
            self.fill(self.settable, self.entries)
            self.project = path
            self.dirty = False
            self.setWindowTitle("SoundFont Edit Studio")
            self.scan(list({e["path"] for e in entries}))
        except Exception as exc:
            self.error(exc)

    def export(self):
        if self.exporting:
            return
        if not self.entries:
            self.error("Add presets to the sound set first")
            return
        summary = f"{len(self.entries)} presets → SF2\nSources are preserved. All source samples are retained.\nPreset names use the SF2 ASCII encoding.\nContinue?"
        if QMessageBox.question(self, "Export SF2", summary) != QMessageBox.Yes:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Export SF2", "My sound set.sf2", "SoundFont (*.sf2)"
        )
        if not path:
            return
        self.exporting = True
        self.export_button.setEnabled(False)
        entries = [dict(e) for e in self.entries]
        self.statusBar().showMessage("Exporting…")

        def work():
            try:
                export_sf2(entries, path)
                self.signals.exported.emit(path, "")
            except Exception as exc:
                self.signals.exported.emit(path, str(exc))

        self.executor.submit(work)

    def export_done(self, path, error):
        self.exporting = False
        self.export_button.setEnabled(True)
        if error:
            self.error(error)
            self.statusBar().showMessage("Export failed")
        else:
            self.statusBar().showMessage(f"Exported: {path}")

    def preview(self):
        e = self.active
        if e:
            try:
                self.player.select(
                    e["path"],
                    e.get("source_bank", e["bank"]),
                    e.get("source_program", e["program"]),
                )
                self.player.on(60)
                QTimer.singleShot(600, lambda: self.player.off(60))
            except Exception as exc:
                self.error(
                    f"Audio unavailable: {exc}\nInstall FluidSynth and its DLL dependencies; see README."
                )

    def note_on(self, n):
        if self.active is None:
            return
        try:
            e = self.active
            self.player.select(
                e["path"],
                e.get("source_bank", e["bank"]),
                e.get("source_program", e["program"]),
            )
            self.player.on(n)
        except Exception as exc:
            self.error(f"Audio unavailable: {exc}")

    def volume(self, v):
        self.player.volume = v * 127 // 100
        if self.player.synth:
            self.player.synth.cc(0, 7, self.player.volume)

    def midi_refresh(self):
        try:
            import mido

            self.midi.clear()
            self.midi.addItems(["None"] + mido.get_input_names())
        except Exception as exc:
            self.error(exc)

    def midi_select(self, label):
        if self.midiport:
            self.midiport.close()
            self.midiport = None
        if label and label != "None":
            try:
                import mido

                self.midiport = mido.open_input(label)
            except Exception as exc:
                self.error(exc)

    def poll_midi(self):
        if self.midiport:
            for msg in self.midiport.iter_pending():
                if msg.type == "note_on" and msg.velocity:
                    self.note_on(msg.note)
                elif msg.type in ["note_off", "note_on"]:
                    self.player.off(msg.note)

    def keyPressEvent(self, event):
        keys = "awsedftgyhujkolp"
        if (
            not event.isAutoRepeat()
            and event.text() in keys
            and event.text()
            and not isinstance(self.focusWidget(), (QLineEdit, QSpinBox))
        ):
            self.note_on(60 + keys.index(event.text()))
        else:
            super().keyPressEvent(event)

    def keyReleaseEvent(self, event):
        keys = "awsedftgyhujkolp"
        if not event.isAutoRepeat() and event.text() and event.text() in keys:
            self.player.off(60 + keys.index(event.text()))
        else:
            super().keyReleaseEvent(event)

    def closeEvent(self, event):
        if self.exporting or self.pending:
            self.error("Please wait for scanning/export to finish")
            event.ignore()
            return
        if not self.may_discard():
            event.ignore()
            return
        self.timer.stop()
        if self.midiport:
            self.midiport.close()
        self.player.close()
        self.executor.shutdown(wait=False, cancel_futures=True)
        event.accept()


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("SoundFont Edit Studio")
    w = Window()
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
