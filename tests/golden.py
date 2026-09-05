"""Capture chaque template généré, pour qu'un refactor puisse prouver qu'il n'a rien changé.

La génération n'est pas touchée par le travail sur les totaux de débit : chaque
template doit donc se sérialiser à l'octet près à l'identique avant et après.
Les échecs sont enregistrés eux aussi : une chaîne qui levait une exception
avant doit lever la même après.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.pi_data import CHAINS, PLANET_TYPES
from src.services.template_service import TemplateService

BASELINE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "baseline_golden.json")


def capture():
    """Génère chaque chaîne x produit x planète en CC5 et enregistre le résultat."""
    svc = TemplateService()
    out = {}
    for chain, info in sorted(CHAINS.items()):
        for product in sorted(info["recipes"]):
            for planet in sorted(PLANET_TYPES):
                key = f"{chain}|{product}|{planet}"
                try:
                    tpl = svc.generate({
                        "product_name": product,
                        "chain_name": chain,
                        "planet_type": planet,
                        "cc_level": 5,
                        "planet_diameter": 10000.0,
                        "layout": {},
                    })
                except Exception as exc:              # noqa: BLE001 - recording
                    out[key] = f"__RAISED__ {type(exc).__name__}: {exc}"
                    continue
                out[key] = tpl
    return out


def write_baseline():
    data = capture()
    with open(BASELINE, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=1, sort_keys=True, ensure_ascii=False)
    print(f"wrote {len(data)} entries to {BASELINE}")


def compare():
    """Renvoie la liste des clés dont la sortie a dérivé par rapport à la référence."""
    with open(BASELINE, encoding="utf-8") as fh:
        old = json.load(fh)
    new = capture()
    drift = []
    for key in sorted(set(old) | set(new)):
        a = json.dumps(old.get(key), sort_keys=True, ensure_ascii=False)
        b = json.dumps(new.get(key), sort_keys=True, ensure_ascii=False)
        if a != b:
            drift.append(key)
    return drift


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "compare":
        bad = compare()
        if bad:
            print(f"DRIFT in {len(bad)} entries:")
            for key in bad[:20]:
                print("  ", key)
            sys.exit(1)
        print("OK - all templates byte-identical")
    else:
        write_baseline()
