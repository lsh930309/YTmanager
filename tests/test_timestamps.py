import unittest

from ytmanager.timestamps import format_timestamp, parse_timestamp, render_timestamps
from ytmanager.models import TimestampEntry


class TimestampTests(unittest.TestCase):
    def test_format_timestamp(self):
        self.assertEqual(format_timestamp(83), "01:23")
        self.assertEqual(format_timestamp(3661), "01:01:01")

    def test_parse_timestamp(self):
        self.assertEqual(parse_timestamp("01:23"), 83)
        self.assertEqual(parse_timestamp("01:01:01"), 3661)
        with self.assertRaises(ValueError):
            parse_timestamp("01:99")

    def test_render_sorted(self):
        rendered = render_timestamps([TimestampEntry(90, "두 번째"), TimestampEntry(10, "첫 번째")])
        self.assertEqual(rendered, "00:10 - 첫 번째\n01:30 - 두 번째")


if __name__ == "__main__":
    unittest.main()
