import tempfile
import unittest
import struct
from pathlib import Path
from soundfont_edit.soundfont import SoundFont, export_sf2, chunk, name


def fixture(path, title="Piano", sample=100):
    tables = {
        b"phdr": name(title)
        + struct.pack("<HHHIII", 0, 0, 0, 0, 0, 0)
        + name("EOP")
        + struct.pack("<HHHIII", 0, 0, 1, 0, 0, 0),
        b"pbag": struct.pack("<HHHH", 0, 0, 1, 0),
        b"pmod": bytes(10),
        b"pgen": struct.pack("<HHHH", 41, 0, 0, 0),
        b"inst": name("Instrument")
        + struct.pack("<H", 0)
        + name("EOI")
        + struct.pack("<H", 1),
        b"ibag": struct.pack("<HHHH", 0, 0, 1, 0),
        b"imod": bytes(10),
        b"igen": struct.pack("<HHHH", 53, 0, 0, 0),
        b"shdr": name("Sample")
        + struct.pack("<IIIIIBbHH", 0, 8, 1, 7, 44100, 60, 0, 0, 1)
        + name("EOS")
        + bytes(26),
    }
    body = (
        b"sfbk"
        + chunk(b"LIST", b"INFO" + chunk(b"ifil", struct.pack("<HH", 2, 1)))
        + chunk(
            b"LIST",
            b"sdta" + chunk(b"smpl", struct.pack("<8h", *([sample] * 8)) + bytes(92)),
        )
        + chunk(b"LIST", b"pdta" + b"".join(chunk(k, v) for k, v in tables.items()))
    )
    path.write_bytes(chunk(b"RIFF", body))


class Tests(unittest.TestCase):
    def test_merge_references_and_pcm(self):
        with tempfile.TemporaryDirectory() as d:
            a, b, out = [Path(d) / n for n in ["a.sf2", "b.sf2", "out.sf2"]]
            fixture(a)
            fixture(b, "Strings", 200)
            entries = [
                dict(path=str(p), index=0, name=n, bank=0, program=i)
                for i, (p, n) in enumerate([(a, "Edited Piano"), (b, "Strings")])
            ]
            export_sf2(entries, out)
            sf = SoundFont(out)
            self.assertEqual([p.name for p in sf.presets], ["Edited Piano", "Strings"])
            self.assertEqual(struct.unpack_from("<HH", sf.tables[b"pgen"], 4), (41, 1))
            self.assertEqual(struct.unpack_from("<HH", sf.tables[b"igen"], 4), (53, 1))
            self.assertEqual(
                struct.unpack_from("<I", sf.tables[b"shdr"], 46 + 20)[0], 54
            )
            self.assertEqual(sf.samples[:16], struct.pack("<8h", *([100] * 8)))
            self.assertEqual(sf.samples[108:124], struct.pack("<8h", *([200] * 8)))
            roundtrip = Path(d) / "roundtrip.sf2"
            export_sf2(
                [dict(path=str(out), index=1, name="Again", bank=3, program=4)],
                roundtrip,
            )
            p = SoundFont(roundtrip).presets[0]
            self.assertEqual((p.name, p.bank, p.program), ("Again", 3, 4))

    def test_guards(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "a.sf2"
            fixture(p)
            original = p.read_bytes()
            e = dict(path=str(p), index=0, name="A", bank=0, program=0)
            with self.assertRaises(ValueError):
                export_sf2([e], p)
            self.assertEqual(p.read_bytes(), original)
            with self.assertRaises(ValueError):
                export_sf2([e, e], Path(d) / "out.sf2")
            p.write_bytes(b"not soundfont")
            with self.assertRaises(ValueError):
                SoundFont(p)

    def test_sf3_rejected_for_export(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "a.sf3"
            fixture(p)
            with self.assertRaisesRegex(ValueError, "SF3"):
                export_sf2(
                    [dict(path=str(p), index=0, name="A", bank=0, program=0)],
                    Path(d) / "out.sf2",
                )


if __name__ == "__main__":
    unittest.main()
