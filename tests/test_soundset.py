import unittest
from copy import deepcopy
from soundfont_edit.soundset import merge_entries, ordered, slot
from soundfont_edit.gm import GM_NAMES, reference


def entry(name, bank=0, program=0, path=None):
    return dict(
        path=path or name + ".sf2", index=0, name=name, bank=bank, program=program
    )


class SoundSetTests(unittest.TestCase):
    def test_numeric_order_and_gm_reference(self):
        rows = ordered(
            [
                entry("ten", program=10),
                entry("two", program=2),
                entry("drums", bank=128),
                entry("bank", bank=3),
            ]
        )
        self.assertEqual([slot(e) for e in rows], [(0, 2), (0, 10), (3, 0), (128, 0)])
        self.assertEqual(len(GM_NAMES), 128)
        self.assertEqual(
            reference(entry("Custom bass", program=33)), "Electric Bass (finger)"
        )
        self.assertEqual(reference(entry("drums", bank=128)), "Standard Kit")

    def test_replace_and_remap_preserve_original_preview_address(self):
        old = [entry("old")]
        incoming = [entry("replacement")]
        result = merge_entries(old, incoming, lambda *args: ("replace", None))
        self.assertEqual(result[0]["path"], "replacement.sf2")
        self.assertEqual(old[0]["name"], "old")
        result = merge_entries(old, incoming, lambda *args: ("remap", (2, 33)))
        self.assertEqual(slot(result[1]), (2, 33))
        self.assertEqual(
            (result[1]["source_bank"], result[1]["source_program"]), (0, 0)
        )

    def test_cancel_is_atomic_for_entire_batch(self):
        old = [entry("old")]
        before = deepcopy(old)
        result = merge_entries(
            old,
            [entry("free", program=4), entry("collision")],
            lambda *args: ("cancel", None),
        )
        self.assertIsNone(result)
        self.assertEqual(old, before)

    def test_conflicts_within_incoming_batch_are_resolved(self):
        calls = []

        def resolve(candidate, conflict, working):
            calls.append(conflict["name"])
            return "replace", None

        result = merge_entries([], [entry("one"), entry("two")], resolve)
        self.assertEqual(calls, ["one"])
        self.assertEqual([e["name"] for e in result], ["two"])
