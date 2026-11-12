"""Two-pane source/destination SoundFont editor."""

import json
import os
import sys
import uuid
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from PySide6.QtCore import Qt, QTimer, Signal, QObject, QStandardPaths
from PySide6.QtWidgets import (
    QApplication,
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QLabel,
    QLineEdit,
    QSplitter,
    QFileDialog,
    QMessageBox,
    QSpinBox,
    QFormLayout,
    QComboBox,
    QSlider,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QInputDialog,
    QMenu,
)
from .soundfont import SoundFont, export_sf2
from .cache import read_presets
from .piano import Piano
from .audio import Player
from .preset_tree import PresetTree, ROLE
from .soundset import ordered, copy_entry, merge_entries, slot


class Signals(QObject):
    scanned = Signal(object, object, object)
    loaded = Signal(object, str)
    exported = Signal(str, str)


class Window(QMainWindow):
    def __init__(self):
        super().__init__()
        self.resize(1500, 940)
        self.library = []
        self.entries = []
        self.sources = set()
        self.pending = set()
        self.project = None
        self.destination_path = None
        self.destination_name = "New SoundFont.sf2"
        self.dirty = False
        self.loading = False
        self.exporting = False
        self.active = None
        self.active_side = None
        self.th = True
        self.labels = []
        self.player = Player()
        self.midiport = None
        self.only_favorites = False
        self.executor = ThreadPoolExecutor(max_workers=1)
        self.signals = Signals()
        self.signals.scanned.connect(self.scan_done)
        self.signals.loaded.connect(self.load_done)
        self.signals.exported.connect(self.export_done)
        storage = Path(QStandardPaths.writableLocation(QStandardPaths.AppDataLocation))
        storage.mkdir(parents=True, exist_ok=True)
        self.settings = storage / "library.json"
        self.cache = storage / "presets.sqlite3"
        try:
            self.meta = json.loads(self.settings.read_text("utf-8"))
            if not isinstance(self.meta, dict):
                raise ValueError("Invalid metadata")
        except (OSError, ValueError):
            self.meta = {}
        self.meta.setdefault("favorites", [])
        self.meta.setdefault("tags", {})
        self.token = uuid.uuid4().hex
        root = QWidget()
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        layout.setSpacing(12)
        brand = QLabel("♫  SoundFont Edit Studio 0.2")
        brand.setStyleSheet("font-size:24px;font-weight:600;color:#087e73;padding:6px")
        toolbar = QHBoxLayout()
        layout.addLayout(toolbar)
        toolbar.addWidget(brand)
        self.project_open = self.button(
            toolbar, "เปิดโปรเจกต์", "Open project", self.open_project
        )
        self.project_save = self.button(
            toolbar, "บันทึกโปรเจกต์", "Save project", self.save_project
        )
        library_button = self.button(toolbar, "คลังเสียง ▾", "Library ▾", lambda: None)
        menu = QMenu(library_button)
        addfolder = menu.addAction("เพิ่มโฟลเดอร์ / Add folder")
        addfolder.triggered.connect(self.add_folder)
        self.favorite_filter = menu.addAction("เฉพาะรายการโปรด / Favorites only")
        self.favorite_filter.setCheckable(True)
        self.favorite_filter.toggled.connect(self.set_favorites_filter)
        library_button.setMenu(menu)
        toolbar.addStretch()
        self.button(toolbar, "TH / EN", "TH / EN", self.language)
        split = QSplitter()
        layout.addWidget(split, 1)
        source, sv = self.panel("ต้นทาง / Source SF2", "Source SF2")
        split.addWidget(source)
        controls = QHBoxLayout()
        sv.addLayout(controls)
        self.button(controls, "＋ เพิ่ม SF2", "＋ Add SF2", self.add_files)
        self.source_files = QComboBox()
        self.source_files.setMinimumWidth(180)
        controls.addWidget(self.source_files, 1)
        self.source_files.currentIndexChanged.connect(self.refresh_source)
        self.source_search = QLineEdit()
        sv.addWidget(self.source_search)
        self.source_search.textChanged.connect(self.refresh_source)
        self.source_tree = PresetTree(self.token)
        sv.addWidget(self.source_tree, 1)
        self.source_tree.itemSelectionChanged.connect(lambda: self.select("source"))
        self.source_tree.itemDoubleClicked.connect(
            lambda item, col: self.preview() if item.data(0, ROLE) else None
        )
        self.source_tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.source_tree.customContextMenuRequested.connect(self.source_context)
        self.source_count = QLabel()
        sv.addWidget(self.source_count)
        middle = QWidget()
        mv = QVBoxLayout(middle)
        mv.setContentsMargins(0, 0, 0, 0)
        mv.addStretch()
        self.copy_button = self.button(
            mv, "คัดลอก →", "Copy →", self.copy_selected, True
        )
        mv.addStretch()
        split.addWidget(middle)
        destination, dv = self.panel("ปลายทาง / Destination SF2", "Destination SF2")
        split.addWidget(destination)
        controls = QHBoxLayout()
        dv.addLayout(controls)
        self.new_button = self.button(
            controls, "สร้างใหม่", "New SF2", self.new_destination
        )
        self.open_target_button = self.button(
            controls, "เปิด SF2 เดิม", "Open SF2", self.open_destination
        )
        self.target_name = QLabel(self.destination_name)
        self.target_name.setStyleSheet("font-weight:600;padding:6px")
        controls.addWidget(self.target_name, 1)
        self.destination_search = QLineEdit()
        dv.addWidget(self.destination_search)
        self.destination_search.textChanged.connect(self.refresh_destination)
        self.destination_tree = PresetTree(self.token, True)
        dv.addWidget(self.destination_tree, 1)
        self.destination_tree.itemSelectionChanged.connect(
            lambda: self.select("destination")
        )
        self.destination_tree.itemDoubleClicked.connect(
            lambda item, col: self.preview() if item.data(0, ROLE) else None
        )
        self.destination_tree.dropped.connect(self.drop_source)
        self.destination_count = QLabel()
        dv.addWidget(self.destination_count)
        controls = QHBoxLayout()
        dv.addLayout(controls)
        self.rename_button = self.button(controls, "เปลี่ยนชื่อ", "Rename", self.rename)
        self.slot_button = self.button(
            controls, "Bank / ID", "Bank / ID", self.change_slot
        )
        self.remove_button = self.button(controls, "นำออก", "Remove", self.remove)
        controls.addStretch()
        self.export_button = self.button(
            controls, "บันทึกเป็น SF2 ใหม่", "Save as new SF2", self.export, True
        )
        split.setStretchFactor(0, 1)
        split.setStretchFactor(2, 1)
        split.setSizes([650, 120, 650])
        middle.setMaximumWidth(135)
        audio = QHBoxLayout()
        layout.addLayout(audio)
        self.audition = QLabel()
        self.audition.setMinimumWidth(230)
        audio.addWidget(self.audition, 1)
        self.button(audio, "▶ ฟัง", "▶ Play", self.preview)
        self.button(audio, "■ หยุด", "■ Stop", self.stop_sound)
        audio.addWidget(QLabel("MIDI"))
        self.midi = QComboBox()
        self.midi.addItem("None")
        self.midi.setMaximumWidth(190)
        audio.addWidget(self.midi)
        self.midi.currentTextChanged.connect(self.midi_select)
        self.button(audio, "ค้นหา MIDI", "Refresh MIDI", self.midi_refresh)
        audio.addWidget(QLabel("Volume"))
        volume = QSlider(Qt.Horizontal)
        volume.setRange(0, 100)
        volume.setValue(70)
        volume.setMaximumWidth(140)
        volume.valueChanged.connect(self.volume)
        audio.addWidget(volume)
        audio.addWidget(QLabel("Velocity"))
        velocity = QSpinBox()
        velocity.setRange(1, 127)
        velocity.setValue(100)
        velocity.valueChanged.connect(lambda v: setattr(self.player, "velocity", v))
        audio.addWidget(velocity)
        self.piano = Piano()
        self.piano.pressed.connect(self.note_on)
        self.piano.released.connect(self.player.off)
        layout.addWidget(self.piano)
        footer = QHBoxLayout()
        layout.addLayout(footer)
        self.numbering = QCheckBox()
        self.numbering.toggled.connect(self.refresh)
        footer.addWidget(self.numbering)
        self.gm_hint = QLabel()
        footer.addWidget(self.gm_hint)
        self.piano_toggle = QCheckBox()
        self.piano_toggle.setChecked(True)
        self.piano_toggle.toggled.connect(self.piano.setVisible)
        self.labels.append((self.piano_toggle, "แสดงคีย์บอร์ด", "Show piano"))
        footer.addWidget(self.piano_toggle)
        footer.addStretch()
        self.slot_status = QLabel()
        footer.addWidget(self.slot_status)
        self.edit_controls = [
            self.copy_button,
            self.new_button,
            self.open_target_button,
            self.rename_button,
            self.slot_button,
            self.remove_button,
            self.destination_tree,
            self.project_open,
            self.project_save,
            self.export_button,
        ]
        self.timer = QTimer()
        self.timer.timeout.connect(self.poll_midi)
        self.timer.start(10)
        self.setStyleSheet(
            "QMainWindow,QWidget{background:#f7f9f8;color:#243b37;font-size:15px} QPushButton{padding:9px;border:1px solid #c7d8d3;border-radius:6px;background:white} QPushButton:hover{background:#d9f0e9} QPushButton:disabled{color:#8da39c;background:#edf2f0} QLineEdit,QSpinBox,QComboBox{padding:8px;background:white;border:1px solid #c7d8d3;border-radius:5px} QTreeWidget{background:white;alternate-background-color:#f7fbf9;border:1px solid #c7d8d3;selection-background-color:#bfe8df;selection-color:#163b34} QTreeWidget::item{min-height:29px;padding:3px} QHeaderView::section{background:#edf3f1;padding:9px;border:0;font-weight:600} QSplitter::handle{background:#e0ebe7;width:4px}"
        )
        self.update_language()
        self.refresh()
        self.update_title()
        QTimer.singleShot(
            0,
            lambda: self.scan(
                [p for p in self.meta.get("sources", []) if Path(p).is_file()]
            ),
        )

    def text(self, th, en):
        return th if self.th else en

    def button(self, layout, th, en, fn, primary=False):
        button = QPushButton(th)
        button.clicked.connect(fn)
        layout.addWidget(button)
        self.labels.append((button, th, en))
        if primary:
            button.setStyleSheet(
                "QPushButton{background:#008d80;color:white;font-weight:600} QPushButton:disabled{background:#a6c6bf}"
            )
        return button

    def panel(self, th, en):
        widget = QWidget()
        v = QVBoxLayout(widget)
        v.setContentsMargins(0, 0, 0, 0)
        label = QLabel(th)
        label.setStyleSheet(
            "background:#008d80;color:white;font-size:21px;font-weight:600;padding:12px;border-radius:6px"
        )
        v.addWidget(label)
        self.labels.append((label, th, en))
        return widget, v

    def language(self):
        self.th = not self.th
        self.update_language()
        self.refresh()

    def update_language(self):
        for label, th, en in self.labels:
            label.setText(self.text(th, en))
        for search in [self.source_search, self.destination_search]:
            search.setPlaceholderText(
                self.text(
                    "ค้นหาชื่อเสียง / GM / bank:0 / id:0…",
                    "Search preset / GM / bank:0 / id:0…",
                )
            )
        self.numbering.setText(
            self.text(
                "แสดงหมายเลข GM 1–128 (แทน ID 0–127)",
                "Show GM numbers 1–128 (instead of ID 0–127)",
            )
        )
        self.gm_hint.setText(
            self.text(
                "ชื่อ GM เป็นข้อมูลอ้างอิงของช่องเสียง",
                "GM names describe the standard slot",
            )
        )
        self.update_audition()

    def update_title(self):
        self.setWindowTitle("SoundFont Edit Studio 0.2" + (" *" if self.dirty else ""))

    def busy(self):
        return self.loading or self.exporting

    def set_busy(self):
        for control in self.edit_controls:
            control.setEnabled(not self.busy())

    def error(self, exc):
        QMessageBox.warning(self, "SoundFont Edit Studio", str(exc))

    def persist(self):
        try:
            self.settings.write_text(
                json.dumps(self.meta, ensure_ascii=False), encoding="utf-8"
            )
        except OSError as exc:
            self.statusBar().showMessage(str(exc))

    def add_files(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self,
            self.text("เพิ่มไฟล์ต้นทาง", "Add source files"),
            "",
            "SoundFont (*.sf2 *.sf3)",
        )
        self.scan(paths)

    def add_folder(self):
        folder = QFileDialog.getExistingDirectory(
            self, self.text("เพิ่มโฟลเดอร์", "Add folder")
        )
        if folder:
            self.scan(
                [
                    str(p)
                    for p in Path(folder).rglob("*")
                    if p.is_file() and p.suffix.lower() in (".sf2", ".sf3")
                ]
            )

    def scan(self, paths):
        paths = list(dict.fromkeys(str(Path(p).resolve()) for p in paths))
        paths = [p for p in paths if p not in self.sources and p not in self.pending]
        if not paths:
            return
        self.pending.update(paths)
        self.statusBar().showMessage(
            self.text("กำลังอ่านรายการเสียง…", "Reading presets…")
        )

        def work():
            rows = []
            errors = []
            for path in paths:
                try:
                    rows.extend(read_presets(path, self.cache))
                except Exception as exc:
                    errors.append(f"{Path(path).name}: {exc}")
            self.signals.scanned.emit(rows, errors, paths)

        self.executor.submit(work)

    def scan_done(self, rows, errors, paths):
        self.pending.difference_update(paths)
        existing = {(e["path"], e["index"]) for e in self.library}
        self.library.extend(e for e in rows if (e["path"], e["index"]) not in existing)
        self.sources.update(e["path"] for e in rows)
        previous = self.source_files.currentData()
        self.source_files.blockSignals(True)
        self.source_files.clear()
        for path in sorted(self.sources, key=lambda p: (Path(p).name.casefold(), p)):
            self.source_files.addItem(Path(path).name, path)
            self.source_files.setItemData(
                self.source_files.count() - 1, path, Qt.ToolTipRole
            )
        index = self.source_files.findData(previous)
        self.source_files.setCurrentIndex(max(index, 0))
        self.source_files.blockSignals(False)
        self.refresh_source()
        self.meta["sources"] = sorted(self.sources)
        self.persist()
        self.statusBar().showMessage(
            f"{len(self.sources)} files · {len(self.library)} presets"
        )
        if errors:
            self.error("\n".join(errors[:12]))

    def ident(self, e):
        return f"{e['path']}|{e['index']}"

    def refresh(self):
        self.refresh_source()
        self.refresh_destination()

    def refresh_source(self):
        path = self.source_files.currentData()
        rows = []
        for e in self.library:
            if e["path"] != path:
                continue
            favorite = self.ident(e) in self.meta["favorites"]
            if self.only_favorites and not favorite:
                continue
            rows.append(
                dict(
                    e,
                    _tags=self.meta["tags"].get(self.ident(e), ""),
                    _favorite=favorite,
                )
            )
        self.source_tree.populate(
            rows, self.source_search.text(), self.numbering.isChecked(), self.th
        )
        self.source_count.setText(
            self.text(
                f"{len(self.sources)} ไฟล์ · แสดง {len(self.source_tree.rows)} เสียง",
                f"{len(self.sources)} files · {len(self.source_tree.rows)} presets shown",
            )
        )
        self.reconcile_active("source")

    def refresh_destination(self):
        self.destination_tree.populate(
            self.entries,
            self.destination_search.text(),
            self.numbering.isChecked(),
            self.th,
        )
        self.destination_count.setText(
            self.text(
                f"{len(self.entries)} เสียงในปลายทาง · แสดง {len(self.destination_tree.rows)}",
                f"{len(self.entries)} destination presets · {len(self.destination_tree.rows)} shown",
            )
        )
        duplicates = len({slot(e) for e in self.entries}) != len(self.entries)
        self.slot_status.setText("Bank / ID: " + ("Duplicate!" if duplicates else "OK"))
        self.target_name.setText(self.destination_name)
        self.target_name.setToolTip(self.destination_path or self.destination_name)
        self.reconcile_active("destination")

    def reconcile_active(self, side):
        if self.active_side != side:
            return
        tree = self.source_tree if side == "source" else self.destination_tree
        selected = tree.selected_entries()
        self.active = selected[0] if selected else None
        if not self.active:
            self.stop_sound()
        self.update_audition()

    def select(self, side):
        tree = self.source_tree if side == "source" else self.destination_tree
        selected = tree.selected_entries()
        if selected:
            self.active = selected[0]
            self.active_side = side
            self.stop_sound()
            self.update_audition()

    def update_audition(self):
        if not hasattr(self, "audition"):
            return
        if not self.active:
            self.audition.setText(
                self.text("เลือกเสียงเพื่อทดลองฟัง", "Select a preset to audition")
            )
            return
        side = (
            self.text("ต้นทาง", "Source")
            if self.active_side == "source"
            else self.text("ปลายทาง", "Destination")
        )
        self.audition.setText(f"{side} · {self.active['name']}")

    def source_context(self, pos):
        if not self.source_tree.selected_entries():
            return
        menu = QMenu(self)
        menu.addAction(
            self.text("เพิ่ม/ลบรายการโปรด ☆", "Toggle favorite ☆"), self.favorite
        )
        menu.addAction(self.text("แก้ไขแท็ก", "Edit tags"), self.edit_tags)
        menu.exec(self.source_tree.viewport().mapToGlobal(pos))

    def set_favorites_filter(self, checked):
        self.only_favorites = checked
        self.refresh_source()

    def favorite(self):
        for e in self.source_tree.selected_entries():
            key = self.ident(e)
            favorites = self.meta["favorites"]
            favorites.remove(key) if key in favorites else favorites.append(key)
        self.persist()
        self.refresh_source()

    def edit_tags(self):
        entries = self.source_tree.selected_entries()
        if not entries:
            return
        value, ok = QInputDialog.getText(
            self,
            self.text("แท็ก", "Tags"),
            "Piano, Acoustic",
            text=self.meta["tags"].get(self.ident(entries[0]), ""),
        )
        if ok:
            for e in entries:
                self.meta["tags"][self.ident(e)] = value
            self.persist()
            self.refresh_source()

    def copy_selected(self):
        self.copy_to_destination(self.source_tree.selected_entries())

    def drop_source(self, keys):
        try:
            lookup = {(e["path"], e["index"]): e for e in self.library}
            entries = [
                lookup[(str(key[0]), int(key[1]))] for key in keys if len(key) == 2
            ]
        except (KeyError, TypeError, ValueError):
            return
        self.copy_to_destination(entries)

    def copy_to_destination(self, entries):
        if self.busy() or not entries:
            return
        incoming = [dict(copy_entry(e), _uid=uuid.uuid4().hex) for e in entries]
        try:
            result = merge_entries(self.entries, incoming, self.resolve_collision)
        except ValueError as exc:
            self.error(exc)
            return
        if result is not None:
            self.entries = result
            self.changed()

    def resolve_collision(self, candidate, conflict, working):
        box = QMessageBox(self)
        box.setWindowTitle(self.text("Bank / ID ซ้ำ", "Bank / ID conflict"))
        box.setText(
            self.text(
                f"Bank {candidate['bank']} / ID {candidate['program']:03d} มีเสียงอยู่แล้ว",
                f"Bank {candidate['bank']} / ID {candidate['program']:03d} is occupied",
            )
        )
        box.setInformativeText(f"{conflict['name']}  ←  {candidate['name']}")
        replace = box.addButton(self.text("แทนที่", "Replace"), QMessageBox.AcceptRole)
        remap = box.addButton(
            self.text("เปลี่ยน Bank / ID", "Change Bank / ID"), QMessageBox.ActionRole
        )
        cancel = box.addButton(
            self.text("ยกเลิกทั้งหมด", "Cancel batch"), QMessageBox.RejectRole
        )
        box.setDefaultButton(cancel)
        box.exec()
        if box.clickedButton() is replace:
            return "replace", None
        if box.clickedButton() is remap:
            value = self.ask_slot(candidate, {slot(e) for e in working})
            if value is not None:
                return "remap", value
        return "cancel", None

    def ask_slot(self, entry, occupied):
        dialog = QDialog(self)
        dialog.setWindowTitle(
            self.text("กำหนด Bank / Preset ID", "Set Bank / Preset ID")
        )
        form = QFormLayout(dialog)
        form.addRow(
            QLabel(
                self.text(
                    "ใช้ ID 0–127 เสมอในกล่องนี้", "This dialog always uses ID 0–127"
                )
            )
        )
        bank = QSpinBox()
        bank.setRange(0, 128)
        bank.setValue(entry["bank"])
        program = QSpinBox()
        program.setRange(0, 127)
        program.setValue(entry["program"])
        form.addRow("Bank", bank)
        form.addRow("Preset ID", program)
        warning = QLabel()
        form.addRow(warning)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        form.addRow(buttons)

        def validate():
            if (bank.value(), program.value()) in occupied:
                warning.setText(
                    self.text(
                        "ช่องนี้มีเสียงแล้ว กรุณาเลือกหมายเลขอื่น",
                        "Slot occupied; choose another Bank / ID",
                    )
                )
                return
            dialog.accept()

        buttons.accepted.connect(validate)
        buttons.rejected.connect(dialog.reject)
        return (
            (bank.value(), program.value())
            if dialog.exec() == QDialog.Accepted
            else None
        )

    def rename(self):
        selected = self.destination_tree.selected_entries()
        if self.busy() or len(selected) != 1:
            return
        e = selected[0]
        name, ok = QInputDialog.getText(
            self,
            self.text("เปลี่ยนชื่อ", "Rename"),
            self.text("ชื่อ preset", "Preset name"),
            text=e["name"],
        )
        if ok and name.strip():
            e["name"] = name.strip()
            self.changed()

    def change_slot(self):
        selected = self.destination_tree.selected_entries()
        if self.busy() or len(selected) != 1:
            return
        e = selected[0]
        occupied = {slot(other) for other in self.entries if other is not e}
        value = self.ask_slot(e, occupied)
        if value is not None:
            e["bank"], e["program"] = value
            self.changed()

    def remove(self):
        if self.busy():
            return
        selected = {e["_uid"] for e in self.destination_tree.selected_entries()}
        if selected:
            self.entries = [e for e in self.entries if e["_uid"] not in selected]
            self.changed()

    def changed(self):
        self.entries = ordered(self.entries)
        self.dirty = True
        self.refresh_destination()
        self.update_title()

    def may_discard(self):
        return (
            not self.dirty
            or QMessageBox.question(
                self,
                self.text("ยังไม่ได้บันทึก", "Unsaved changes"),
                self.text(
                    "ละทิ้งการแก้ไขปลายทางที่ยังไม่ได้บันทึกหรือไม่?",
                    "Discard unsaved destination changes?",
                ),
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            == QMessageBox.Yes
        )

    def new_destination(self):
        if self.busy() or not self.may_discard():
            return
        self.stop_sound()
        self.entries = []
        self.project = None
        self.destination_path = None
        self.destination_name = "New SoundFont.sf2"
        self.dirty = False
        self.active = None
        self.active_side = None
        self.refresh_destination()
        self.update_audition()
        self.update_title()

    def open_destination(self):
        if self.busy():
            return
        path, _ = QFileDialog.getOpenFileName(
            self,
            self.text("เปิด SF2 ปลายทาง", "Open destination SF2"),
            "",
            "SoundFont (*.sf2)",
        )
        if path and self.may_discard():
            self.load_destination(path)

    def load_destination(self, path):
        if self.busy():
            return
        self.loading = True
        self.set_busy()
        self.statusBar().showMessage(
            self.text("กำลังเปิดปลายทาง…", "Opening destination…")
        )

        def work():
            try:
                sf = SoundFont(path)
                if sf.major >= 3:
                    raise ValueError("SF3 cannot be used as an export destination yet")
                entries = [
                    dict(
                        path=str(Path(path).resolve()),
                        index=p.index,
                        name=p.name,
                        bank=p.bank,
                        program=p.program,
                    )
                    for p in sf.presets
                ]
                if len({slot(e) for e in entries}) != len(entries):
                    raise ValueError("The destination contains duplicate Bank / IDs")
                self.signals.loaded.emit(
                    dict(
                        entries=entries,
                        destination_name=Path(path).name,
                        destination_path=str(Path(path).resolve()),
                        project=None,
                        source_paths=[],
                    ),
                    "",
                )
            except Exception as exc:
                self.signals.loaded.emit(None, str(exc))

        self.executor.submit(work)

    def load_done(self, data, error):
        self.loading = False
        self.set_busy()
        if error:
            self.error(error)
            return
        self.stop_sound()
        self.entries = ordered(
            [dict(copy_entry(e), _uid=uuid.uuid4().hex) for e in data["entries"]]
        )
        self.destination_name = data["destination_name"]
        self.destination_path = data.get("destination_path")
        self.project = data["project"]
        self.dirty = False
        self.active = None
        self.active_side = None
        self.refresh_destination()
        self.update_audition()
        self.update_title()
        self.statusBar().showMessage(self.text("เปิดปลายทางแล้ว", "Destination loaded"))
        self.scan(data.get("source_paths", []))

    def project_path(self, path, base):
        try:
            return os.path.relpath(path, base)
        except ValueError:
            return str(Path(path).resolve())

    def protected_paths(self):
        return {
            str(Path(p).resolve()).casefold()
            for p in self.sources
            | {e["path"] for e in self.entries}
            | ({self.destination_path} if self.destination_path else set())
        }

    def save_project(self):
        if self.busy():
            return
        path, _ = QFileDialog.getSaveFileName(
            self,
            self.text("บันทึกโปรเจกต์", "Save project"),
            self.project or "My sound set.sfedit",
            "SF Edit project (*.sfedit)",
        )
        if not path:
            return
        if not Path(path).suffix:
            path += ".sfedit"
        try:
            if (
                Path(path).suffix.lower() != ".sfedit"
                or str(Path(path).resolve()).casefold() in self.protected_paths()
            ):
                raise ValueError("Choose a new .sfedit project file")
            base = Path(path).resolve().parent
            entries = [
                dict(
                    {k: v for k, v in e.items() if not k.startswith("_")},
                    path=self.project_path(e["path"], base),
                )
                for e in self.entries
            ]
            data = {
                "version": 2,
                "entries": entries,
                "destination_name": self.destination_name,
                "destination_path": (
                    self.project_path(self.destination_path, base)
                    if self.destination_path
                    else None
                ),
                "sources": [self.project_path(p, base) for p in sorted(self.sources)],
            }
            temp = Path(path + ".tmp")
            temp.write_text(
                json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            temp.replace(path)
            self.project = path
            self.dirty = False
            self.update_title()
            self.statusBar().showMessage(
                self.text("บันทึกโปรเจกต์แล้ว", "Project saved")
            )
        except Exception as exc:
            self.error(exc)

    def open_project(self):
        if self.busy():
            return
        path, _ = QFileDialog.getOpenFileName(
            self,
            self.text("เปิดโปรเจกต์", "Open project"),
            "",
            "SF Edit project (*.sfedit)",
        )
        if not path or not self.may_discard():
            return
        self.loading = True
        self.set_busy()

        def work():
            try:
                data = json.loads(Path(path).read_text("utf-8"))
                if data["version"] not in (1, 2):
                    raise ValueError("Unsupported project version")
                base = Path(path).resolve().parent
                loaded = {}
                entries = []
                for entry in data["entries"]:
                    if not isinstance(entry.get("name"), str):
                        raise ValueError("Invalid preset name in project")
                    source = str((base / entry["path"]).resolve())
                    if source not in loaded:
                        loaded[source] = SoundFont(source)
                    sf = loaded[source]
                    index = int(entry["index"])
                    if not 0 <= index < len(sf.presets):
                        raise ValueError("Invalid preset index")
                    bank, program = slot(entry)
                    if not 0 <= bank <= 128 or not 0 <= program <= 127:
                        raise ValueError("Invalid Bank / ID")
                    p = sf.presets[index]
                    entries.append(
                        dict(
                            entry,
                            path=source,
                            bank=bank,
                            program=program,
                            source_bank=p.bank,
                            source_program=p.program,
                        )
                    )
                if len({slot(e) for e in entries}) != len(entries):
                    raise ValueError(
                        "Project contains duplicate Bank / IDs; resolve them in version 0.1 before importing"
                    )
                if not isinstance(
                    data.get("destination_name", "New SoundFont.sf2"), str
                ):
                    raise ValueError("Invalid destination name in project")
                origin = data.get("destination_path")
                result = dict(
                    entries=entries,
                    destination_name=data.get("destination_name", "New SoundFont.sf2"),
                    destination_path=str((base / origin).resolve()) if origin else None,
                    project=path,
                    source_paths=list(
                        set(loaded)
                        | {
                            str((base / p).resolve())
                            for p in data.get("sources", [])
                            if (base / p).is_file()
                        }
                    ),
                )
                self.signals.loaded.emit(result, "")
            except Exception as exc:
                self.signals.loaded.emit(None, str(exc))

        self.executor.submit(work)

    def export(self):
        if self.busy():
            return
        if not self.entries:
            self.error(
                self.text(
                    "เลือกเสียงจากซ้ายแล้วคัดลอกไปขวาก่อน",
                    "Copy presets from source to destination first",
                )
            )
            return
        if any(Path(e["path"]).suffix.lower() == ".sf3" for e in self.entries):
            self.error(
                self.text(
                    "ยังส่งออกเสียงจาก SF3 ไม่ได้ กรุณาใช้ SF2",
                    "SF3 export is not available yet; use SF2 sources",
                )
            )
            return
        path, _ = QFileDialog.getSaveFileName(
            self,
            self.text("บันทึกเป็น SF2 ใหม่", "Save as new SF2"),
            self.destination_name,
            "SoundFont (*.sf2)",
        )
        if not path:
            return
        if not Path(path).suffix:
            path += ".sf2"
        if Path(path).suffix.lower() != ".sf2":
            self.error("Choose an .sf2 file")
            return
        if str(Path(path).resolve()).casefold() in self.protected_paths():
            self.error(
                self.text(
                    "กรุณาเลือกชื่อใหม่ เพื่อเก็บไฟล์ต้นทางไว้",
                    "Choose a new filename to preserve the original SoundFont",
                )
            )
            return
        summary = self.text(
            f"บันทึก {len(self.entries)} เสียงเป็น SF2 ใหม่?\nเก็บ instrument/sample จากไฟล์ที่ใช้ทั้งหมด\nชื่อ SF2 ใช้ ASCII สูงสุด 19 ตัวอักษร",
            f"Save {len(self.entries)} presets as a new SF2?\nAll source instruments/samples are retained.\nSF2 names use up to 19 ASCII characters.",
        )
        if QMessageBox.question(self, "Save SF2", summary) != QMessageBox.Yes:
            return
        self.exporting = True
        self.set_busy()
        entries = [dict(e) for e in self.entries]
        self.statusBar().showMessage(self.text("กำลังบันทึก SF2…", "Writing SF2…"))

        def work():
            try:
                export_sf2(entries, path)
                self.signals.exported.emit(path, "")
            except Exception as exc:
                self.signals.exported.emit(path, str(exc))

        self.executor.submit(work)

    def export_done(self, path, error):
        self.exporting = False
        self.set_busy()
        if error:
            self.error(error)
            self.statusBar().showMessage(self.text("บันทึกไม่สำเร็จ", "Export failed"))
        else:
            self.destination_name = Path(path).name
            self.dirty = False
            self.refresh_destination()
            self.update_title()
            self.statusBar().showMessage(self.text("บันทึกแล้ว: ", "Saved: ") + path)

    def stop_sound(self):
        if self.player.synth:
            self.player.synth.all_sounds_off(0)

    def preview(self):
        if self.active:
            self.note_on(60)
            QTimer.singleShot(600, lambda: self.player.off(60))

    def note_on(self, n, velocity=None):
        if not self.active:
            return
        try:
            e = self.active
            bank = e.get("source_bank", e["bank"])
            program = e.get("source_program", e["program"])
            self.player.select(e["path"], bank, program, drums=bank == 128)
            if velocity is None:
                self.player.on(n)
            else:
                self.player.synth.noteon(self.player.channel, n, velocity)
        except Exception as exc:
            self.error(
                self.text("ไม่สามารถเล่นเสียง: ", "Audio unavailable: ") + str(exc)
            )

    def volume(self, v):
        self.player.volume = v * 127 // 100
        if self.player.synth:
            self.player.synth.cc(self.player.channel, 7, self.player.volume)

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
        if not self.midiport:
            return
        try:
            for msg in self.midiport.iter_pending():
                if msg.type == "note_on" and msg.velocity:
                    self.note_on(msg.note, msg.velocity)
                elif msg.type in ("note_off", "note_on"):
                    self.player.off(msg.note)
                elif msg.type == "control_change" and self.player.synth:
                    self.player.synth.cc(self.player.channel, msg.control, msg.value)
        except Exception as exc:
            self.midiport.close()
            self.midiport = None
            self.statusBar().showMessage(str(exc))

    def keyPressEvent(self, event):
        keys = "awsedftgyhujkolp"
        if (
            not event.isAutoRepeat()
            and event.text()
            and event.text() in keys
            and not isinstance(self.focusWidget(), (QLineEdit, QSpinBox, QComboBox))
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
        if self.busy() or self.pending:
            self.error(
                self.text(
                    "กรุณารอให้อ่าน/บันทึกไฟล์เสร็จก่อน",
                    "Wait for file operations to finish",
                )
            )
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
    window = Window()
    screen = app.primaryScreen()
    if screen:
        available = screen.availableGeometry()
        window.resize(
            min(1500, available.width() - 32), min(940, available.height() - 40)
        )
        if available.height() < 850:
            window.piano_toggle.setChecked(False)
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
