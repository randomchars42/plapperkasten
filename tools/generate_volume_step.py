"""Generate the short, click-free volume feedback tone using only stdlib."""

import math
from pathlib import Path
import struct
import wave


def main() -> None:
    rate = 44100
    frames = round(rate * 0.070)
    fade = round(rate * 0.010)
    data = bytearray()
    for index in range(frames):
        ramp = min(1.0, index / (fade - 1), (frames - 1 - index) / (fade - 1))
        envelope = (1 - math.cos(math.pi * ramp)) / 2
        value = round(8192 * envelope * math.sin(2 * math.pi * 1000 * index / rate))
        data.extend(struct.pack('<hh', value, value))
    path = Path(__file__).resolve().parents[1] / (
        'src/plapperkasten/plugins/soundeffects/sounds/volume-step.wav')
    with wave.open(str(path), 'wb') as sound:
        sound.setnchannels(2)
        sound.setsampwidth(2)
        sound.setframerate(rate)
        sound.writeframes(data)


if __name__ == '__main__':
    main()
