"""The boot-time history replay encodes valid remote-write payloads."""
import importlib.util
import struct
import unittest

spec = importlib.util.spec_from_file_location("replay_history", "deploy/vercel/replay_history.py")
replay = importlib.util.module_from_spec(spec)
spec.loader.exec_module(replay)


class TestReplayEncoding(unittest.TestCase):
    def test_varint(self):
        self.assertEqual(replay.varint(1), b"\x01")
        self.assertEqual(replay.varint(300), b"\xac\x02")

    def test_snappy_literal_layout(self):
        data = b"x" * 70000
        encoded = replay.snappy_literal(data)
        self.assertEqual(encoded[:3], replay.varint(70000))
        self.assertEqual(encoded[3], 0xFC)
        self.assertEqual(struct.unpack("<I", encoded[4:8])[0], 69999)
        self.assertEqual(encoded[8:], data)

    def test_labels_are_sorted_and_samples_encoded(self):
        payload = replay.encode_series({"job": "a", "__name__": "m"}, [(1000, 1.5)])
        self.assertLess(payload.index(b"__name__"), payload.index(b"job"))
        self.assertIn(b"\x09" + struct.pack("<d", 1.5) + b"\x10" + replay.varint(1000), payload)

    def test_label_parsing_handles_escapes(self):
        parsed = replay.parse_labels(r'a="x",b="say \"hi\"",le="+Inf"')
        self.assertEqual(parsed, {"a": "x", "b": 'say "hi"', "le": "+Inf"})

    def test_collect_keeps_order_adds_up_and_respects_head_window(self):
        snapshots = [["m_total 1.0"], ['n{a="b"} 2.0']] * 300
        series = replay.collect(snapshots, 1_000_000)
        by_name = {labels["__name__"]: (labels, samples) for labels, samples in series}
        self.assertEqual(set(by_name), {"up", "m_total", "n"})
        self.assertEqual(by_name["up"][0]["job"], "mlops-api")
        for _, samples in series:
            stamps = [t for t, _ in samples]
            self.assertEqual(stamps, sorted(stamps))
            self.assertGreaterEqual(min(stamps), (1_000_000 - replay.MAX_AGE_SECONDS) * 1000)


if __name__ == "__main__":
    unittest.main()
