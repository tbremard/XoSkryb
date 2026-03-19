import sys
import torch
import whisper

AUDIO_FILE    = "test.mp3"
EXPECTED_TEXT = "Hello, this is a test."


def main():
    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"Loading Whisper model on {device.upper()}...")
    model = whisper.load_model("small", device=device)

    print(f"Transcribing {AUDIO_FILE}...")
    result = model.transcribe(AUDIO_FILE, language="english")
    transcript = result["text"].strip()

    print(f"Transcript : {transcript!r}")
    print(f"Expected   : {EXPECTED_TEXT!r}")

    if EXPECTED_TEXT.lower() in transcript.lower():
        print("PASS")
        sys.exit(0)
    else:
        print("FAIL — expected text not found in transcript")
        sys.exit(1)


if __name__ == "__main__":
    main()
