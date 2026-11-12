"""Regression coverage for unused PCM, shared samples, stereo and address offsets."""

import struct
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from soundfont_edit.soundfont import SoundFont, SampleData, export_sf2, chunk, name


def bank(path, presets, instruments, samples, pcm):
    tables = {}
    for preset, headers in [(True, presets), (False, instruments)]:
        hdr, bag, gen, mod = (
            (b"phdr", b"pbag", b"pgen", b"pmod")
            if preset
            else (b"inst", b"ibag", b"igen", b"imod")
        )
        tables[hdr] = bytearray()
        tables[bag] = bytearray()
        tables[gen] = bytearray()
        tables[mod] = bytearray()
        for index, zones in enumerate(headers):
            header = name(("Preset" if preset else "Instrument") + str(index))
            header += (
                struct.pack("<HHHIII", index, 0, len(tables[bag]) // 4, 0, 0, 0)
                if preset
                else struct.pack("<H", len(tables[bag]) // 4)
            )
            tables[hdr] += header
            for generators, modulators in zones:
                tables[bag] += struct.pack(
                    "<HH", len(tables[gen]) // 4, len(tables[mod]) // 10
                )
                tables[gen] += b"".join(
                    struct.pack("<HH", op, value & 65535) for op, value in generators
                )
                tables[mod] += modulators
        tables[hdr] += name("EOP" if preset else "EOI") + (
            struct.pack("<HHHIII", 0, 0, len(tables[bag]) // 4, 0, 0, 0)
            if preset
            else struct.pack("<H", len(tables[bag]) // 4)
        )
        tables[bag] += struct.pack("<HH", len(tables[gen]) // 4, len(tables[mod]) // 10)
        tables[gen] += bytes(4)
        tables[mod] += bytes(10)
    tables[b"shdr"] = (
        b"".join(
            name(s.get("name", f"Sample{i}"))
            + struct.pack(
                "<IIIIIBbHH",
                s["start"],
                s["end"],
                s.get("loop_start", s["start"] + 1),
                s.get("loop_end", s["end"] - 1),
                44100,
                60,
                0,
                s.get("link", 0),
                s.get("type", 1),
            )
            for i, s in enumerate(samples)
        )
        + name("EOS")
        + bytes(26)
    )
    keys = [
        b"phdr",
        b"pbag",
        b"pmod",
        b"pgen",
        b"inst",
        b"ibag",
        b"imod",
        b"igen",
        b"shdr",
    ]
    body = (
        b"sfbk"
        + chunk(b"LIST", b"INFO" + chunk(b"ifil", struct.pack("<HH", 2, 1)))
        + chunk(b"LIST", b"sdta" + chunk(b"smpl", pcm))
        + chunk(b"LIST", b"pdta" + b"".join(chunk(k, tables[k]) for k in keys))
    )
    path.write_bytes(chunk(b"RIFF", body))


def zone(*generators, mods=b""):
    return list(generators), mods


def entry(path, index, program=0):
    return dict(
        path=str(path), index=index, name=f"Chosen{index}", bank=0, program=program
    )


class PruningTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.folder = Path(self.temp.name)
        self.source = self.folder / "source.sf2"
        self.output = self.folder / "output.sf2"

    def tearDown(self):
        self.temp.cleanup()

    def rich_bank(self):
        junk = bytes(1024 * 1024)
        used = struct.pack("<64h", *range(64))
        left = struct.pack("<64h", *range(100, 164))
        right = struct.pack("<64h", *range(200, 264))
        guard = bytes(92)
        pcm = junk + used + guard + left + guard + right + guard
        base = len(junk) // 2
        samples = [
            dict(start=0, end=base - 46),
            dict(start=base, end=base + 64),
            dict(start=base + 110, end=base + 174, type=4, link=3),
            dict(start=base + 220, end=base + 284, type=2, link=2),
        ]
        pmod = struct.pack("<HHhHH", 0, 48, 10, 0, 0)
        imod = struct.pack("<HHhHH", 0, 17, 20, 0, 0)
        presets = [
            [zone((41, 0))],
            [zone((17, 100), mods=pmod), zone((41, 1))],
            [zone((41, 1))],
            [zone((41, 2))],
        ]
        instruments = [
            [zone((53, 0))],
            [zone((54, 1), mods=imod), zone((53, 1))],
            [zone((53, 3))],
        ]
        bank(self.source, presets, instruments, samples, pcm)
        return used, left, right, pmod, imod

    def test_prunes_unreachable_data_and_keeps_global_zones_and_modulators(self):
        used, _, _, pmod, imod = self.rich_bank()
        stats = export_sf2([entry(self.source, 1)], self.output)
        font = SoundFont(self.output)
        self.assertLess(self.output.stat().st_size, 2000)
        self.assertGreater(self.source.stat().st_size, 1000000)
        self.assertEqual((stats["instruments"], stats["samples"]), (1, 1))
        self.assertEqual(font.samples[:128], used)
        self.assertEqual(
            list(struct.iter_unpack("<HH", font.tables[b"pgen"]))[:-1],
            [(17, 100), (41, 0)],
        )
        self.assertEqual(
            list(struct.iter_unpack("<HH", font.tables[b"igen"]))[:-1],
            [(54, 1), (53, 0)],
        )
        self.assertEqual(font.tables[b"pmod"][:-10], pmod)
        self.assertEqual(font.tables[b"imod"][:-10], imod)
        self.assertEqual(
            struct.unpack_from("<IIII", font.tables[b"shdr"], 20), (0, 64, 1, 63)
        )

    def test_shared_instrument_and_sample_copied_once(self):
        self.rich_bank()
        export_sf2([entry(self.source, 1), entry(self.source, 2, 1)], self.output)
        font = SoundFont(self.output)
        self.assertEqual(len(font.presets), 2)
        self.assertEqual(len(font.records(b"inst", 22)), 2)
        self.assertEqual(len(font.records(b"shdr", 46)), 2)
        self.assertEqual(len(font.samples), 220)

    def test_stereo_partner_and_links_survive_pruning(self):
        _, left, right, _, _ = self.rich_bank()
        stats = export_sf2([entry(self.source, 3)], self.output)
        font = SoundFont(self.output)
        self.assertEqual(stats["samples"], 2)
        headers = font.records(b"shdr", 46)
        self.assertEqual(struct.unpack_from("<HH", headers[0], 42), (1, 4))
        self.assertEqual(struct.unpack_from("<HH", headers[1], 42), (0, 2))
        self.assertEqual(
            list(struct.iter_unpack("<HH", font.tables[b"igen"]))[:-1], [(53, 1)]
        )
        self.assertEqual(font.samples[:128], left)
        self.assertEqual(font.samples[220:348], right)

    def test_signed_offsets_and_global_local_override_preserve_pcm(self):
        pcm = struct.pack("<200h", *range(200))
        bank(
            self.source,
            [[zone((41, 0))]],
            [[zone((0, -3), (1, 2), (54, 1)), zone((0, -2), (53, 0))]],
            [dict(start=100, end=110)],
            pcm,
        )
        export_sf2([entry(self.source, 0)], self.output)
        font = SoundFont(self.output)
        self.assertEqual(font.samples[:28], pcm[196:224])
        self.assertEqual(
            struct.unpack_from("<IIII", font.tables[b"shdr"], 20), (2, 12, 3, 11)
        )
        self.assertEqual(
            list(struct.iter_unpack("<HH", font.tables[b"igen"]))[:-1],
            [(0, 65533), (1, 2), (54, 1), (0, 65534), (53, 0)],
        )

    def test_coarse_offsets_preserve_access_before_nominal_start(self):
        pcm = bytes(70000)
        bank(
            self.source,
            [[zone((41, 0))]],
            [[zone((4, -1), (53, 0))]],
            [dict(start=33000, end=33100)],
            pcm,
        )
        export_sf2([entry(self.source, 0)], self.output)
        font = SoundFont(self.output)
        self.assertEqual(struct.unpack_from("<I", font.tables[b"shdr"], 20)[0], 32768)
        self.assertEqual(len(font.samples), (33100 - 232 + 46) * 2)

    def test_inactive_zero_loops_do_not_keep_preceding_unused_audio(self):
        bank(
            self.source,
            [[zone((41, 0))]],
            [[zone((53, 0))]],
            [dict(start=10000, end=10010, loop_start=0, loop_end=0)],
            bytes(20200),
        )
        export_sf2([entry(self.source, 0)], self.output)
        font = SoundFont(self.output)
        self.assertEqual(len(font.samples), 112)
        self.assertLess(self.output.stat().st_size, 1000)

    def test_bad_reference_does_not_replace_existing_destination(self):
        bank(
            self.source,
            [[zone((41, 0))]],
            [[zone((53, 5))]],
            [dict(start=0, end=10)],
            bytes(112),
        )
        self.output.write_bytes(b"previous output")
        with self.assertRaisesRegex(ValueError, "sample reference"):
            export_sf2([entry(self.source, 0)], self.output)
        self.assertEqual(self.output.read_bytes(), b"previous output")
        self.assertEqual(list(self.folder.glob("*.tmp")), [])

    def broken_pair(
        self, valid=False, ambiguous=False, partner_link=None, mismatch=False
    ):
        pcm = struct.pack("<440h", *range(440))
        samples = [
            dict(name="Unused", start=0, end=64),
            dict(
                name="Note_A_(R", start=110, end=174, link=3 if valid else 2025, type=4
            ),
            dict(name="Other", start=220, end=284),
            dict(
                name="Note_A_(L", start=330, end=394, link=1 if valid else 2025, type=2
            ),
        ]
        if partner_link is not None:
            samples[3]["link"] = partner_link
        if mismatch:
            samples[3]["end"] += 1
        if ambiguous:
            samples.append(dict(samples[3]))
        bank(self.source, [[zone((41, 0))]], [[zone((53, 1))]], samples, pcm)

    def test_repairs_only_unique_matching_stereo_links(self):
        self.broken_pair()
        before = self.source.read_bytes()
        stats = export_sf2([entry(self.source, 0)], self.output)
        font = SoundFont(self.output)
        self.assertEqual(len(stats["stereo_link_repairs"]), 1)
        self.assertEqual(stats["stereo_link_repairs"][0]["sample_ids"], [1, 3])
        records = font.records(b"shdr", 46)
        self.assertEqual(struct.unpack_from("<HH", records[0], 42), (1, 4))
        self.assertEqual(struct.unpack_from("<HH", records[1], 42), (0, 2))
        self.assertEqual(self.source.read_bytes(), before)
        repaired = self.output.read_bytes()
        self.broken_pair(valid=True)
        reference = self.folder / "reference.sf2"
        stats = export_sf2([entry(self.source, 0)], reference)
        self.assertEqual(stats["stereo_link_repairs"], [])
        self.assertEqual(repaired, reference.read_bytes())

    def test_stereo_repair_requires_matching_geometry_and_no_existing_partner(self):
        for options in ({"partner_link": 0}, {"mismatch": True}):
            with self.subTest(options=options):
                self.broken_pair(**options)
                with self.assertRaisesRegex(
                    ValueError, "no unique matching L/R partner"
                ):
                    export_sf2([entry(self.source, 0)], self.output)
                self.assertFalse(self.output.exists())

    def test_ambiguous_stereo_partner_is_not_guessed(self):
        self.broken_pair(ambiguous=True)
        self.output.write_bytes(b"keep previous")
        with self.assertRaisesRegex(ValueError, "no unique matching L/R partner"):
            export_sf2([entry(self.source, 0)], self.output)
        self.assertEqual(self.output.read_bytes(), b"keep previous")

    def test_large_unused_pcm_is_not_loaded_or_copied(self):
        bank(
            self.source,
            [[zone((41, 0))]],
            [[zone((53, 0))]],
            [dict(start=0, end=8)],
            bytes(108),
        )
        original = SoundFont(self.source)
        pdta = chunk(
            b"LIST", b"pdta" + b"".join(chunk(k, v) for k, v in original.tables.items())
        )
        info = chunk(b"LIST", b"INFO" + chunk(b"ifil", struct.pack("<HH", 2, 1)))
        pcm_size = 64 * 1024 * 1024
        body_size = 4 + len(info) + 20 + pcm_size + len(pdta)
        with self.source.open("wb") as stream:
            stream.write(
                b"RIFF"
                + struct.pack("<I", body_size)
                + b"sfbk"
                + info
                + b"LIST"
                + struct.pack("<I", 12 + pcm_size)
                + b"sdta"
                + b"smpl"
                + struct.pack("<I", pcm_size)
            )
            stream.seek(pcm_size, 1)
            stream.write(pdta)
        with patch.object(
            Path,
            "read_bytes",
            side_effect=AssertionError("Do not read entire bank into memory"),
        ):
            font = SoundFont(self.source)
            self.assertIsInstance(font.samples, SampleData)
            export_sf2([entry(self.source, 0)], self.output)
        self.assertLess(self.output.stat().st_size, 1000)
