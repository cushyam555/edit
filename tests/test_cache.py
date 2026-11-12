import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from soundfont_edit.cache import read_presets
from test_soundfont import fixture


class CacheTests(unittest.TestCase):
    def test_cache_hit_and_file_change(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "a.sf2"
            db = Path(d) / "cache.db"
            fixture(p)
            self.assertEqual(read_presets(p, db)[0]["name"], "Piano")
            with patch(
                "soundfont_edit.cache.SoundFont",
                side_effect=AssertionError("Cache should avoid sample loading"),
            ):
                self.assertEqual(read_presets(p, db)[0]["name"], "Piano")
            fixture(p, "Different")
            self.assertEqual(read_presets(p, db)[0]["name"], "Different")
