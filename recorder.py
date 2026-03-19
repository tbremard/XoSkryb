import os
import subprocess
import sys
import time
import numpy as np
import sounddevice as sd
import soundfile as sf

SILENCE_THRESHOLD = 0.01   # RMS amplitude below this is considered silence
SILENCE_DURATION = 2.0     # Seconds of silence before stopping recording
SAMPLERATE = 16000
CHANNELS = 1
RECORDINGS_DIR = "recordings"
TRANSCRIPTS_DIR = "Transcripts"


def list_input_devices():
    devices = sd.query_devices()
    print("\nAvailable input devices:")
    for i, dev in enumerate(devices):
        if dev["max_input_channels"] > 0:
            print(f"  [{i}] {dev['name']}")
    print()


def select_device() -> int:
    list_input_devices()
    while True:
        try:
            idx = int(input("Select input device index: "))
            dev = sd.query_devices(idx)
            if dev["max_input_channels"] > 0:
                return idx
            print("That device has no input channels. Try again.")
        except (ValueError, sd.PortAudioError):
            print("Invalid index. Try again.")


def record_until_silence(device_index: int) -> np.ndarray:
    print("Recording... (speak now, will stop after silence)")
    buffer = []
    silent_chunks = 0
    chunk_frames = int(SAMPLERATE * 0.1)  # 100 ms chunks
    chunks_for_silence = int(SILENCE_DURATION / 0.1)

    def callback(indata, frames, time_info, status):
        nonlocal silent_chunks
        chunk = indata.copy()
        buffer.append(chunk)
        rms = float(np.sqrt(np.mean(chunk ** 2)))
        if rms < SILENCE_THRESHOLD:
            silent_chunks += 1
        else:
            silent_chunks = 0

    with sd.InputStream(
        device=device_index,
        samplerate=SAMPLERATE,
        channels=CHANNELS,
        dtype="float32",
        blocksize=chunk_frames,
        callback=callback,
    ):
        while silent_chunks < chunks_for_silence:
            time.sleep(0.05)

    print("Silence detected. Stopped recording.")
    if not buffer:
        return np.zeros((0, CHANNELS), dtype="float32")
    return np.concatenate(buffer, axis=0)


def save_wav(audio: np.ndarray, path: str):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    sf.write(path, audio, SAMPLERATE)


def run_whisper(audio_path: str) -> str:
    os.makedirs(TRANSCRIPTS_DIR, exist_ok=True)
    result = subprocess.run(
        [
            "whisper", audio_path,
            "--device", "cuda",
            "--language", "English",
            "--model", "small",
            "--output_format", "txt",
            "--output_dir", TRANSCRIPTS_DIR,
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print("Whisper error:", result.stderr)
        return ""

    base = os.path.splitext(os.path.basename(audio_path))[0]
    txt_path = os.path.join(TRANSCRIPTS_DIR, base + ".txt")
    if not os.path.exists(txt_path):
        return ""
    with open(txt_path, "r", encoding="utf-8") as f:
        return f.read().strip()


def main():
    device_index = select_device()
    wav_path = os.path.join(RECORDINGS_DIR, "output.wav")

    print("\nPress Ctrl+C to quit.\n")
    try:
        while True:
            audio = record_until_silence(device_index)
            if audio.shape[0] == 0:
                print("No audio captured, retrying...")
                continue

            save_wav(audio, wav_path)
            print("Transcribing...")
            transcript = run_whisper(wav_path)
            if transcript:
                print(f"Transcript: {transcript}\n")
            else:
                print("(no transcript)\n")
    except KeyboardInterrupt:
        print("\nExiting.")


if __name__ == "__main__":
    main()
