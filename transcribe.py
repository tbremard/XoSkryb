import sys
import os
import torch
import whisper


def transcribe(audio_file: str = "test.mp3") -> str:
    device = "cuda" if torch.cuda.is_available() else "cpu"
    model = whisper.load_model("small", device=device)
    result = model.transcribe(audio_file, language="english")
    return result["text"].strip()


if __name__ == "__main__":
    audio = sys.argv[1] if len(sys.argv) > 1 else "test.mp3"
    text = transcribe(audio)
    print(text)
