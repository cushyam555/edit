"""Sorted preset trees with window-local, copy-only source drag and drop."""

import json
from PySide6.QtCore import (
    Qt,
    Signal,
    QMimeData,
    QPersistentModelIndex,
    QModelIndex,
    QEvent,
)
from PySide6.QtGui import QDrag, QKeySequence
from PySide6.QtWidgets import (
    QTreeWidget,
    QTreeWidgetItem,
    QHeaderView,
    QAbstractItemView,
    QStyledItemDelegate,
    QAbstractItemDelegate,
    QSpinBox,
    QLineEdit,
    QApplication,
)
from shiboken6 import isValid
from .gm import reference
from .soundset import ordered

MIME = "application/x-soundfont-edit-presets"
ROLE = Qt.ItemDataRole.UserRole


class PresetDelegate(QStyledItemDelegate):
    """Commit document edits without mutating the temporary Qt item model."""

    def createEditor(self, parent, option, index):
        tree = self.parent()
        entry = tree.entry_map.get(index.siblingAtColumn(0).data(ROLE))
        if not tree.destination or entry is None or index.column() not in (0, 1, 2):
            return None
        if index.column() == 1:
            editor = QLineEdit(parent)
        else:
            editor = QSpinBox(parent)
            offset = int(tree.gm_numbers) if index.column() == 0 else 0
            editor.setProperty("numbering_offset", offset)
            (
                editor.setRange(offset, 127 + offset)
                if index.column() == 0
                else editor.setRange(0, 128)
            )
        tree.inline_editor = editor
        tree.inline_index = QPersistentModelIndex(index)
        return editor

    def eventFilter(self, editor, event):
        if (
            editor is self.parent().inline_editor
            and event.type() == QEvent.KeyPress
            and event.key() in (Qt.Key_Return, Qt.Key_Enter)
        ):
            self.commitData.emit(editor)
            self.closeEditor.emit(editor, QAbstractItemDelegate.NoHint)
            return True
        return super().eventFilter(editor, event)

    def setEditorData(self, editor, index):
        entry = self.parent().entry_map[index.siblingAtColumn(0).data(ROLE)]
        if isinstance(editor, QLineEdit):
            editor.setText(entry["name"])
            editor.selectAll()
        else:
            value = entry["program"] if index.column() == 0 else entry["bank"]
            editor.setValue(value + (editor.property("numbering_offset") or 0))
            editor.selectAll()

    def setModelData(self, editor, model, index):
        if self.parent().inline_editor is not editor:
            return
        key = index.siblingAtColumn(0).data(ROLE)
        if isinstance(editor, QLineEdit):
            value = editor.text()
        else:
            editor.interpretText()
            value = editor.value() - (editor.property("numbering_offset") or 0)
        # Document updates synchronously, so a subsequent Save sees this value.
        # Window defers only the tree rebuild until Qt releases its editor.
        self.parent().edited.emit(key, index.column(), value)


