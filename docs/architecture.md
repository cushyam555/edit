# Architecture

- `soundfont_edit/app.py`: PySide6 desktop UI, background work, project JSON,
  MIDI polling and FluidSynth playback. Library scans and exports share one worker
  to keep large file operations off the GUI thread.
- `soundfont_edit/soundfont.py`: bounded RIFF chunk iteration, SoundFont preset
  metadata, SF2 merge/export. Preset bags are copied selectively; complete source
  instrument/sample pools are copied once per source and references are rebased.
  Outputs are written beside the destination, reopened for structural checking,
  then atomically replaced. Input SoundFonts are never opened for writing.
- `soundfont_edit/cache.py`: SQLite metadata cache, invalidated by size and
  nanosecond mtime; sample PCM is not stored in the database.
- `soundfont_edit/piano.py`: two-octave keyboard with independent note on/off.
- `tests`: synthetic RIFF fixtures, reference/PCM checks across merged sources,
  independent FluidSynth loading, cache invalidation, and Qt project workflows.

## Project v1

UTF-8 JSON, extension `.sfedit`:

```json
{
  "version": 1,
  "entries": [
    {"path": "Piano.sf2", "index": 0, "name": "My Piano", "bank": 0,
     "program": 0, "source_bank": 0, "source_program": 0}
  ]
}
```

`index` is the original preset's index in `phdr`; the project must retain the
same source bank file. `source_bank` / `source_program` preserve preview routing
when the output assignment changes. Relative paths resolve against the project
folder; cross-drive Windows paths are absolute.

Library metadata is stored under Qt's per-user AppDataLocation in `library.json`
and `presets.sqlite3`. These files contain local paths, tags and favorites; they
are never sent to a server. The app performs no network requests.

## Next phase

Sample dependency pruning and deduplication, compressed SF3 decoding/export,
full localization, undo/redo, and advanced sample/loop/envelope/filter editing.
