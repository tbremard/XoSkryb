# ╔══════════════════════════════════════════════════════════════════════════╗
# ║                                                                          ║
# ║                           X o S k r y b                                  ║
# ║                                                                          ║
# ║                         by Thierry Brémard                               ║
# ║                               tiri@tiritix.com                           ║
# ║              AI Real-Time Speech-to-Text Scribe for Windows              ║
# ║           Inspired by the ancient Egyptian scribes of knowledge          ║
# ║                                                                          ║
# ╚══════════════════════════════════════════════════════════════════════════╝

import os
import queue
import tempfile
import threading
import time
from enum import Enum, auto
import numpy as np
import sounddevice as sd
import soundfile as sf
import torch
import whisper
from keyboard_controller import KeyboardController, Command
from settings import Settings, CONFIG_FILE

keyboard = KeyboardController()

class RecordingPhase(Enum):
    WAITING   = auto()
    RECORDING = auto()
    DONE      = auto()


SILENCE_THRESHOLD  = 0.02    # RMS below this = silence (raise if keyboard noise triggers recording)
SILENCE_DURATION   = 1.0     # Seconds of continuous silence to stop recording
MIN_SPEECH_SEC     = 0.4     # Minimum speech required before queuing for transcription
NOISE_CANCEL_CHUNKS = 2      # Consecutive silent chunks right after onset that cancel the recording
POST_RMS_THRESHOLD = 0.12    # Post-recording RMS below this = noise-only segment, skip transcription
POST_RMS_STEP      = 10      # Subsample stride for fast post-recording RMS estimate
SAMPLERATE         = 16000
CHANNELS           = 1
CHUNK_SEC          = 0.1     # Duration of each audio chunk (100 ms)
RECORDINGS_DIR     = "recordings"
TRANSCRIPTS_DIR    = "Transcripts"
CONFIG_FILE        = "XoSkryb.config"
LANGUAGES_CONF     = "XoSkryb.languages"


# ---------------------------------------------------------------------------
# Device helpers
# ---------------------------------------------------------------------------

def _get_input_devices() -> list[dict]:
    """Return all input devices, deduplicated by name (lowest index wins)."""
    seen_names: dict[str, dict] = {}
    for i, dev in enumerate(sd.query_devices()):
        if dev["max_input_channels"] < 1:
            continue
        name = dev["name"]
        if name not in seen_names:
            seen_names[name] = {"index": i, "name": name}
    return list(seen_names.values())


def _validate_device(index: int) -> bool:
    """Try opening a short stream to confirm the device actually works."""
    try:
        with sd.InputStream(device=index, samplerate=SAMPLERATE,
                            channels=CHANNELS, dtype="float32", blocksize=512):
            pass
        return True
    except Exception:
        return False


def list_input_devices():
    devices = _get_input_devices()
    print("\nAvailable input devices (deduplicated):")
    for d in devices:
        print(f"  [{d['index']}] {d['name']}")
    print()


def select_device() -> int:
    list_input_devices()
    devices = _get_input_devices()
    valid_indices = {d["index"] for d in devices}
    while True:
        try:
            idx = int(input("Select input device index: "))
        except ValueError:
            print("Please enter a number.")
            continue
        if idx not in valid_indices:
            print(f"Index {idx} not in the list above. Try again.")
            continue
        print(f"Validating device {idx}...", end=" ", flush=True)
        if _validate_device(idx):
            print("OK")
            return idx
        print("FAILED — device could not be opened. Try another.")



# ---------------------------------------------------------------------------
# Language helpers
# ---------------------------------------------------------------------------

def load_enabled_languages() -> list[str]:
    """Read XoSkryb.languages and return the uncommented language names."""
    if not os.path.exists(LANGUAGES_CONF):
        print(f"Warning: {LANGUAGES_CONF} not found — defaulting to English.")
        return ["English"]
    languages = []
    with open(LANGUAGES_CONF, "r", encoding="utf-8") as f:
        for line in f:
            stripped = line.strip()
            if stripped and not stripped.startswith("#"):
                languages.append(stripped)
    if not languages:
        print(f"Warning: no languages enabled in {LANGUAGES_CONF} — defaulting to English.")
        return ["English"]
    return languages


def select_language() -> str:
    languages = load_enabled_languages()
    print("\nAvailable languages (from XoSkryb.languages):")
    for i, lang in enumerate(languages, 1):
        print(f"  [{i}] {lang}")
    print()
    while True:
        try:
            choice = int(input("Select language number: "))
            if 1 <= choice <= len(languages):
                return languages[choice - 1]
            print(f"Please enter a number between 1 and {len(languages)}.")
        except ValueError:
            print("Please enter a number.")


