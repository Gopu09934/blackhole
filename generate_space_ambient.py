"""
Generate a seamless, fully-synthesized ambient "deep space" soundtrack.
------------------------------------------------------------------------
Nothing here is sampled, recorded, or copied from any existing work —
every sound is generated mathematically (sine layers + filtered noise),
so there is zero copyright risk and it can be reused/redistributed freely.

Layers:
  - Sub-bass drone: a few slightly detuned low sine waves with slow
    amplitude "breathing" (gives a deep hum, like a ship's engine or a
    distant star).
  - Shimmer: a very quiet high overtone with slow tremolo (adds a subtle
    twinkle without being distracting).
  - Filtered noise ("solar wind" texture): white noise passed through a
    low-pass filter, amplitude-modulated slowly to create soft swells,
    reminiscent of static/plasma-wave textures without copying any real
    recording.

The output is crossfaded at the loop point so it plays back-to-back with
no audible seam when looped by ffmpeg's -stream_loop -1.

Install: pip install numpy scipy
Run:     python generate_space_ambient.py
Output:  space_ambient.wav  (default: 90-second seamless loop, stereo)
"""

import numpy as np
from scipy.signal import butter, lfilter
from scipy.io import wavfile

SAMPLE_RATE = 44100
DURATION_SEC = 90      # length of the loop before it repeats
CROSSFADE_SEC = 3       # blended into the loop point for a seamless seam
SEED = 7


def lowpass(signal, cutoff_hz, sr, order=4):
    nyq = 0.5 * sr
    b, a = butter(order, cutoff_hz / nyq, btype="low")
    return lfilter(b, a, signal)


def generate(path="space_ambient.wav", duration=DURATION_SEC, sr=SAMPLE_RATE,
             crossfade=CROSSFADE_SEC, seed=SEED):
    rng = np.random.default_rng(seed)
    total = duration + crossfade
    t = np.linspace(0, total, int(sr * total), endpoint=False)

    # --- Sub-bass drone: three detuned low tones with independent slow LFOs
    drone = (
        0.25 * np.sin(2 * np.pi * 48 * t) * (0.6 + 0.4 * np.sin(2 * np.pi * 0.030 * t))
        + 0.15 * np.sin(2 * np.pi * 72.3 * t + 0.5) * (0.6 + 0.4 * np.sin(2 * np.pi * 0.021 * t + 1.3))
        + 0.10 * np.sin(2 * np.pi * 96.7 * t + 1.1) * (0.5 + 0.5 * np.sin(2 * np.pi * 0.017 * t + 2.1))
    )

    # --- Shimmer: quiet high overtone with slow tremolo
    shimmer = 0.025 * np.sin(2 * np.pi * 880 * t) * (0.5 + 0.5 * np.sin(2 * np.pi * 0.11 * t))

    # --- Filtered noise texture ("solar wind"), slowly swelling
    noise = rng.normal(0, 1, t.shape)
    wind = lowpass(noise, cutoff_hz=300, sr=sr)
    wind /= np.max(np.abs(wind)) + 1e-9
    wind *= 0.05 * (0.6 + 0.4 * np.sin(2 * np.pi * 0.008 * t + 0.7))

    mono = drone + shimmer + wind
    mono /= np.max(np.abs(mono)) + 1e-9
    mono *= 0.7  # headroom so it doesn't clip when mixed with stream audio

    # --- Slow stereo panning for width
    pan = 0.5 + 0.3 * np.sin(2 * np.pi * 0.015 * t)
    left = mono * (1 - pan)
    right = mono * pan

    # --- Crossfade the tail into the head so the loop has no audible seam
    fade_n = int(crossfade * sr)
    fade_curve = np.linspace(0, 1, fade_n)
    for ch in (left, right):
        head = ch[:fade_n].copy()
        ch[-fade_n:] = ch[-fade_n:] * (1 - fade_curve) + head * fade_curve
    left = left[:-fade_n]
    right = right[:-fade_n]

    stereo = np.stack([left, right], axis=1)
    stereo_int16 = np.int16(np.clip(stereo, -1, 1) * 32767)
    wavfile.write(path, sr, stereo_int16)
    print(f"Wrote {path} — {duration}s seamless loop, {sr}Hz stereo.")


if __name__ == "__main__":
    generate()
