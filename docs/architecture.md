# Architecture

- `soundfont_edit/app.py`: two-pane PySide6 UI, asynchronous file loading,
  project JSON, MIDI polling and conflict dialogs. Library scans and exports share one worker
  to keep large file operations off the GUI thread.
- `soundfont_edit/soundfont.py`: bounded RIFF chunk iteration, SoundFont preset
  metadata, dependency-pruned SF2 merge/export. Traverse selected preset zones to
  instruments and samples, close stereo links, retain global zones/modulators,
  and preserve signed fine/coarse address offsets. Copy only referenced PCM
  intervals with guard points, remapping sample IDs, instrument IDs and addresses.
  Metadata reads seek past PCM; final writes stream 1 MiB blocks from each source.
  Shared headers and overlapping audio ranges within a source are emitted once.
  Source size/mtime are checked before and after copying. Out-of-range stereo
  links may be repaired only when complementary L/R names and types, length,
  relative loops, rate and pitch uniquely agree in both directions. Existing
  valid partners are never detached. Repairs are returned as export statistics
  and disclosed by an inline success notice; ambiguous links remain errors.
  Reversed effective spans already present in a source zone are preserved with
  an explicit warning if all addressed points exist in PCM. Negative/out-of-file
  addresses remain hard errors. This preserves player behavior rather than
  guessing a correction or dropping a source voice.
  Outputs are written beside the destination, reopened for structural checking,
  then atomically replaced. Input SoundFonts are never opened for writing.
- `soundfont_edit/preset_tree.py`: numeric tree ordering, display-only GM numbering,
  multi-selection and window-local copy-only drag/drop. Leaf identifiers map back
  to canonical entries rather than editable QVariant copies. Destination inline
  editors use a delegate with validated numeric ranges and numbering conversion.
  Document changes commit synchronously; tree rebuilds wait until Qt closes the
  editor. Save explicitly finishes a focused edit before taking its snapshot.
  GM reference cells stay read-only and support clipboard copying.
- `soundfont_edit/soundset.py`: immutable merge planning, collision replacement or
  remapping, atomic batch cancellation, and source preview address preservation.
- `soundfont_edit/gm.py`: 128 standard GM program references. Bank 128 is the
  SoundFont percussion bank; custom kit names remain unchanged.
- `soundfont_edit/audio.py`: FluidSynth lifecycle and channel 10 percussion preview.
- `soundfont_edit/diagnostics.py`: local failure reports with traceback and base64
  PDTA metadata, source sizes and chosen entries. No PCM/sm24 audio is included.
  Export failures render inline and remain copyable independently of modal dialogs.
- `soundfont_edit/cache.py`: SQLite metadata cache, invalidated by size and
  nanosecond mtime; sample PCM is not stored in the database.
- `soundfont_edit/piano.py`: two-octave keyboard with independent note on/off.
- `tests`: synthetic RIFF fixtures, reference/PCM checks across merged sources,
  independent FluidSynth loading, cache invalidation, and Qt project workflows.

## Project v2 (reads v1 too)

UTF-8 JSON, extension `.sfedit`:

```json
{
  "version": 2,
  "destination_name": "My Band.sf2",
  "destination_path": null,
  "sources": ["Piano.sf2"],
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

Cross-file content deduplication, compressed SF3 decoding/export,
remaining localization, undo/redo, and advanced sample/loop/envelope/filter editing.
