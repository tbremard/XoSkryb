import sys
import time


class KeyboardController:
    """
    Abstracts keyboard injection and quit-key detection across platforms.

    Public interface:
        quit_key_pressed() -> bool
        type_text(text: str)

    Windows is fully implemented. macOS and Linux are TO BE DONE.
    """

    _INPUT_KEYBOARD    = 1
    _KEYEVENTF_UNICODE = 0x0004
    _KEYEVENTF_KEYUP   = 0x0002

    def __init__(self):
        self._platform = sys.platform
        if self._platform == "win32":
            self._init_windows()

    # ------------------------------------------------------------------
    # Windows — initialisation
    # ------------------------------------------------------------------

    def _init_windows(self):
        import ctypes
        import ctypes.wintypes as wintypes

        # All three union members must be present so ctypes computes the
        # correct struct size (MOUSEINPUT is the largest at 32 bytes on
        # 64-bit). Without them the union is undersized and SendInput reads
        # the event array at wrong offsets, silently dropping keystrokes.

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

        self._ctypes     = ctypes
        self._KEYBDINPUT = _KEYBDINPUT
        self._INPUT      = _INPUT
        self._INPUT_SIZE = ctypes.sizeof(_INPUT)
        self._send_input = ctypes.windll.user32.SendInput

    # ------------------------------------------------------------------
    # Public — quit-key detection
    # ------------------------------------------------------------------

    def quit_key_pressed(self) -> bool:
        """Return True if the user pressed X/x to request a graceful shutdown."""
        if self._platform == "win32":
            import msvcrt
            if msvcrt.kbhit():
                return msvcrt.getwch().lower() == "x"
            return False

        # TO BE DONE — macOS
        # Use select.select([sys.stdin], [], [], 0) combined with tty/termios
        # to poll for a keypress without blocking, then check for 'x'.

        # TO BE DONE — Linux
        # Same approach: select + tty/termios raw mode.

        return False

    # ------------------------------------------------------------------
    # Public — text injection
    # ------------------------------------------------------------------

    def type_text(self, text: str):
        """Inject text as keystrokes into the currently focused window."""
        if self._platform == "win32":
            self._type_windows(text)
        elif self._platform == "darwin":
            # TO BE DONE — macOS
            # Use pyobjc-framework-Quartz:
            #   pip install pyobjc-framework-Quartz
            #
            #   import Quartz
            #   event = Quartz.CGEventCreateKeyboardEvent(None, 0, True)
            #   Quartz.CGEventKeyboardSetUnicodeString(event, len(ch), ch)
            #   Quartz.CGEventPost(Quartz.kCGHIDEventTap, event)
            raise NotImplementedError("Keyboard injection not yet implemented for macOS.")
        else:
            # TO BE DONE — Linux (X11 or Wayland)
            # X11:     pip install python-xlib
            #          display.xtest_fake_input() with XStringToKeysym()
            # Wayland: pip install evdev
            #          UInput device, EV_KEY events
            raise NotImplementedError(
                f"Keyboard injection not yet implemented for {self._platform}."
            )

    # ------------------------------------------------------------------
    # Windows — implementation
    # ------------------------------------------------------------------

    def _type_windows(self, text: str):
        ctypes      = self._ctypes
        _KEYBDINPUT = self._KEYBDINPUT
        _INPUT      = self._INPUT
        chars = text + " "   # trailing space separates consecutive utterances
        for ch in chars:
            code   = ord(ch)
            events = []
            for flags in (self._KEYEVENTF_UNICODE,
                          self._KEYEVENTF_UNICODE | self._KEYEVENTF_KEYUP):
                inp    = _INPUT(type=self._INPUT_KEYBOARD)
                inp.ki = _KEYBDINPUT(wVk=0, wScan=code, dwFlags=flags,
                                     time=0, dwExtraInfo=0)
                events.append(inp)
            arr  = (_INPUT * len(events))(*events)
            sent = self._send_input(len(events), arr, self._INPUT_SIZE)
            if sent != len(events):
                print(f"[warn] SendInput: sent {sent}/{len(events)} events "
                      f"(WinError {ctypes.GetLastError()})")
            time.sleep(0.001)   # 1 ms between characters
