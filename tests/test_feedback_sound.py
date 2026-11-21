"""The volume cue is one short tone with quiet boundaries, not hard clicks."""

import math
from pathlib import Path
import struct
import unittest
import wave

import plapperkasten


class VolumeFeedbackSoundTests(unittest.TestCase):
    def test_single_short_tone_has_silent_edges_and_one_audible_burst(self):
        path = Path(plapperkasten.__file__).parent / 'plugins/soundeffects/sounds/volume-step.wav'
        with wave.open(str(path), 'rb') as sound:
            self.assertEqual((sound.getnchannels(), sound.getsampwidth()), (2, 2))
            rate = sound.getframerate()
            duration = sound.getnframes() / rate
            data = sound.readframes(sound.getnframes())
        self.assertGreater(duration, 0.05)
        self.assertLess(duration, 0.1)
        samples = struct.unpack('<' + 'h' * (len(data) // 2), data)
        left, right = samples[::2], samples[1::2]
        self.assertEqual(left, right)
        self.assertEqual((left[0], left[-1]), (0, 0))
        peak = max(map(abs, left))
        self.assertLess(max(map(abs, left[:round(rate * 0.001)])), peak * 0.05)
        self.assertLess(max(map(abs, left[-round(rate * 0.001):])), peak * 0.05)
        window = round(rate * 0.005)
        levels = [math.sqrt(sum(value * value for value in left[i:i + window]) /
                            len(left[i:i + window]))
                  for i in range(0, len(left), window)]
        audible = [level > max(levels) * 0.1 for level in levels]
        onsets = sum(current and not previous for previous, current
                     in zip([False] + audible, audible))
        self.assertEqual(onsets, 1)
