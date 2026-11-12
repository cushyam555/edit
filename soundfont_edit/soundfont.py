"""SoundFont metadata reader and dependency-pruned, streaming SF2 exporter."""

from dataclasses import dataclass
from pathlib import Path
import os
import struct
import tempfile
from bisect import bisect_right
from contextlib import nullcontext


def chunks(data, start=0, end=None):
    end = len(data) if end is None else end
    while start + 8 <= end:
        tag, size = struct.unpack_from("<4sI", data, start)
        stop = start + 8 + size
        if stop > end:
            raise ValueError("Truncated RIFF chunk")
        yield tag, data[start + 8 : stop]
        start = stop + (size & 1)
    if start != end:
        raise ValueError("Invalid RIFF padding")


def chunk(tag, data):
    return tag + struct.pack("<I", len(data)) + data + b"\0" * (len(data) & 1)


def name(value):
    return value.encode("ascii", "replace")[:19].ljust(20, b"\0")


def file_chunks(stream, start, end):
    while start + 8 <= end:
        stream.seek(start)
        header = stream.read(8)
        if len(header) != 8:
            raise ValueError("Truncated RIFF header")
        tag, size = struct.unpack("<4sI", header)
        stop = start + 8 + size
        if stop > end:
            raise ValueError("Truncated RIFF chunk")
        yield tag, start + 8, size
        start = stop + (size & 1)
    if start != end:
        raise ValueError("Invalid RIFF padding")


@dataclass
class SampleData:
    """File-backed sample chunk; metadata scans never read PCM into memory."""

    path: Path
    offset: int
    size: int

    def __len__(self):
        return self.size

    def __getitem__(self, key):
        if isinstance(key, slice):
            start, stop, step = key.indices(self.size)
            if step != 1:
                return bytes(self)[key]
            with self.path.open("rb") as stream:
                stream.seek(self.offset + start)
                data = stream.read(max(0, stop - start))
            if len(data) != max(0, stop - start):
                raise ValueError("Source sample data changed or was truncated")
            return data
        index = int(key)
        if index < 0:
            index += self.size
        if not 0 <= index < self.size:
            raise IndexError(index)
        return self[index : index + 1][0]

    def __bytes__(self):
        return self[:]

    def copy_to(self, output, start, stop, source=None):
        if not 0 <= start <= stop <= self.size:
            raise ValueError("Sample range is outside PCM data")
        with self.path.open("rb") if source is None else nullcontext(source) as source:
            source.seek(self.offset + start)
            remaining = stop - start
            while remaining:
                data = source.read(min(1024 * 1024, remaining))
                if not data:
                    raise ValueError("Source sample data changed or was truncated")
                output.write(data)
                remaining -= len(data)


@dataclass
class Preset:
    index: int
    name: str
    bank: int
    program: int


class SoundFont:
    def __init__(self, path):
        self.path = Path(path)
        self.tables = {}
        self.samples = b""
        self.sm24 = None
        self.major = 2
        stat = self.path.stat()
        self.signature = (stat.st_size, stat.st_mtime_ns)
        with self.path.open("rb") as stream:
            header = stream.read(12)
            if len(header) != 12 or header[:4] != b"RIFF" or header[8:12] != b"sfbk":
                raise ValueError("Not a SoundFont bank")
            if struct.unpack_from("<I", header, 4)[0] + 8 != stat.st_size:
                raise ValueError("Invalid RIFF length")
            for tag, offset, size in file_chunks(stream, 12, stat.st_size):
                if tag != b"LIST":
                    continue
                if size < 4:
                    raise ValueError("Invalid LIST chunk")
                stream.seek(offset)
                kind = stream.read(4)
                for key, position, length in file_chunks(
                    stream, offset + 4, offset + size
                ):
                    if kind == b"pdta":
                        stream.seek(position)
                        self.tables[key] = stream.read(length)
                        if len(self.tables[key]) != length:
                            raise ValueError("Truncated SoundFont table")
                    elif kind == b"sdta":
                        if key == b"smpl":
                            self.samples = SampleData(self.path, position, length)
                        if key == b"sm24":
                            self.sm24 = SampleData(self.path, position, length)
                    elif kind == b"INFO" and key == b"ifil":
                        if length < 4:
                            raise ValueError("Invalid SoundFont version")
                        stream.seek(position)
                        self.major = struct.unpack("<HH", stream.read(4))[0]
        for key, size in [
            (b"phdr", 38),
            (b"pbag", 4),
            (b"pmod", 10),
            (b"pgen", 4),
            (b"inst", 22),
            (b"ibag", 4),
            (b"imod", 10),
            (b"igen", 4),
            (b"shdr", 46),
        ]:
            if (
                key not in self.tables
                or not self.tables[key]
                or len(self.tables[key]) % size
            ):
                raise ValueError(f"Invalid SoundFont table: {key.decode()}")
        self.presets = [
            Preset(
                i,
                r[:20].split(b"\0")[0].decode("latin1"),
                *reversed(struct.unpack_from("<HH", r, 20)),
            )
            for i, r in enumerate(self.records(b"phdr", 38)[:-1])
        ]

    def records(self, key, size):
        value = self.tables[key]
        return [value[i : i + size] for i in range(0, len(value), size)]


