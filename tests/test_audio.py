import os
import sys
import tempfile
import unittest
from pathlib import Path
from test_soundfont import fixture
from soundfont_edit.soundfont import export_sf2


class AudioTests(unittest.TestCase):
    def test_export_loads_in_independent_synth(self):
        dll = Path("vendor").resolve()
        handle = None
        if sys.platform == "win32" and dll.exists():
            handle = os.add_dll_directory(str(dll))
            os.environ["PATH"] = str(dll) + os.pathsep + os.environ.get("PATH", "")
        try:
            import fluidsynth
        except (ImportError, OSError) as exc:
            self.skipTest(f"FluidSynth runtime unavailable: {exc}")
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
