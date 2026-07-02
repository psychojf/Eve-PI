"""Debug logging gated by PI_DEBUG environment variable."""
import os

DEBUG = os.environ.get("PI_DEBUG", "").lower() in ("1", "true", "yes")


def _debug(msg: str) -> None:
    if DEBUG:
        print(f"[DEBUG] {msg}")