class ExportPlan:
    def __init__(self, font, indices):
        self.font = font
        self.phdr = font.records(b"phdr", 38)
        self.inst = font.records(b"inst", 22)
        self.shdr = font.records(b"shdr", 46)
        self.pbag = font.records(b"pbag", 4)
        self.ibag = font.records(b"ibag", 4)
        self.pgen = list(struct.iter_unpack("<HH", font.tables[b"pgen"]))
        self.igen = list(struct.iter_unpack("<HH", font.tables[b"igen"]))
        self.pzones = {}
        self.izones = {}
        self.bounds = {}
        self.looped = set()
        self.instrument_ids = set()
        for index in sorted(indices):
            zones = self.zones(index, True)
            self.pzones[index] = zones
            global_gen = {}
            for generators, mods in zones:
                local = dict(generators)
                if 41 not in local:
                    global_gen.update(local)
                    continue
                instrument = local[41]
                if not 0 <= instrument < len(self.inst) - 1:
                    raise ValueError("Invalid instrument reference")
                self.instrument_ids.add(instrument)
                if instrument not in self.izones:
                    self.izones[instrument] = self.zones(instrument, False)
                preset_gen = global_gen | local
                instrument_global = {}
                for igen, imod in self.izones[instrument]:
                    setting = dict(igen)
                    if 53 not in setting:
                        instrument_global.update(setting)
                        continue
                    settings = instrument_global | setting
                    self.use_sample(settings[53], settings, preset_gen)
        # Linked stereo partners must survive even if only one side has a zone.
        pending = list(self.bounds)
        while pending:
            sample = pending.pop()
            record = self.sample_header(sample)
            link, typ = struct.unpack_from("<HH", record, 42)
            if typ & 14:
                self.sample_header(link)
                if link not in self.bounds:
                    start, end = struct.unpack_from("<II", self.shdr[link], 20)
                    self.bounds[link] = [start, end]
                    pending.append(link)
        intervals = sorted((low, high) for low, high in self.bounds.values())
        self.components = []
        for low, high in intervals:
            if self.components and low <= self.components[-1][1]:
                self.components[-1][1] = max(high, self.components[-1][1])
            else:
                self.components.append([low, high])
        self.instrument_map = {}
        self.sample_map = {}
        self.deltas = {}

    def zones(self, index, preset):
        headers = self.phdr if preset else self.inst
        bags = self.pbag if preset else self.ibag
        gens = self.pgen if preset else self.igen
        mods = self.font.tables[b"pmod" if preset else b"imod"]
        offset = 24 if preset else 20
        if not 0 <= index < len(headers) - 1:
            raise ValueError("Preset or instrument index is no longer valid")
        first = struct.unpack_from("<H", headers[index], offset)[0]
        last = struct.unpack_from("<H", headers[index + 1], offset)[0]
        if not 0 <= first <= last < len(bags):
            raise ValueError("Invalid zone bag range")
        result = []
        for b in range(first, last):
            g, m = struct.unpack("<HH", bags[b])
            ng, nm = struct.unpack("<HH", bags[b + 1])
            if not 0 <= g <= ng < len(gens) or not 0 <= m <= nm < len(mods) // 10:
                raise ValueError("Invalid generator/modulator range")
            result.append((gens[g:ng], mods[m * 10 : nm * 10]))
        return result

    def sample_header(self, index):
        if not 0 <= index < len(self.shdr) - 1:
            raise ValueError("Invalid sample reference")
        record = self.shdr[index]
        typ = struct.unpack_from("<H", record, 44)[0]
        if typ & 0x8000:
            raise ValueError("ROM samples cannot be exported")
        if typ & 16:
            raise ValueError("Compressed SF3 samples cannot be exported yet")
        start, end = struct.unpack_from("<II", record, 20)
        if (
            len(self.font.samples) % 2
            or not 0 <= start <= end <= len(self.font.samples) // 2
        ):
            raise ValueError("Invalid sample PCM range")
        return record

    def use_sample(self, index, settings, preset):
        record = self.sample_header(index)
        start, end, loop_start, loop_end = struct.unpack_from("<IIII", record, 20)

        def signed(value):
            return value - 65536 if value >= 32768 else value

        def amount(fine, coarse):
            return sum(
                signed(g.get(fine, 0)) + 32768 * signed(g.get(coarse, 0))
                for g in (settings, preset)
            )

        effective_start = start + amount(0, 4)
        effective_end = end + amount(1, 12)
        points = [start, end, effective_start, effective_end]
        if settings.get(54, 0) & 3 in (1, 3):
            self.looped.add(index)
            points.extend(
                [
                    loop_start,
                    loop_end,
                    loop_start + amount(2, 45),
                    loop_end + amount(3, 50),
                ]
            )
        if (
            effective_end < effective_start
            or min(points) < 0
            or max(points) > len(self.font.samples) // 2
        ):
            raise ValueError("Sample address offsets exceed source PCM data")
        low, high = self.bounds.get(index, [min(points), max(points)])
        self.bounds[index] = [min(low, *points), max(high, *points)]

    def assert_unchanged(self):
        stat = self.font.path.stat()
        if (stat.st_size, stat.st_mtime_ns) != self.font.signature:
            raise ValueError(
                "Source SoundFont changed during export; retry with the updated file"
            )


