# XoSkryb — Claude Code Project Guide

## What this project is

XoSkryb is a real-time speech-to-text scribe for Windows. It listens continuously via microphone, detects speech using RMS amplitude gating, transcribes segments with OpenAI Whisper (Python API, CUDA-accelerated), and injects the result as keystrokes into whichever window has focus using the Windows `SendInput` API.

Designed and architected by **Thierry Brémard**.

---

## Project structure

```
XoScriber/
├── XoSkryb.py          # Main application — live dictation engine
├── transcribe.py       # Standalone one-shot file transcription utility (uses subprocess/CLI)
├── XoSkryb.languages   # Language menu config — uncomment to enable a language
├── XoSkryb.config      # Auto-generated: saved device index + language (JSON)
├── recordings/         # Temporary WAV segments (auto-deleted after transcription)
└── Transcripts/        # Whisper CLI output dir (used by transcribe.py)
```

---

## Architecture

### Dual-thread pipeline

- **Main thread** — audio capture loop (`sounddevice.InputStream`, 100 ms chunks, RMS gating). Two phases: WAITING → RECORDING → back to WAITING. Never blocks on transcription.
- **Worker thread** (`TranscriptionWorker`) — daemon thread pulling WAV paths from an unbounded `queue.Queue`. Transcribes with the pre-loaded Whisper model, types result via `SendInput`, deletes the WAV.

### Whisper integration

The Whisper model is loaded **once** at startup in `main()`:

```python
device = "cuda" if torch.cuda.is_available() else "cpu"
model = whisper.load_model("small", device=device)
```

The worker calls:

```python
result = model.transcribe(wav_path, language=language.lower())
transcript = result["text"].strip()
```

No subprocess is spawned per segment. `transcribe.py` is a separate standalone utility that still uses the Whisper CLI subprocess — this is intentional (different use case).

### Keyboard injection (Windows only)

Uses `ctypes` + `user32.SendInput` with `KEYEVENTF_UNICODE` events. One key-down + key-up per character, 1 ms sleep between characters. The `_INPUT` struct includes all three union members (`MOUSEINPUT`, `KEYBDINPUT`, `HARDWAREINPUT`) to ensure correct struct sizing on 64-bit Windows.

Stubs for macOS and Linux are present in the platform switch block at the top of `XoSkryb.py`.

---

## Key constants (XoSkryb.py)

| Constant | Default | Purpose |
|---|---|---|
| `SILENCE_THRESHOLD` | `0.02` | RMS below this = silence. Raise if keyboard noise triggers recording. |
| `SILENCE_DURATION` | `2.0` s | Continuous silence needed to close a recording segment. |
| `MIN_SPEECH_SEC` | `0.4` s | Minimum speech duration to queue for transcription. |
| `SAMPLERATE` | `16000` Hz | Audio sample rate (Whisper native rate). |
| `CHUNK_SEC` | `0.1` s | Audio callback chunk size. |

---

## Requirements

- Python 3.10 recommended
- PyTorch with CUDA build installed **before** Whisper (otherwise Whisper silently falls back to CPU)
- `pip install openai-whisper sounddevice soundfile numpy torch`

Verify GPU visibility before running:
```
python -c "import torch; print(torch.cuda.is_available(), torch.cuda.get_device_name(0))"
```

---

## Configuration files

- `XoSkryb.config` — JSON with `device_index` and `language`. Delete to re-run setup wizard.
- `XoSkryb.languages` — one language per line; lines starting with `#` are disabled.

---

## Running

```bash
python XoSkryb.py          # live dictation
python transcribe.py <file> # one-shot file transcription
```

Press **X** (while in the listening phase) or **Ctrl+C** to quit gracefully. Pending transcriptions are flushed before exit.
