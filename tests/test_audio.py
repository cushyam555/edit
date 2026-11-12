import os
import sys
import tempfile
import unittest
from pathlib import Path
from test_soundfont import fixture
from soundfont_edit.soundfont import export_sf2


def runtime(case):
    dll = Path("vendor").resolve()
    if sys.platform == "win32" and dll.exists():
        case.dll_handle = os.add_dll_directory(str(dll))
        os.environ["PATH"] = str(dll) + os.pathsep + os.environ.get("PATH", "")
    try:
        import fluidsynth

        return fluidsynth
    except (ImportError, OSError) as exc:
        case.skipTest(f"FluidSynth runtime unavailable: {exc}")


class AudioTests(unittest.TestCase):
    def test_export_loads_in_independent_synth(self):
        fluidsynth = runtime(self)
        with tempfile.TemporaryDirectory() as tmp:
            a, b, out = [Path(tmp) / n for n in ["a.sf2", "b.sf2", "out.sf2"]]
            fixture(a)
            fixture(b, "Strings", 300)
            export_sf2(
                [
                    dict(path=str(a), index=0, name="A", bank=0, program=2),
                    dict(path=str(b), index=0, name="B", bank=1, program=3),
                ],
                out,
            )
            synth = fluidsynth.Synth()
            try:
                ident = synth.sfload(str(out))
                self.assertGreaterEqual(ident, 0)
                for bank, program in [(0, 2), (1, 3)]:
                    self.assertEqual(synth.program_select(0, ident, bank, program), 0)
                    synth.noteon(0, 60, 100)
                    self.assertEqual(len(synth.get_samples(1024)), 2048)
                    synth.noteoff(0, 60)
            finally:
                synth.delete()

    def test_reversed_zone_preserves_render_of_remaining_voices(self):
        from test_pruning import bank, zone, entry
        import math, struct
        import numpy as np

        fluidsynth = runtime(self)
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "original.sf2"
            output = Path(tmp) / "export.sf2"
            values = (
                [int(15000 * math.sin(i * 0.1)) for i in range(2048)]
                + [0] * 152
                + [int(7000 * math.sin(i * 0.2)) for i in range(100)]
                + [0] * 3700
            )
            pcm = struct.pack(f"<{len(values)}h", *values)
            bank(
                source,
                [[zone((41, 0))]],
                [[zone((54, 1)), zone((53, 0)), zone((0, 500), (53, 1))]],
                [dict(start=0, end=2048), dict(start=2200, end=2300)],
                pcm,
            )
            stats = export_sf2([entry(source, 0)], output)
            self.assertEqual(len(stats["source_zone_warnings"]), 1)
            rendered = []
            for path in [source, output]:
                synth = fluidsynth.Synth(samplerate=44100)
                synth.setting("synth.reverb.active", 0)
                synth.setting("synth.chorus.active", 0)
                try:
                    ident = synth.sfload(str(path))
                    self.assertGreaterEqual(ident, 0)
                    self.assertEqual(synth.program_select(0, ident, 0, 0), 0)
                    synth.noteon(0, 60, 100)
                    rendered.append(synth.get_samples(8192).astype(np.int32))
                finally:
                    synth.delete()
            self.assertGreater(np.max(np.abs(rendered[0])), 10)
            self.assertLessEqual(np.max(np.abs(rendered[0] - rendered[1])), 2)
