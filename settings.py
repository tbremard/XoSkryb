import json
import os


CONFIG_FILE = "XoSkryb.config"


DEFAULT_RMS_THRESHOLD = 0.02


class Settings:
    """Persists and restores device index, language, and rms_threshold to XoSkryb.config."""

    def __init__(self):
        self.device_index:  int | None   = None
        self.language:      str | None   = None
        self.rms_threshold: float        = DEFAULT_RMS_THRESHOLD

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
            self.device_index  = idx
            self.language      = language
            self.rms_threshold = float(cfg.get("rms_threshold", DEFAULT_RMS_THRESHOLD))
            return True
        except Exception:
            return False

    def save(self):
        """Persist current settings to disk."""
        with open(CONFIG_FILE, "w") as f:
            json.dump(
                {
                    "device_index":  self.device_index,
                    "language":      self.language,
                    "rms_threshold": self.rms_threshold,
                },
                f,
                indent=2,
            )
