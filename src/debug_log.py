"""Journal de débogage, conditionné par la variable d'environnement PI_DEBUG."""
import os

DEBUG = os.environ.get("PI_DEBUG", "").lower() in ("1", "true", "yes")


def _debug(msg: str) -> None:
    if DEBUG:
        print(f"[DEBUG] {msg}")