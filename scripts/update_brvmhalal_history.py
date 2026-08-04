"""
update_brvmhalal_history.py — Met à jour brvmhalal_index_history.json
Ajoute la valeur quotidienne de nav_indice_reference (indice halal sans frictions).
"""
import os, json, sys
from datetime import datetime, timezone

ROOT_DIR  = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
DATA_DIR  = os.path.join(ROOT_DIR, "data")

NAV_PATH      = os.path.join(DATA_DIR, "nav_latest.json")
HIST_PATH     = os.path.join(DATA_DIR, "brvmhalal_index_history.json")
LAUNCH_PATH   = os.path.join(DATA_DIR, "launch_state.json")


def main():
    if not os.path.exists(NAV_PATH):
        print("[ERREUR] nav_latest.json introuvable")
        sys.exit(1)

    with open(NAV_PATH, encoding="utf-8") as f:
        nl = json.load(f)

    calc_date  = nl.get("calc_date") or nl.get("date")
    nav_ref    = nl.get("nav_indice_reference") or nl.get("nav_indice")

    if not calc_date or not nav_ref:
        print("[ERREUR] calc_date ou nav_indice_reference manquant dans nav_latest.json")
        sys.exit(1)

    # Charger l'historique existant
    hist = {}
    if os.path.exists(HIST_PATH):
        with open(HIST_PATH, encoding="utf-8") as f:
            hist = json.load(f)

    hist[calc_date] = round(float(nav_ref), 4)

    with open(HIST_PATH, "w", encoding="utf-8") as f:
        json.dump(hist, f, ensure_ascii=False, indent=2)
    print(f"[OK] brvmhalal_index_history.json mis à jour : {calc_date} = {nav_ref:.4f}")

    # Ajouter brvmhalal_index_at_launch dans launch_state.json si absent
    if os.path.exists(LAUNCH_PATH):
        with open(LAUNCH_PATH, encoding="utf-8") as f:
            ls = json.load(f)
        if not ls.get("brvmhalal_index_at_launch"):
            launch_date = ls.get("launch_date")
            val = hist.get(launch_date) or float(nav_ref)
            ls["brvmhalal_index_at_launch"] = val
            with open(LAUNCH_PATH, "w", encoding="utf-8") as f:
                json.dump(ls, f, ensure_ascii=False, indent=2)
            print(f"[OK] brvmhalal_index_at_launch = {val} ajouté à launch_state.json")


if __name__ == "__main__":
    main()
