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

import json
import os
import queue
import subprocess
import sys
import tempfile
import threading
import time
import numpy as np
import sounddevice as sd
import soundfile as sf

# ---------------------------------------------------------------------------
# Platform detection
# ---------------------------------------------------------------------------

_PLATFORM = sys.platform   # "win32" | "darwin" | "linux"

# ---------------------------------------------------------------------------
# Keyboard injection — platform-specific implementations
# ---------------------------------------------------------------------------

if _PLATFORM == "win32":

    import ctypes
    import ctypes.wintypes as wintypes
    import msvcrt

    def _quit_key_pressed() -> bool:
        """Return True if the user pressed X/x in the console (Windows)."""
        if msvcrt.kbhit():
            return msvcrt.getwch().lower() == "x"
        return False

    _INPUT_KEYBOARD    = 1
    _KEYEVENTF_UNICODE = 0x0004
    _KEYEVENTF_KEYUP   = 0x0002

    # All three union members must be present so ctypes computes the correct
    # struct size (MOUSEINPUT is the largest member at 32 bytes on 64-bit).
    # Without them the union is undersized and SendInput reads the event array
    # at wrong offsets, silently dropping all keystrokes.

    class _MOUSEINPUT(ctypes.Structure):
        _fields_ = [
            ("dx",          wintypes.LONG),
            ("dy",          wintypes.LONG),
            ("mouseData",   wintypes.DWORD),
            ("dwFlags",     wintypes.DWORD),
            ("time",        wintypes.DWORD),
            ("dwExtraInfo", ctypes.c_size_t),
        ]

    class _KEYBDINPUT(ctypes.Structure):
        _fields_ = [
            ("wVk",         wintypes.WORD),
            ("wScan",       wintypes.WORD),
            ("dwFlags",     wintypes.DWORD),
            ("time",        wintypes.DWORD),
            ("dwExtraInfo", ctypes.c_size_t),
        ]

    class _HARDWAREINPUT(ctypes.Structure):
        _fields_ = [
            ("uMsg",    wintypes.DWORD),
            ("wParamL", wintypes.WORD),
            ("wParamH", wintypes.WORD),
        ]

    class _INPUT_UNION(ctypes.Union):
        _fields_ = [
            ("mi", _MOUSEINPUT),
            ("ki", _KEYBDINPUT),
            ("hi", _HARDWAREINPUT),
        ]

    class _INPUT(ctypes.Structure):
        _anonymous_ = ("u",)
        _fields_    = [
            ("type", wintypes.DWORD),
            ("u",    _INPUT_UNION),
        ]

    _send_input = ctypes.windll.user32.SendInput
    _INPUT_SIZE = ctypes.sizeof(_INPUT)

    def type_into_active_window(text: str):
        """Type text into whatever window currently has keyboard focus (Windows)."""
        chars = text + " "   # trailing space separates consecutive utterances
        for ch in chars:
            code   = ord(ch)
            events = []
            for flags in (_KEYEVENTF_UNICODE, _KEYEVENTF_UNICODE | _KEYEVENTF_KEYUP):
                inp    = _INPUT(type=_INPUT_KEYBOARD)
                inp.ki = _KEYBDINPUT(wVk=0, wScan=code, dwFlags=flags,
                                     time=0, dwExtraInfo=0)
                events.append(inp)
            arr  = (_INPUT * len(events))(*events)
            sent = _send_input(len(events), arr, _INPUT_SIZE)
            if sent != len(events):
                print(f"[warn] SendInput: sent {sent}/{len(events)} events "
                      f"(WinError {ctypes.GetLastError()})")
            time.sleep(0.001)   # 1 ms between characters

