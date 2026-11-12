"""Local export diagnostics. Metadata only: never includes sample audio."""

import base64
import platform
import traceback
from pathlib import Path
from .soundfont import SoundFont

VERSION = "0.2.4"


def export_report(entries, destination, exception):
    sources = []
    paths = {}
    selected = []
    for entry in entries:
        path = str(Path(entry["path"]).resolve())
        if path not in paths:
            ident = f"source-{len(paths)+1}"
            paths[path] = ident
            record = {"id": ident, "filename": Path(path).name}
            try:
                font = SoundFont(path)
                record.update(
                    file_size=font.signature[0],
                    major_version=font.major,
                    sample_bytes=len(font.samples),
                    sm24_bytes=len(font.sm24) if font.sm24 is not None else None,
                    pdta={
                        key.decode("ascii"): base64.b64encode(value).decode("ascii")
                        for key, value in font.tables.items()
                    },
                )
            except Exception as error:
                record["metadata_error"] = f"{type(error).__name__}: {error}"
            sources.append(record)
        selected.append(
            {key: entry[key] for key in ("index", "name", "bank", "program")}
            | {"source": paths[path]}
        )
    return {
        "format": "soundfont-edit-export-error-v1",
        "app_version": VERSION,
        "system": platform.platform(),
        "destination": Path(destination).name,
        "error_type": type(exception).__name__,
        "error": str(exception) or repr(exception),
        "traceback": "".join(
            traceback.format_exception(
                type(exception), exception, exception.__traceback__
            )
        ),
        "sources": sources,
        "entries": selected,
        "contains_sample_audio": False,
    }
