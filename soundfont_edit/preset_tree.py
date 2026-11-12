"""Sorted preset trees with window-local, copy-only source drag and drop."""

import json
from PySide6.QtCore import Qt, Signal, QMimeData
from PySide6.QtGui import QDrag
from PySide6.QtWidgets import (
    QTreeWidget,
    QTreeWidgetItem,
    QHeaderView,
    QAbstractItemView,
)
from .gm import reference
from .soundset import ordered

MIME = "application/x-soundfont-edit-presets"
ROLE = Qt.ItemDataRole.UserRole


class PresetTree(QTreeWidget):
    dropped = Signal(object)

    def __init__(self, token, destination=False):
        super().__init__()
        self.token = token
        self.destination = destination
        self.rows = []
        self.entry_map = {}
        self.setColumnCount(3)
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
        self.header().setSectionResizeMode(2, QHeaderView.Stretch)

    def populate(self, entries, query="", gm_numbers=False, thai=True):
        selected = {
            e.get("_uid", (e["path"], e["index"])) for e in self.selected_entries()
        }
        self.blockSignals(True)
        self.clear()
        self.rows = []
        self.entry_map = {}
        self.setHeaderLabels(
            [
                "GM# (1–128)" if gm_numbers else "ID (0–127)",
                "ชื่อ preset" if thai else "Preset name",
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
                2,
                "GM reference identifies the standard slot, not the actual sample sound.",
            )
            item.setFlags(
                Qt.ItemIsEnabled
                | Qt.ItemIsSelectable
                | (Qt.NoItemFlags if self.destination else Qt.ItemIsDragEnabled)
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