# ---------------------------------------------------------------------------
# Recording  (main thread)
# ---------------------------------------------------------------------------

def wait_for_speech_then_record(device_index: int, stop_event: threading.Event, pause_event: threading.Event) -> tuple[np.ndarray, float]:
    """
    Phase 1 – wait silently until speech is detected (RMS >= SILENCE_THRESHOLD).
              Pressing X during this phase sets stop_event and returns immediately.
    Phase 2 – record until SILENCE_DURATION seconds of continuous silence.
    Returns (audio_array, speech_seconds).
    """
    chunk_frames   = int(SAMPLERATE * CHUNK_SEC)
    chunks_silence = int(SILENCE_DURATION / CHUNK_SEC)
    phase         = RecordingPhase.WAITING
    buffer        = []
    silent_chunks = 0
    speech_chunks = 0
    onset_silent  = 0   # consecutive silent chunks seen right after the trigger chunk
    #-------------------------------
    def callback(indata, frames, time_info, status):
        nonlocal phase, silent_chunks, speech_chunks, onset_silent
        chunk = indata.copy()
        rms   = float(np.sqrt(np.mean(chunk ** 2)))
        loud  = rms >= SILENCE_THRESHOLD

        if phase == RecordingPhase.WAITING:
            if loud:
                phase          = RecordingPhase.RECORDING
                silent_chunks  = 0
                onset_silent   = 0
                buffer.append(chunk)
                speech_chunks  = 1

        elif phase == RecordingPhase.RECORDING:
            buffer.append(chunk)
            if loud:
                silent_chunks = 0
                onset_silent  = 0
                speech_chunks += 1
            else:
                silent_chunks += 1
                if speech_chunks == 1:
                    # Confirmation window: still only the trigger chunk — check for noise spike.
                    onset_silent += 1
                    if onset_silent >= NOISE_CANCEL_CHUNKS:
                        # Silence immediately after trigger → noise spike, ignore it.
                        phase         = RecordingPhase.WAITING
                        buffer.clear()
                        silent_chunks = 0
                        speech_chunks = 0
                        onset_silent  = 0
                elif silent_chunks >= chunks_silence:
                    phase = RecordingPhase.DONE
    #-------------------------------
    print("Listening... (waiting for speech — Space to pause, X to quit)")
    with sd.InputStream(
        device    = device_index,
        samplerate= SAMPLERATE,
        channels  = CHANNELS,
        dtype     = "float32",
        blocksize = chunk_frames,
        callback  = callback,
    ):
        while phase != RecordingPhase.DONE:
            if phase == RecordingPhase.WAITING:
                cmd = keyboard.poll_command()
                if cmd == Command.EXIT:
                    stop_event.set()
                    break
                if cmd == Command.PAUSE:
                    pause_event.set()
                    break
            if phase == RecordingPhase.RECORDING:
                elapsed = len(buffer) * CHUNK_SEC
                print(f"\rRecording... {elapsed:.1f}s", end="", flush=True)
            time.sleep(0.05)

    #-------------------------------
    print(f"\rRecording stopped — {len(buffer) * CHUNK_SEC:.1f}s captured.")
    if not buffer:
        return np.zeros((0, CHANNELS), dtype="float32"), 0.0
    audio      = np.concatenate(buffer, axis=0)
    speech_sec = speech_chunks * CHUNK_SEC
    return audio, speech_sec


def save_wav(audio: np.ndarray, path: str):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    sf.write(path, audio, SAMPLERATE)

# ---------------------------------------------------------------------------
# Transcription worker  (background thread)
# ---------------------------------------------------------------------------

