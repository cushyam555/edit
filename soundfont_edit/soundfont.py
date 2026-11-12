"""SoundFont RIFF reader and dependency-preserving SF2 preset exporter."""

from dataclasses import dataclass
from pathlib import Path
import struct


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


@dataclass
class Preset:
    index: int
    name: str
    bank: int
    program: int


class SoundFont:
    def __init__(self, path):
        self.path = Path(path)
        data = self.path.read_bytes()
        if len(data) < 12 or data[:4] != b"RIFF" or data[8:12] != b"sfbk":
            raise ValueError("Not a SoundFont bank")
        if struct.unpack_from("<I", data, 4)[0] + 8 != len(data):
            raise ValueError("Invalid RIFF length")
        self.tables = {}
        self.samples = b""
        self.sm24 = None
        self.major = 2
        for tag, payload in chunks(data, 12):
            if tag != b"LIST":
                continue
            for key, value in chunks(payload, 4):
                if payload[:4] == b"pdta":
                    self.tables[key] = value
                elif payload[:4] == b"sdta":
                    if key == b"smpl":
                        self.samples = value
                    if key == b"sm24":
                        self.sm24 = value
                elif payload[:4] == b"INFO" and key == b"ifil":
                    self.major = struct.unpack_from("<H", value)[0]
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


def export_sf2(entries, destination):
    """Copy selected presets, all source instruments/samples, rebasing every reference.

    Keeping the complete source instrument pool preserves global zones, modulators,
    stereo sample links and shared samples without a lossy dependency traversal.
    """
    if not entries:
        raise ValueError("The sound set is empty")
    seen = set()
    for entry in entries:
        key = (int(entry["bank"]), int(entry["program"]))
        if not 0 <= key[0] <= 128 or not 0 <= key[1] <= 127:
            raise ValueError("Bank must be 0–128 and Program 0–127")
        if key in seen:
            raise ValueError(f"Duplicate Bank/Program: {key}")
        seen.add(key)
    sources = {}
    for entry in entries:
        path = str(Path(entry["path"]).resolve())
        if path not in sources:
            sf = SoundFont(path)
            if sf.major >= 3 or sf.path.suffix.lower() == ".sf3":
                raise ValueError(
                    "SF3 export needs sample decompression; export SF2 sources only"
                )
            if sf.sm24 is not None:
                raise ValueError(
                    "24-bit sample export is not supported yet; source is unchanged"
                )
            sources[path] = sf
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
    samples = bytearray()
    offsets = {}
    for path, sf in sources.items():
        insbase, bagbase = len(out[b"inst"]) // 22, len(out[b"ibag"]) // 4
        samplebase, pointbase = len(out[b"shdr"]) // 46, len(samples) // 2
        offsets[path] = insbase
        for r in sf.records(b"inst", 22)[:-1]:
            out[b"inst"] += r[:20] + struct.pack(
                "<H", struct.unpack_from("<H", r, 20)[0] + bagbase
            )
        genbase, modbase = len(out[b"igen"]) // 4, len(out[b"imod"]) // 10
        for r in sf.records(b"ibag", 4)[:-1]:
            g, m = struct.unpack("<HH", r)
            out[b"ibag"] += struct.pack("<HH", g + genbase, m + modbase)
        for r in sf.records(b"igen", 4)[:-1]:
            op, v = struct.unpack("<HH", r)
            out[b"igen"] += struct.pack("<HH", op, v + samplebase if op == 53 else v)
        out[b"imod"] += sf.tables[b"imod"][:-10]
        for r in sf.records(b"shdr", 46)[:-1]:
            r = bytearray(r)
            for pos in [20, 24, 28, 32]:
                struct.pack_into(
                    "<I", r, pos, struct.unpack_from("<I", r, pos)[0] + pointbase
                )
            link, typ = struct.unpack_from("<HH", r, 42)
            if typ & 0x8000:
                raise ValueError("ROM samples cannot be exported")
            if typ & 14:
                struct.pack_into("<H", r, 42, link + samplebase)
            out[b"shdr"] += r
        samples += sf.samples
    for entry in entries:
        path = str(Path(entry["path"]).resolve())
        sf = sources[path]
        headers = sf.records(b"phdr", 38)
        idx = int(entry["index"])
        if not 0 <= idx < len(headers) - 1:
            raise ValueError("Preset index is no longer valid")
        first = struct.unpack_from("<H", headers[idx], 24)[0]
        last = struct.unpack_from("<H", headers[idx + 1], 24)[0]
        out[b"phdr"] += (
            name(entry["name"])
            + struct.pack(
                "<HHH",
                int(entry["program"]),
                int(entry["bank"]),
                len(out[b"pbag"]) // 4,
            )
            + headers[idx][26:]
        )
        bags = sf.records(b"pbag", 4)
        for b in range(first, last):
            g, m = struct.unpack("<HH", bags[b])
            ng, nm = struct.unpack("<HH", bags[b + 1])
            out[b"pbag"] += struct.pack(
                "<HH", len(out[b"pgen"]) // 4, len(out[b"pmod"]) // 10
            )
            for r in sf.records(b"pgen", 4)[g:ng]:
                op, v = struct.unpack("<HH", r)
                out[b"pgen"] += struct.pack(
                    "<HH", op, v + offsets[path] if op == 41 else v
                )
            out[b"pmod"] += sf.tables[b"pmod"][m * 10 : nm * 10]
    out[b"phdr"] += name("EOP") + struct.pack(
        "<HHHIII", 0, 0, len(out[b"pbag"]) // 4, 0, 0, 0
    )
    out[b"inst"] += name("EOI") + struct.pack("<H", len(out[b"ibag"]) // 4)
    for bag, gen, mod in [(b"pbag", b"pgen", b"pmod"), (b"ibag", b"igen", b"imod")]:
        out[bag] += struct.pack("<HH", len(out[gen]) // 4, len(out[mod]) // 10)
        out[gen] += bytes(4)
        out[mod] += bytes(10)
    out[b"shdr"] += name("EOS") + bytes(26)
    info = (
        chunk(b"ifil", struct.pack("<HH", 2, 1))
        + chunk(b"isng", b"EMU8000\0")
        + chunk(b"INAM", b"SoundFont Edit Studio\0")
    )
    body = (
        b"sfbk"
        + chunk(b"LIST", b"INFO" + info)
        + chunk(b"LIST", b"sdta" + chunk(b"smpl", samples))
        + chunk(b"LIST", b"pdta" + b"".join(chunk(k, v) for k, v in out.items()))
    )
    destination = Path(destination)
    if str(destination.resolve()) in sources:
        raise ValueError("Choose a new file; overwriting a source is disabled")
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    try:
        temporary.write_bytes(chunk(b"RIFF", body))
        SoundFont(temporary)
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)