elif _PLATFORM == "darwin":

    # -----------------------------------------------------------------------
    # macOS — quit-key detection — NOT YET IMPLEMENTED
    #
    # On macOS there is no direct equivalent of msvcrt.kbhit().
    # Options:
    #   - Use select.select([sys.stdin], [], [], 0) to poll stdin in raw mode
    #   - Use the 'tty' and 'termios' modules to switch the terminal to
    #     non-blocking / raw mode before polling, then restore it after
    # -----------------------------------------------------------------------

    def _quit_key_pressed() -> bool:
        return False   # TODO: implement for macOS

    # -----------------------------------------------------------------------
    # macOS — keyboard injection — NOT YET IMPLEMENTED
    #
    # To implement keyboard injection on macOS, use the Quartz / CoreGraphics
    # framework via the pyobjc-framework-Quartz package:
    #
    #   pip install pyobjc-framework-Quartz
    #
    # Then use CGEventCreateKeyboardEvent() to post Unicode key events:
    #
    #   import Quartz
    #   event = Quartz.CGEventCreateKeyboardEvent(None, 0, True)
    #   Quartz.CGEventKeyboardSetUnicodeString(event, len(ch), ch)
    #   Quartz.CGEventPost(Quartz.kCGHIDEventTap, event)
    #
    # Implement this logic inside type_into_active_window() below.
    # -----------------------------------------------------------------------

    def type_into_active_window(text: str):
        raise NotImplementedError(
            "Keyboard injection is not yet implemented for macOS.\n"
            "See the comment block above this function in XoSkryb.py for guidance."
        )

else:

    # -----------------------------------------------------------------------
    # Linux / other — quit-key detection — NOT YET IMPLEMENTED
    #
    # Use select.select([sys.stdin], [], [], 0) combined with tty/termios
    # to poll for a keypress without blocking, then check for 'x'.
    # -----------------------------------------------------------------------

    def _quit_key_pressed() -> bool:
        return False   # TODO: implement for Linux

    # -----------------------------------------------------------------------
    # Linux / other — keyboard injection — NOT YET IMPLEMENTED
    #
    # To implement keyboard injection on Linux, use the python-xlib package
    # (for X11) or the python-evdev package (for Wayland / direct input):
    #
    #   X11:    pip install python-xlib
    #           Use display.xtest_fake_input() with Xlib.X.KeyPress events
    #           and XStringToKeysym() to map Unicode characters to keysyms.
    #
    #   Wayland / evdev:  pip install evdev
    #                     Create a UInput device and emit KEY_* events via
    #                     ui.write(ecodes.EV_KEY, keycode, 1) / value=0.
    #
    # Implement this logic inside type_into_active_window() below.
    # -----------------------------------------------------------------------

    def type_into_active_window(text: str):
        raise NotImplementedError(
            "Keyboard injection is not yet implemented for this platform "
            f"({_PLATFORM}).\n"
            "See the comment block above this function in XoSkryb.py for guidance."
        )

SILENCE_THRESHOLD  = 0.02    # RMS below this = silence (raise if keyboard noise triggers recording)
SILENCE_DURATION   = 2.0     # Seconds of continuous silence to stop recording
MIN_SPEECH_SEC     = 0.4     # Minimum speech required before queuing for transcription
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


def load_settings() -> tuple[int, str] | tuple[None, None]:
    """Load saved device + language. Returns (None, None) if missing/invalid."""
    if not os.path.exists(CONFIG_FILE):
        return None, None
    try:
        with open(CONFIG_FILE, "r") as f:
            cfg = json.load(f)
        idx      = int(cfg["device_index"])
        language = str(cfg["language"])
        valid = {d["index"] for d in _get_input_devices()}
        if idx not in valid:
            print(f"Saved device index {idx} no longer available.")
            return None, None
        if not _validate_device(idx):
            print(f"Saved device index {idx} failed validation.")
            return None, None
        return idx, language
    except Exception:
        return None, None


def save_settings(index: int, language: str):
    with open(CONFIG_FILE, "w") as f:
        json.dump({"device_index": index, "language": language}, f, indent=2)


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

def wait_for_speech_then_record(device_index: int, stop_event: threading.Event) -> tuple[np.ndarray, float]:
    """
    Phase 1 – wait silently until speech is detected (RMS >= SILENCE_THRESHOLD).
              Pressing X during this phase sets stop_event and returns immediately.
    Phase 2 – record until SILENCE_DURATION seconds of continuous silence.
    Returns (audio_array, speech_seconds).
    """
    chunk_frames   = int(SAMPLERATE * CHUNK_SEC)
    chunks_silence = int(SILENCE_DURATION / CHUNK_SEC)

    state         = {"phase": "waiting"}   # "waiting" | "recording" | "done"
    buffer        = []
    silent_chunks = 0
    speech_chunks = 0

    def callback(indata, frames, time_info, status):
        nonlocal silent_chunks, speech_chunks
        chunk = indata.copy()
        rms   = float(np.sqrt(np.mean(chunk ** 2)))
        loud  = rms >= SILENCE_THRESHOLD

        if state["phase"] == "waiting":
            if loud:
                state["phase"] = "recording"
                silent_chunks  = 0
                buffer.append(chunk)
                speech_chunks  = 1

        elif state["phase"] == "recording":
            buffer.append(chunk)
            if loud:
                silent_chunks  = 0
                speech_chunks += 1
            else:
                silent_chunks += 1
                if silent_chunks >= chunks_silence:
                    state["phase"] = "done"

    print("Listening... (waiting for speech — press X to quit)")
    with sd.InputStream(
        device    = device_index,
        samplerate= SAMPLERATE,
        channels  = CHANNELS,
        dtype     = "float32",
        blocksize = chunk_frames,
        callback  = callback,
    ):
        while state["phase"] != "done":
            if state["phase"] == "waiting" and _quit_key_pressed():
                stop_event.set()
                break
            if state["phase"] == "recording":
                elapsed = len(buffer) * CHUNK_SEC
                print(f"\rRecording... {elapsed:.1f}s", end="", flush=True)
            time.sleep(0.05)

    print("\rSilence detected. Stopped.            ")

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

