import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from ytmanager.ffmpeg_tools import build_ffmpeg_split_command, parse_ffprobe_keyframes, probe_local_video, read_probe_created_at


class FFmpegToolsTests(unittest.TestCase):
    def test_parse_ffprobe_keyframes(self):
        payload = {
            "frames": [
                {"key_frame": 1, "best_effort_timestamp_time": "0.000000"},
                {"key_frame": 1, "pkt_pts_time": "12.500000"},
                {"key_frame": 1, "pkt_dts_time": "24.250000"},
            ]
        }
        self.assertEqual(parse_ffprobe_keyframes(payload), [0.0, 12.5, 24.25])

    def test_build_ffmpeg_split_command(self):
        command = build_ffmpeg_split_command(Path("ffmpeg"), Path("input.mp4"), Path("output.mp4"), 12.5, 30.0)
        self.assertEqual(command[:6], ["ffmpeg", "-y", "-ss", "12.500", "-i", "input.mp4"])
        self.assertEqual(command[-1], "output.mp4")

    def test_read_probe_created_at_prefers_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "sample.mp4"
            source.write_bytes(b"x")
            payload = {"format": {"tags": {"creation_time": "2026-04-25T01:02:03Z"}}}
            self.assertEqual(read_probe_created_at(payload, source), "2026-04-25")

    def test_probe_local_video_parses_metadata_and_keyframes(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "sample.mp4"
            source.write_bytes(b"x")

            def runner(command, capture_output, text, check):
                if "-show_format" in command:
                    stdout = json.dumps(
                        {
                            "format": {"duration": "120.0", "tags": {"creation_time": "2026-04-25T01:02:03Z"}},
                            "streams": [{"codec_type": "video", "width": 1920, "height": 1080}],
                        }
                    )
                else:
                    stdout = json.dumps({"frames": [{"key_frame": 1, "best_effort_timestamp_time": "0.0"}, {"key_frame": 1, "best_effort_timestamp_time": "15.0"}]})
                return subprocess.CompletedProcess(command, 0, stdout=stdout, stderr="")

            probe = probe_local_video(source, ffprobe_path=Path("ffprobe"), runner=runner)
            self.assertEqual(probe.duration_seconds, 120.0)
            self.assertEqual((probe.width_pixels, probe.height_pixels), (1920, 1080))
            self.assertEqual(probe.created_at, "2026-04-25")
            self.assertEqual(probe.keyframes, (0.0, 15.0))


if __name__ == "__main__":
    unittest.main()
