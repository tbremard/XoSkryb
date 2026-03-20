"""
audio_stat.py — Diagnostic tool for analysing WAV file energy profiles.

Usage:
    python audio_stat.py <path_to_wav_file>

Example:
    python audio_stat.py recordings/diag_115219_11.4s.wav

The script prints:
  - Overall file info (duration, sample rate)
  - RMS energy per 0.5 s window (5 × 100 ms chunks grouped together)
  - Percentile summary (p50, p75, p90) of per-chunk RMS
  - Fraction of 100 ms chunks exceeding several energy thresholds

This helps distinguish speech from noise:
  - Speech has sustained energy across most chunks (high median, high fraction above 0.05).
  - Spiky noise (keyboard, clicks) has a few loud bursts but low median and low fraction.
"""

import sys
import numpy as np
import soundfile as sf

CHUNK_SEC = 0.1        # Window size for per-chunk RMS (100 ms)
GROUP_CHUNKS = 5       # Chunks per display row (0.5 s per row)


def analyse(path: str):
    data, sr = sf.read(path)
    mono = data[:, 0] if data.ndim > 1 else data
    dur = len(mono) / sr

    print(f"File:        {path}")
    print(f"Duration:    {dur:.2f} s")
    print(f"Sample rate: {sr} Hz")
    print(f"Samples:     {len(mono)}")
    print()

    # --- Per-chunk RMS ---
    # Split the audio into small fixed-size windows and compute the RMS
    # (root-mean-square) of each.  RMS measures the average energy of a
    # window — higher means louder.
    win = int(CHUNK_SEC * sr)
    n = len(mono) // win
    chunks = mono[: n * win].reshape(n, win)
    rms = np.sqrt(np.mean(chunks ** 2, axis=1))

    # --- Timeline: RMS per 0.5 s row ---
    # Groups of 5 chunks (0.5 s) are shown on one line so you can see
    # where energy is concentrated.  Sustained high values → speech.
    # Isolated spikes surrounded by low values → impulsive noise.
    print(f"RMS per {GROUP_CHUNKS * CHUNK_SEC:.1f} s window ({n} chunks of {CHUNK_SEC*1000:.0f} ms):")
    for i in range(0, n, GROUP_CHUNKS):
        t_start = i * CHUNK_SEC
        t_end = min((i + GROUP_CHUNKS) * CHUNK_SEC, dur)
        grp = rms[i : i + GROUP_CHUNKS]
        vals = "  ".join(f"{v:.4f}" for v in grp)
        print(f"  {t_start:5.1f} - {t_end:5.1f} s: [{vals}]  avg={np.mean(grp):.4f}")
    print()

    # --- Percentile summary ---
    # Percentiles summarise the distribution of chunk energies:
    #   p50 (median) — the "typical" chunk energy.  Speech keeps this high
    #       because most chunks contain voiced audio.  Spiky noise has a low
    #       median because most chunks are quiet between bursts.
    #   p75 — energy exceeded by the loudest 25 % of chunks.
    #   p90 — energy exceeded by the loudest 10 % of chunks.  Sensitive to
    #       peaks, so spiky noise can score high here even with low median.
    p50 = float(np.percentile(rms, 50))
    p75 = float(np.percentile(rms, 75))
    p90 = float(np.percentile(rms, 90))
    print("Percentiles:")
    print(f"  p50 (median) = {p50:.4f}   <-- best speech-vs-noise discriminator")
    print(f"  p75          = {p75:.4f}")
    print(f"  p90          = {p90:.4f}")
    print()

    # --- Basic stats ---
    # min  — quietest chunk (background / silence floor).
    # mean — overall average energy (diluted by silence in speech recordings).
    # std  — spread of chunk energies.  High std + low median → spiky noise.
    #         Moderate std + high median → speech with natural pauses.
    # max  — single loudest chunk.
    print("Stats:")
    print(f"  min  = {np.min(rms):.4f}")
    print(f"  mean = {np.mean(rms):.4f}")
    print(f"  std  = {np.std(rms):.4f}")
    print(f"  max  = {np.max(rms):.4f}")
    print()

    # --- Chunk fraction above thresholds ---
    # Shows what percentage of chunks exceed a given RMS level.
    # Speech typically has >60 % of chunks above 0.05.
    # Spiky noise typically has <35 % above 0.05.
    print("Chunk fraction above threshold:")
    for th in [0.02, 0.03, 0.05, 0.08, 0.10]:
        count = int(np.sum(rms >= th))
        frac = count / n * 100
        print(f"  >= {th:.2f}: {frac:5.1f} %  ({count}/{n})")
    print()

    # --- Key differentiators ---
    # These two metrics best separate speech from noise:
    #   chunks >= 0.05 : speech ~70 %, noise ~30 %
    #   chunks >= 0.03 : speech ~80 %, noise ~45 %
    # A recording that scores high on both is very likely speech.
    frac_05 = np.mean(rms >= 0.05) * 100
    frac_03 = np.mean(rms >= 0.03) * 100
    print("Key differentiators (speech vs noise):")
    print(f"  chunks >= 0.05: {frac_05:5.1f} %  (speech ~70%, noise ~30%)")
    print(f"  chunks >= 0.03: {frac_03:5.1f} %  (speech ~80%, noise ~45%)")
    if frac_05 >= 50:
        verdict = "SPEECH"
    elif frac_03 < 50:
        verdict = "NOISE"
    else:
        verdict = "UNCERTAIN"
    print(f"  --> likely: {verdict}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__.strip())
        sys.exit(1)
    analyse(sys.argv[1])