def _transcription_worker(seg_queue: queue.Queue, language: str):
    """
    Runs in a daemon thread.
    Pulls WAV file paths from seg_queue, transcribes each with Whisper,
    types the result into the currently focused window via clipboard paste,
    then cleans up the temporary files.

    Receives None as sentinel to stop.
    """
    os.makedirs(TRANSCRIPTS_DIR, exist_ok=True)

    while True:
        wav_path = seg_queue.get()
        try:
            if wav_path is None:      # sentinel — time to exit
                break

            result = subprocess.run(
                [
                    "whisper", wav_path,
                    "--device", "cuda",
                    "--language", language,
                    "--model", "small",
                    "--output_format", "txt",
                    "--output_dir", TRANSCRIPTS_DIR,
                ],
                capture_output=True,
                text=True,
            )

            stem     = os.path.splitext(os.path.basename(wav_path))[0]
            txt_path = os.path.join(TRANSCRIPTS_DIR, stem + ".txt")

            if result.returncode == 0 and os.path.exists(txt_path):
                with open(txt_path, "r", encoding="utf-8") as f:
                    transcript = f.read().strip()
                if transcript:
                    type_into_active_window(transcript)
                # Remove the Whisper output txt — we typed it, we're done with it
                try:
                    os.remove(txt_path)
                except OSError:
                    pass
            else:
                if result.returncode != 0:
                    print(f"\n[whisper error] {result.stderr[:200]}")

        except Exception as e:
            print(f"\n[transcription error] {e}")

        finally:
            # Always clean up the temporary WAV and mark item done —
            # including when wav_path is None (the sentinel).
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
        "║                           X o S k r y b                                 ║\n"
        "║                                                                          ║\n"
        "║                         by Thierry Brémard                               ║\n"
        "║                                                                          ║\n"
        "║              AI Real-Time Speech-to-Text Scribe for Windows              ║\n"
        "║           Inspired by the ancient Egyptian scribes of knowledge          ║\n"
        "║                                                                          ║\n"
        "╚══════════════════════════════════════════════════════════════════════════╝\n"
    )

    # Load saved settings or ask user
    device_index, language = load_settings()
    if device_index is not None:
        dev_name = sd.query_devices(device_index)["name"]
        print(f"Using saved device   : [{device_index}] {dev_name}")
        print(f"Using saved language : {language}")
        print(f"(Delete {CONFIG_FILE} to change these settings.)")
    else:
        device_index = select_device()
        language     = select_language()
        save_settings(device_index, language)
        print(f"\nSettings saved to {CONFIG_FILE}.")

    os.makedirs(RECORDINGS_DIR, exist_ok=True)

    # Start the background transcription thread
    seg_queue = queue.Queue()
    worker    = threading.Thread(
        target=_transcription_worker,
        args=(seg_queue, language),
        daemon=True,
        name="TranscriptionWorker",
    )
    worker.start()

    print("\nRecording is active. Focus the window you want text typed into.")
    print("Press X (while listening) or Ctrl+C to quit.\n")

    stop_event = threading.Event()

    try:
        while not stop_event.is_set():
            audio, speech_sec = wait_for_speech_then_record(device_index, stop_event)

            if stop_event.is_set():
                break

            if audio.shape[0] == 0 or speech_sec < MIN_SPEECH_SEC:
                print(f"(too short: {speech_sec:.2f}s — skipping)\n")
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
