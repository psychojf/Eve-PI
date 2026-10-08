"""Journal de débogage, conditionné par la variable d'environnement PI_DEBUG."""
import os

DEBUG = os.environ.get("PI_DEBUG", "").lower() in ("1", "true", "yes")


def _debug(msg: str) -> None:
    """Écrit une ligne sur la console, seulement quand PI_DEBUG est posée.

    Muet par défaut : l'exe tourne sans console, et les appelants passent par
    ici plutôt que par `print` pour qu'une trace de diagnostic ne coûte rien en
    usage normal.
    """
    if DEBUG:
        print(f"[DEBUG] {msg}")