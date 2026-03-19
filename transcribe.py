import subprocess
import sys
import os


def transcribe(audio_file: str = "test.mp3") -> str:
    os.makedirs("Transcripts", exist_ok=True)

    result = subprocess.run(
        [
            "whisper", audio_file,
            "--device", "cuda",
            "--language", "English",
            "--model", "small",
            "--output_format", "txt",
            "--output_dir", "Transcripts",
        ],
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        print("Whisper error:", result.stderr)
        sys.exit(1)

    base = os.path.splitext(os.path.basename(audio_file))[0]
    txt_path = os.path.join("Transcripts", base + ".txt")

    with open(txt_path, "r", encoding="utf-8") as f:
        transcript = f.read().strip()

    return transcript


if __name__ == "__main__":
    audio = sys.argv[1] if len(sys.argv) > 1 else "test.mp3"
    text = transcribe(audio)
    print(text)