def export_sf2(entries, destination):
    """Write only reachable instruments/samples, compacting PCM without resampling."""
    entries = sorted(entries, key=lambda e: (int(e["bank"]), int(e["program"])))
    if not entries:
        raise ValueError("The sound set is empty")
    seen = set()
    sources = {}
    indices = {}
    for entry in entries:
        key = int(entry["bank"]), int(entry["program"])
        if not 0 <= key[0] <= 128 or not 0 <= key[1] <= 127:
            raise ValueError("Bank must be 0–128 and Program 0–127")
        if key in seen:
            raise ValueError(f"Duplicate Bank/Program: {key}")
        seen.add(key)
        path = str(Path(entry["path"]).resolve())
        indices.setdefault(path, set()).add(int(entry["index"]))
        if path not in sources:
            font = SoundFont(path)
            if font.major >= 3 or font.path.suffix.lower() == ".sf3":
                raise ValueError(
                    "SF3 export needs sample decompression; export SF2 sources only"
                )
            if font.sm24 is not None:
                raise ValueError(
                    "24-bit sample export is not supported yet; source is unchanged"
                )
            sources[path] = font
    destination = Path(destination)
    if str(destination.resolve()).casefold() in {p.casefold() for p in sources}:
        raise ValueError("Choose a new file; overwriting a source is disabled")
    plans = {path: ExportPlan(font, indices[path]) for path, font in sources.items()}
    out = {
        key: bytearray()
        for key in [
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
    }
    point_cursor = 0
    instrument_cursor = 0
    sample_cursor = 0
    for plan in plans.values():
        for index in sorted(plan.instrument_ids):
            plan.instrument_map[index] = instrument_cursor
            instrument_cursor += 1
        for index in sorted(plan.bounds):
            plan.sample_map[index] = sample_cursor
            sample_cursor += 1
        component_starts = []
        component_deltas = []
        for low, high in plan.components:
            component_starts.append(low)
            component_deltas.append(point_cursor - low)
            point_cursor += high - low + 46
        for index, (sample_low, sample_high) in plan.bounds.items():
            component = bisect_right(component_starts, sample_low) - 1
            if component < 0 or sample_high > plan.components[component][1]:
                raise ValueError("Invalid compact sample mapping")
            plan.deltas[index] = component_deltas[component]
    if instrument_cursor > 65535 or sample_cursor > 65535:
        raise ValueError("Too many instruments or samples for one SF2")

    def append_zones(zones, preset, plan):
        bag, gen, mod = (
            (b"pbag", b"pgen", b"pmod") if preset else (b"ibag", b"igen", b"imod")
        )
        for generators, modulators in zones:
            out[bag] += struct.pack("<HH", len(out[gen]) // 4, len(out[mod]) // 10)
            for op, value in generators:
                if preset and op == 41:
                    value = plan.instrument_map[value]
                if not preset and op == 53:
                    value = plan.sample_map[value]
                out[gen] += struct.pack("<HH", op, value)
            out[mod] += modulators

    for plan in plans.values():
        for index in sorted(plan.instrument_ids):
            out[b"inst"] += plan.inst[index][:20] + struct.pack(
                "<H", len(out[b"ibag"]) // 4
            )
            append_zones(plan.izones[index], False, plan)
        for index in sorted(plan.bounds):
            record = bytearray(plan.shdr[index])
            delta = plan.deltas[index]
            low, high = plan.bounds[index]
            for pos in (20, 24, 28, 32):
                value = struct.unpack_from("<I", record, pos)[0]
                if (
                    pos in (28, 32)
                    and index not in plan.looped
                    and not low <= value <= high
                ):
                    value = struct.unpack_from(
                        "<I", plan.shdr[index], 20 if pos == 28 else 24
                    )[0]
                struct.pack_into("<I", record, pos, value + delta)
            link, typ = struct.unpack_from("<HH", record, 42)
            struct.pack_into("<H", record, 42, plan.sample_map[link] if typ & 14 else 0)
            out[b"shdr"] += record
    for entry in entries:
        plan = plans[str(Path(entry["path"]).resolve())]
        index = int(entry["index"])
        out[b"phdr"] += (
            name(entry["name"])
            + struct.pack(
                "<HHH",
                int(entry["program"]),
                int(entry["bank"]),
                len(out[b"pbag"]) // 4,
            )
            + plan.phdr[index][26:]
        )
        append_zones(plan.pzones[index], True, plan)
    out[b"phdr"] += name("EOP") + struct.pack(
        "<HHHIII", 0, 0, len(out[b"pbag"]) // 4, 0, 0, 0
    )
    out[b"inst"] += name("EOI") + struct.pack("<H", len(out[b"ibag"]) // 4)
    for bag, gen, mod in [(b"pbag", b"pgen", b"pmod"), (b"ibag", b"igen", b"imod")]:
        out[bag] += struct.pack("<HH", len(out[gen]) // 4, len(out[mod]) // 10)
        out[gen] += bytes(4)
        out[mod] += bytes(10)
    out[b"shdr"] += name("EOS") + bytes(26)
    info = chunk(
        b"LIST",
        b"INFO"
        + chunk(b"ifil", struct.pack("<HH", 2, 1))
        + chunk(b"isng", b"EMU8000\0")
        + chunk(b"INAM", b"SoundFont Edit Studio\0"),
    )
    pdta = chunk(b"LIST", b"pdta" + b"".join(chunk(k, v) for k, v in out.items()))
    pcm_bytes = point_cursor * 2
    body_size = 4 + len(info) + 20 + pcm_bytes + len(pdta)
    if body_size > 0xFFFFFFFF:
        raise ValueError("SF2 exceeds the RIFF 4 GiB size limit")
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=destination.parent,
            prefix=destination.name + ".",
            suffix=".tmp",
            delete=False,
        ) as output:
            temporary = Path(output.name)
            output.write(b"RIFF" + struct.pack("<I", body_size) + b"sfbk" + info)
            output.write(
                b"LIST"
                + struct.pack("<I", 12 + pcm_bytes)
                + b"sdta"
                + b"smpl"
                + struct.pack("<I", pcm_bytes)
            )
            for plan in plans.values():
                plan.assert_unchanged()
                with plan.font.path.open("rb") as source:
                    for low, high in plan.components:
                        plan.font.samples.copy_to(output, low * 2, high * 2, source)
                        output.write(bytes(92))
                plan.assert_unchanged()
            output.write(pdta)
        SoundFont(temporary)
        os.replace(temporary, destination)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return dict(
        presets=len(entries),
        instruments=instrument_cursor,
        samples=sample_cursor,
        bytes=destination.stat().st_size,
    )