def _transcription_worker(seg_queue: queue.Queue, language: str, model):
    """
    Runs in a daemon thread.
    Pulls WAV file paths from seg_queue, transcribes each with the
    pre-loaded Whisper model (in-process, GPU-accelerated), types the
    result into the currently focused window, then deletes the WAV.

    Receives None as sentinel to stop.
    """
    while True:
        wav_path = seg_queue.get()
        try:
            if wav_path is None:      # sentinel — time to exit
                break
            result     = model.transcribe(wav_path, language=language.lower())
            transcript = result["text"].strip()
            if transcript:
                keyboard.type_text(transcript)
        except Exception as e:
            print(f"\n[transcription error] {e}")
        finally:
            # Always clean up the temporary WAV and mark item done.
            if wav_path is not None:
                try:
                    os.remove(wav_path)
                except OSError:
                    pass
            seg_queue.task_done()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    print(
        "\n"
        "╔══════════════════════════════════════════════════════════════════════════╗\n"
        "║                                                                          ║\n"
        "║                           X o S k r y b                                  ║\n"
        "║                                                                          ║\n"
        "║                         by Thierry Brémard                               ║\n"
        "║                                                                          ║\n"
        "║              AI Real-Time Speech-to-Text Scribe for Windows              ║\n"
        "║           Inspired by the ancient Egyptian scribes of knowledge          ║\n"
        "║                                                                          ║\n"
        "╚══════════════════════════════════════════════════════════════════════════╝\n"
    )

    # Load saved settings or ask user
    _settings = Settings()
    if _settings.load(_get_input_devices, _validate_device):
        dev_name = sd.query_devices(_settings.device_index)["name"]
        print(f"Using saved device   : [{_settings.device_index}] {dev_name}")
        print(f"Using saved language : {_settings.language}")
        print(f"(Delete {CONFIG_FILE} to change these settings.)")
    else:
        _settings.save(select_device(), select_language())
        print(f"\nSettings saved to {CONFIG_FILE}.")
    device_index = _settings.device_index
    language     = _settings.language
    os.makedirs(RECORDINGS_DIR, exist_ok=True)
    # Load Whisper model once — reused for every segment (no per-segment startup cost).
    if torch.cuda.is_available():
        device = "cuda"
    else:
        device = "cpu"
        print("\n⚠️  CUDA is not available: I will do your work but slower.")
        print("    For me to work faster, if you have an NVidia card, open the README.md file.\n")
    print(f"Loading Whisper model on {device.upper()}...", end=" ", flush=True)
    model = whisper.load_model("small", device=device)
    print("ready.")
    # Start the background transcription thread
    seg_queue = queue.Queue()
    worker    = threading.Thread(
        target=_transcription_worker,
        args=(seg_queue, language, model),
        daemon=True,
        name="TranscriptionWorker",
    )
    worker.start()
    print("\nRecording is active. Focus the window you want text typed into.")
    print("Press Space to pause/resume, X to quit, Ctrl+C to force quit.\n")
    stop_event  = threading.Event()
    pause_event = threading.Event()
    try:
        while not stop_event.is_set():
            audio, speech_sec = wait_for_speech_then_record(device_index, stop_event, pause_event)
            if stop_event.is_set():
                break
            if pause_event.is_set():
                pause_event.clear()
                print("\n*** PAUSED — press Space to resume, X to quit ***")
                while True:
                    cmd = keyboard.poll_command()
                    if cmd == Command.PAUSE:
                        print("*** RESUMED ***\n")
                        break
                    if cmd == Command.EXIT:
                        stop_event.set()
                        break
                    time.sleep(0.05)
                continue
            if audio.shape[0] == 0 or speech_sec < MIN_SPEECH_SEC:
                print(f"(too short: {speech_sec:.2f}s — skipping)\n")
                continue
            # Fast post-recording energy check — subsample to avoid processing
            # the full array.  Rejects noise-only segments before Whisper.
            subsampled = audio[::POST_RMS_STEP, 0] if audio.ndim > 1 else audio[::POST_RMS_STEP]
            post_rms = float(np.sqrt(np.mean(subsampled ** 2)))
            print(f"(post-RMS: {post_rms:.4f})")
            if post_rms < POST_RMS_THRESHOLD:
                print(f"(noise only: RMS {post_rms:.4f} < {POST_RMS_THRESHOLD} — skipping)\n")
                continue
            # Save segment to a unique temp file so the worker and the
            # recording loop never touch the same file simultaneously.
            fd, wav_path = tempfile.mkstemp(suffix=".wav", dir=RECORDINGS_DIR)
            os.close(fd)
            save_wav(audio, wav_path)
            seg_queue.put(wav_path)
            print(f"(segment queued — {speech_sec:.1f}s of speech, "
                  f"{seg_queue.qsize()} in queue)")
            # Main thread immediately loops back to listening
    except KeyboardInterrupt:
        pass
    print("\nStopping — waiting for pending transcriptions...")
    seg_queue.put(None)   # signal worker to exit after draining queue
    seg_queue.join()      # wait until all queued items are processed
    print("Done.")

if __name__ == "__main__":
    main()
