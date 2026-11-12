"""Persist metadata only; sound samples stay in their source files."""

from contextlib import closing
import json
import sqlite3
from pathlib import Path
from .soundfont import SoundFont


def read_presets(path, cache_path):
    source = Path(path)
    stat = source.stat()
    with closing(sqlite3.connect(cache_path)) as db, db:
        db.execute(
            "CREATE TABLE IF NOT EXISTS presets (path TEXT PRIMARY KEY, size INTEGER, mtime INTEGER, data TEXT)"
        )
        cached = db.execute(
            "SELECT size,mtime,data FROM presets WHERE path=?", (str(source),)
        ).fetchone()
        if cached and cached[:2] == (stat.st_size, stat.st_mtime_ns):
            return json.loads(cached[2])
        sf = SoundFont(source)
        entries = [
            dict(
                path=str(source),
                index=p.index,
                name=p.name,
                bank=p.bank,
                program=p.program,
            )
            for p in sf.presets
        ]
        db.execute(
            "INSERT OR REPLACE INTO presets VALUES (?,?,?,?)",
            (str(source), stat.st_size, stat.st_mtime_ns, json.dumps(entries)),
        )
        return entries
