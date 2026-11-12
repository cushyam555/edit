import os
import sys
from pathlib import Path


class Player:
    def __init__(self):
        self.synth = None
        self.loaded = {}
        self.selected = None
        self.volume = 89
        self.velocity = 100
        self.dll_handle = None
        self.channel = 0

    def select(self, path, bank, program, drums=False):
        if self.synth is None:
            dll = (
                Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
                / "vendor"
            )
            if sys.platform == "win32" and dll.exists():
                self.dll_handle = os.add_dll_directory(str(dll))
                os.environ["PATH"] = str(dll) + os.pathsep + os.environ.get("PATH", "")
            import fluidsynth

            self.synth = fluidsynth.Synth()
            self.synth.start(driver=None if sys.platform == "win32" else "pulseaudio")
            if not self.synth.audio_driver:
                self.synth.delete()
                self.synth = None
                raise RuntimeError("No audio output device is available")
        if path not in self.loaded:
            ident = self.synth.sfload(path)
            if ident < 0:
                raise RuntimeError("FluidSynth cannot load this SoundFont")
            self.loaded[path] = ident
        if self.selected == (path, bank, program):
            return
        self.synth.all_sounds_off(self.channel)
        self.channel = 9 if drums else 0
        if (
            self.synth.program_select(self.channel, self.loaded[path], bank, program)
            < 0
        ):
            raise RuntimeError("Cannot select preset")
        self.selected = (path, bank, program)
        self.synth.cc(self.channel, 7, self.volume)

    def on(self, n):
        if self.synth:
            self.synth.noteon(self.channel, n, self.velocity)

    def off(self, n):
        if self.synth:
            self.synth.noteoff(self.channel, n)

    def close(self):
        if self.synth:
            self.synth.delete()