class PresetTree(QTreeWidget):
    dropped = Signal(object)
    edited = Signal(str, int, object)

    def __init__(self, token, destination=False):
        super().__init__()
        self.token = token
        self.destination = destination
        self.gm_numbers = False
        self.inline_editor = None
        self.inline_index = QPersistentModelIndex()
        self.gm_column = 3 if destination else 2
        self.rows = []
        self.entry_map = {}
        self.setColumnCount(4 if destination else 3)
        self.setEditTriggers(
            (
                QAbstractItemView.DoubleClicked
                | QAbstractItemView.EditKeyPressed
                | QAbstractItemView.SelectedClicked
            )
            if destination
            else QAbstractItemView.NoEditTriggers
        )
        self.setItemDelegate(PresetDelegate(self))
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.setUniformRowHeights(True)
        self.setAlternatingRowColors(True)
        self.setRootIsDecorated(True)
        self.setIndentation(18)
        self.setDragEnabled(not destination)
        self.setAcceptDrops(destination)
        self.setDropIndicatorShown(destination)
        self.setDragDropMode(
            QAbstractItemView.DropOnly if destination else QAbstractItemView.DragOnly
        )
        self.setDefaultDropAction(Qt.CopyAction)
        self.header().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.header().setSectionResizeMode(1, QHeaderView.Stretch)
        self.header().setSectionResizeMode(self.gm_column, QHeaderView.Stretch)
        if destination:
            self.header().setSectionResizeMode(2, QHeaderView.ResizeToContents)

    def populate(self, entries, query="", gm_numbers=False, thai=True):
        selected = {
            e.get("_uid", (e["path"], e["index"])) for e in self.selected_entries()
        }
        self.gm_numbers = gm_numbers
        self.blockSignals(True)
        self.clear()
        self.rows = []
        self.entry_map = {}
        self.setHeaderLabels(
            [
                "GM# (1–128)" if gm_numbers else "ID (0–127)",
                "ชื่อ preset" if thai else "Preset name",
                *(["Bank"] if self.destination else []),
                "GM reference",
            ]
        )
        roots = {}
        banks = {}
        terms = query.casefold().split()
        for entry in ordered(entries):
            hay = f"{entry['name']} {entry.get('_tags','')} {reference(entry)} {entry['path']} bank:{entry['bank']} id:{entry['program']} program:{entry['program']}".casefold()

            def matches(term):
                for prefix, key in [
                    ("bank:", "bank"),
                    ("id:", "program"),
                    ("program:", "program"),
                ]:
                    if term.startswith(prefix):
                        return term[len(prefix) :] == str(entry[key])
                return term in hay

            if not all(matches(t) for t in terms):
                continue
            drum = entry["bank"] == 128
            if drum not in roots:
                root = QTreeWidgetItem(
                    self, ["ชุดกลอง / Percussion" if drum else "เครื่องดนตรี / Melodic"]
                )
                root.setFlags(Qt.ItemIsEnabled)
                root.setFirstColumnSpanned(True)
                roots[drum] = root
            key = drum, entry["bank"]
            if key not in banks:
                bank = QTreeWidgetItem(roots[drum], [f"Bank {entry['bank']}"])
                bank.setFlags(Qt.ItemIsEnabled)
                bank.setFirstColumnSpanned(True)
                banks[key] = bank
            item = QTreeWidgetItem(
                banks[key],
                [
                    f"{entry['program'] + int(gm_numbers):03d}",
                    ("★ " if entry.get("_favorite") else "") + entry["name"],
                    *([str(entry["bank"])] if self.destination else []),
                    reference(entry),
                ],
            )
            entry_key = entry.get("_uid") or f"{entry['path']}|{entry['index']}"
            self.entry_map[entry_key] = entry
            item.setData(0, ROLE, entry_key)
            item.setToolTip(
                1,
                f"{entry['path']}\nBank {entry['bank']} · Preset ID {entry['program']}",
            )
            item.setToolTip(
                self.gm_column,
                "Ctrl+C: copy GM name. GM reference identifies the standard slot, not the actual sample sound.",
            )
            item.setFlags(
                Qt.ItemIsEnabled
                | Qt.ItemIsSelectable
                | (Qt.ItemIsEditable if self.destination else Qt.ItemIsDragEnabled)
            )
            if entry.get("_uid", (entry["path"], entry["index"])) in selected:
                item.setSelected(True)
            self.rows.append(item)
        self.expandAll()
        self.blockSignals(False)

    def selected_entries(self):
        return [
            self.entry_map[item.data(0, ROLE)]
            for item in self.selectedItems()
            if item.data(0, ROLE) in self.entry_map
        ]

    def finish_edit(self):
        """Commit a focused editor before actions such as Save take a snapshot."""
        editor = self.inline_editor
        if (
            self.state() != QAbstractItemView.EditingState
            or editor is None
            or not isValid(editor)
            or not self.inline_index.isValid()
        ):
            return
        self.itemDelegate().setModelData(
            editor, self.model(), QModelIndex(self.inline_index)
        )
        self.closeEditor(editor, QAbstractItemDelegate.NoHint)
        self.inline_editor = None

    def current_entry(self):
        item = self.currentItem()
        return self.entry_map.get(item.data(0, ROLE)) if item else None

    def copy_gm(self):
        entry = self.current_entry()
        if entry is None:
            selected = self.selected_entries()
            entry = selected[0] if selected else None
        if entry is not None:
            value = reference(entry)
            QApplication.clipboard().setText(value)

    def keyPressEvent(self, event):
        if event.matches(QKeySequence.Copy) and self.currentColumn() == self.gm_column:
            self.copy_gm()
            event.accept()
            return
        super().keyPressEvent(event)

    def startDrag(self, actions):
        entries = self.selected_entries()
        if not entries:
            return
        data = QMimeData()
        data.setData(
            MIME,
            json.dumps(
                {
                    "token": self.token,
                    "keys": [[e["path"], e["index"]] for e in entries],
                }
            ).encode(),
        )
        drag = QDrag(self)
        drag.setMimeData(data)
        drag.exec(Qt.CopyAction)

    def payload(self, mime):
        if not mime.hasFormat(MIME):
            return None
        try:
            data = json.loads(bytes(mime.data(MIME)))
            if data.get("token") == self.token and isinstance(data.get("keys"), list):
                return data["keys"]
        except (ValueError, TypeError, AttributeError):
            pass
        return None

    def dragEnterEvent(self, event):
        if (
            self.destination
            and self.isEnabled()
            and self.payload(event.mimeData()) is not None
        ):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        self.dragEnterEvent(event)

    def dropEvent(self, event):
        keys = self.payload(event.mimeData())
        if self.destination and self.isEnabled() and keys is not None:
            event.setDropAction(Qt.CopyAction)
            event.accept()
            self.dropped.emit(keys)
        else:
            event.ignore()
