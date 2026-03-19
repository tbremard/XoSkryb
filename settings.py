import json
import os


CONFIG_FILE = "XoSkryb.config"


class Settings:
    """Persists and restores device index and language to XoSkryb.config."""

    def __init__(self):
        self.device_index: int | None = None
        self.language:     str | None = None

    def load(self, get_input_devices, validate_device) -> bool:
        """
        Load settings from disk. Returns True if settings are valid and ready to use.
        get_input_devices and validate_device are injected to avoid circular imports.
        """
        if not os.path.exists(CONFIG_FILE):
            return False
        try:
            with open(CONFIG_FILE, "r") as f:
                cfg = json.load(f)
            idx      = int(cfg["device_index"])
            language = str(cfg["language"])
            valid    = {d["index"] for d in get_input_devices()}
            if idx not in valid:
                print(f"Saved device index {idx} no longer available.")
                return False
            if not validate_device(idx):
                print(f"Saved device index {idx} failed validation.")
                return False
            self.device_index = idx
            self.language     = language
            return True
        except Exception:
            return False

    def save(self, device_index: int, language: str):
        """Persist device index and language to disk."""
        self.device_index = device_index
        self.language     = language
        with open(CONFIG_FILE, "w") as f:
            json.dump({"device_index": device_index, "language": language}, f, indent=2)
