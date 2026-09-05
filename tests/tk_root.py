"""Une seule racine Tk pour toute la session de tests.

Créer un second `tk.Tk()` après en avoir détruit un premier dans le même
processus échoue par intermittence : « invalid command name tcl_findLibrary ».
Les classes concernées se sautent alors, parce que leur `setUpClass` prend cet
échec pour une absence d'affichage — et un test sauté ne se lit pas comme un
test cassé. Observé quatre fois sur douze exécutions du jour : les tests
n'avaient pas disparu du rapport, ils avaient seulement cessé de tourner.

La racine est donc créée une fois et jamais détruite. Elle meurt avec le
processus, ce qui est exactement la durée de vie qu'on veut ici.
"""
import tkinter as tk
import unittest

_ROOT = None
_FAILED = None


def shared_root(geometry=None):
    """La racine Tk de la session, en la créant à la première demande.

    Lève SkipTest s'il n'y a réellement pas d'affichage — le cas que le garde
    d'origine cherchait à couvrir. Mémorisé : sans ça, chaque classe
    retenterait une création qu'on sait vouée à échouer.
    """
    global _ROOT, _FAILED
    if _FAILED is not None:
        raise unittest.SkipTest(f"no display: {_FAILED}")
    if _ROOT is None:
        try:
            _ROOT = tk.Tk()
        except tk.TclError as exc:
            _FAILED = exc
            raise unittest.SkipTest(f"no display: {exc}") from exc
        _ROOT.title("PI tests — offscreen")
        # Hors champ, pas retirée. `withdraw()` la cacherait aussi, mais une
        # fenêtre non affichée ne dispose plus ses widgets : `winfo_width()`
        # rendrait 1, et les contrôles qui mesurent un canvas — la planète
        # centrée, la grille de cartes — mesureraient un pixel.
        #
        # Elle ne mourait plus depuis qu'elle est partagée, donc elle restait
        # affichée pendant toute la suite au lieu de clignoter : signalé comme
        # « what is that damn window », et à juste titre.
        _ROOT.geometry("+-4000+-4000")
    if geometry:
        _ROOT.geometry(geometry)
    _ROOT.update_idletasks()
    return _ROOT
