"""Host arithmetic/source checks for the PS2 completed-frame FPS meter.

This models the averaging contract; it does not compile or execute raylib or
measure hardware performance. Producer FPS is not proof of GS presentation FPS.
"""

from pathlib import Path
import re
import struct
import unittest


class CompletedFrameMeter:
    def __init__(self):
        self.reset()

    def reset(self):
        self.elapsed = 0.0
        self.frames = self.index = 0
        self.history = [0.0] * 32

    def complete(self, duration):
        if self.frames == 32:
            self.elapsed -= self.history[self.index]
        else:
            self.frames += 1
        self.history[self.index] = struct.unpack("f", struct.pack("f", duration))[0]
        self.elapsed += self.history[self.index]
        self.index = (self.index + 1) & 31
        while self.frames > 1:
            oldest = (self.index + 32 - self.frames) & 31
            if self.elapsed - self.history[oldest] < 0.5 - 0.0000001:
                break
            self.elapsed -= self.history[oldest]
            self.frames -= 1

    def get(self):
        return int(self.frames/self.elapsed + 0.5) if self.elapsed > 0.0 else 0


def function_body(text, signature):
    text = re.sub(r"/\*.*?\*/|//[^\n]*", "", text, flags=re.S)
    begin = text.index("{", text.index(signature))
    end = begin + 1
    depth = 1
    while depth:
        depth += (text[end] == "{") - (text[end] == "}")
        end += 1
    return text[begin + 1:end - 1]


class MeterTests(unittest.TestCase):
    def test_alternating_frame_durations_are_counted_as_sixty_fps(self):
        meter = CompletedFrameMeter()
        durations = [0.012, 1.0/30.0 - 0.012] * 300
        for duration in durations:
            meter.complete(duration)
        self.assertAlmostEqual(len(durations)/sum(durations), 60.0)
        self.assertEqual(meter.get(), 60)

    def test_real_fifty_and_thirty_fps_are_not_reported_as_sixty(self):
        for rate in (50, 30):
            with self.subTest(rate=rate):
                meter = CompletedFrameMeter()
                for _ in range(rate * 10):
                    meter.complete(1.0/rate)
                self.assertEqual(meter.get(), rate)

    def test_absent_and_duplicate_getfps_calls_do_not_change_samples(self):
        meters = [CompletedFrameMeter() for _ in range(3)]
        for frame in range(600):
            duration = 0.012 if frame % 2 == 0 else 1.0/30.0 - 0.012
            for meter in meters:
                meter.complete(duration)
            meters[1].get()
            for _ in range(10):
                meters[2].get()
        self.assertEqual([m.__dict__ for m in meters], [meters[0].__dict__] * 3)
        self.assertEqual(meters[0].get(), 60)

    def test_slow_frame_remains_in_elapsed_time(self):
        meter = CompletedFrameMeter()
        for _ in range(30):
            meter.complete(1.0/60.0)
        meter.complete(1.0)
        self.assertEqual(meter.get(), 1)
        self.assertEqual(meter.frames, 1)

    def test_warmup_and_window_reset(self):
        meter = CompletedFrameMeter()
        self.assertEqual(meter.get(), 0)
        meter.complete(1.0/50.0)
        self.assertEqual(meter.get(), 50)
        for _ in range(29):
            meter.complete(1.0/50.0)
        self.assertGreaterEqual(meter.elapsed, 0.5 - 0.0000001)
        meter.reset()
        self.assertEqual(meter.get(), 0)
        self.assertEqual(meter.frames, 0)
        meter.complete(1.0/30.0)
        self.assertEqual(meter.get(), 30)

    def test_rate_change_updates_after_half_second_of_completed_frames(self):
        meter = CompletedFrameMeter()
        for _ in range(60):
            meter.complete(1.0/60.0)
        for _ in range(16):
            meter.complete(1.0/30.0)
        self.assertEqual(meter.get(), 30)

    def test_zero_elapsed_warmup_does_not_divide_by_zero(self):
        meter = CompletedFrameMeter()
        meter.complete(0.0)
        self.assertEqual(meter.get(), 0)
        self.assertEqual(meter.frames, 1)


class SourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = (Path(__file__).resolve().parents[1] / "src/rcore.c").read_text(encoding="utf-8")

    def test_frame_boundary_owns_sampling_without_changing_game_clock(self):
        end = function_body(self.source, "void EndDrawing(void)")
        self.assertEqual(end.count("++ps2Fps.frames;"), 1)
        self.assertIn("ps2Fps.history[ps2Fps.index] = (float)CORE.Time.frame;", end)
        self.assertLess(end.index("CORE.Time.frame = CORE.Time.update + CORE.Time.draw;"),
                        end.index("ps2Fps.history[ps2Fps.index] = (float)CORE.Time.frame;"))
        sampling = end[end.index("if (ps2Fps.frames == 32)"):end.index("#if !defined(PLATFORM_PLAYSTATION2)")]
        self.assertNotIn("GetTime(", sampling)
        self.assertNotIn("GetFrameTime(", sampling)
        self.assertNotIn("malloc", sampling)
        self.assertNotRegex(sampling, r"CORE\.Time\.\w+\s*=")
        frame_time = function_body(self.source, "float GetFrameTime(void)")
        self.assertEqual(frame_time.strip(), "return (float)CORE.Time.frame;")

    def test_getfps_only_reads_ps2_meter_and_retains_other_platform_sampler(self):
        get = function_body(self.source, "int GetFPS(void)")
        ps2 = get.split("#if defined(PLATFORM_PLAYSTATION2)", 1)[1].split("#else", 1)[0]
        self.assertIn("(float)ps2Fps.frames/(float)ps2Fps.elapsed", ps2)
        self.assertNotIn("GetTime(", ps2)
        self.assertNotRegex(ps2, r"ps2Fps\.\w+\s*(?:=|\+\+|--)")
        self.assertIn("#define FPS_CAPTURE_FRAMES_COUNT    30", get)
        self.assertIn("if ((GetTime() - last) > FPS_STEP)", get)
        self.assertEqual(self.source.count("++ps2Fps.frames;"), 1)
        init = function_body(self.source, "void InitWindow(")
        self.assertIn("memset(&ps2Fps, 0, sizeof(ps2Fps));", init)


if __name__ == "__main__":
    unittest.main(verbosity=2)
