"""
run_backtest_halal.py — Backtest ETF CGF BRVMHalal
===================================================
Indice halal BRVM :
  - Univers : sous-ensemble Shariah-compliant de l'indice BRVMCI
  - Ponderation : market-cap (w_brvm30 renormalisé), SONATEL cappé à 35 %
  - Rebalancement : trimestriel (mêmes dates que le BRVMCI)
  - Frais : 0.6 %/an de gestion + 0.10 % spreads par rebalancement
  - Cash buffer : 1 %

Sorties :
  - data/rebal_detail.json
  - data/validation_results.json
"""

import os, sys, json, math
from datetime import date, timedelta

# ── Chemin racine ─────────────────────────────────────────────────────────── #
ROOT_DIR   = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
DATA_DIR   = os.path.join(ROOT_DIR, "data")
BRVMC_DIR  = os.path.normpath(os.path.join(ROOT_DIR, "..", "test_BRVMC", "data"))

# ── Paramètres ────────────────────────────────────────────────────────────── #
HALAL_TICKERS  = ["SNTS", "ORGT", "ONTBF", "CIEC", "SPHC", "TTLC", "SOGC", "PALC", "NEIC", "BNBC"]
TICKER_NAMES   = {
    "SNTS":  "SONATEL",
    "ORGT":  "ORANGE CI",
    "ONTBF": "ONATEL BF",
    "CIEC":  "CIE CI",
    "SPHC":  "SAPH CI",
    "TTLC":  "TOTAL CI",
    "SOGC":  "SOGB CI",
    "PALC":  "PALMINDUSTRIE CI",
    "NEIC":  "NESTLE CI",
    "BNBC":  "BERNABE CI",
}

CAP_SNTS       = 0.35     # 35 % max pour SONATEL
MIN_HALAL_W    = 0.005    # 0.5 % min poids dans le sous-indice halal
MGMT_FEE_ANN   = 0.006   # 0.6 %/an
SPREAD_COST    = 0.001    # 0.1 % aller-retour par rebalancement
CASH_BUFFER    = 0.01     # 1 % cash
AUM_START_MFCFA= 2500.0  # 2.5 Md FCFA
ADV_DAYS       = 63       # fenêtre ADV
MAX_ADV_MULT   = 20.0     # max 20 jours de liquidation
FILL_RATE      = 0.20     # max 20 % du volume journalier
RF_ANN         = 0.03     # 3 %/an (taux sans risque UEMOA)
NAV_BASE       = 1000.0

FEE_DAILY = (1.0 - MGMT_FEE_ANN) ** (1.0 / 252.0)
RF_DAILY  = (1.0 + RF_ANN)        ** (1.0 / 252.0) - 1.0


# ── Helpers ───────────────────────────────────────────────────────────────── #

def load_json(path):
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)

def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def compute_adv(sika_history, ref_date, n_days=ADV_DAYS):
    """ADV en MFCFA sur les n_days derniers jours ouvrés avant ref_date."""
    result = {}
    for tk, hist in sika_history.items():
        dates = sorted(d for d in hist if d < ref_date)[-n_days:]
        vals  = []
        for d in dates:
            e = hist[d]
            c = e.get("close", 0) if isinstance(e, dict) else e
            v = e.get("volume", 0) if isinstance(e, dict) else 0
            if c and v:
                vals.append(c * v / 1_000_000)
        result[tk] = sum(vals) / len(vals) if vals else 0.0
    return result


def compute_halal_weights(brvmc_raw_w, adv_map, aum_mfcfa):
    """
    brvmc_raw_w : {ticker: w_brvm30} pour les tickers BRVMCI à la date de rebal
    Retourne (w_halal_norm, w_etf, excluded) où :
      w_halal_norm = poids dans l'indice halal brut (avant cap ADV)
      w_etf        = poids ETF (après cap SNTS 35 % + cap ADV)
      excluded     = liste des tickers exclus avec leur w_halal_norm
    """
    # 1. Filtrer sur l'univers halal
    raw = {tk: brvmc_raw_w.get(tk, 0.0) for tk in HALAL_TICKERS if brvmc_raw_w.get(tk, 0.0) > 0}
    total_raw = sum(raw.values())
    if total_raw <= 0:
        return {}, {}, []

    # 2. Renormaliser dans l'univers halal
    norm = {tk: w / total_raw for tk, w in raw.items()}

    # 3. Exclure les tickers sous le seuil minimal
    filtered = {tk: w for tk, w in norm.items() if w >= MIN_HALAL_W}
    total_filt = sum(filtered.values())
    excluded_tickers = {tk: norm[tk] for tk in norm if tk not in filtered}
    if total_filt <= 0:
        return {}, {}, list(excluded_tickers.items())
    filtered = {tk: w / total_filt for tk, w in filtered.items()}

    # 4. Cap SNTS à 35 %
    w_halal = dict(filtered)
    if w_halal.get("SNTS", 0) > CAP_SNTS:
        excess = w_halal["SNTS"] - CAP_SNTS
        w_halal["SNTS"] = CAP_SNTS
        others = {tk: w for tk, w in w_halal.items() if tk != "SNTS"}
        tot_others = sum(others.values())
        if tot_others > 0:
            for tk in others:
                w_halal[tk] += excess * others[tk] / tot_others

    # w_halal est maintenant l'indice halal (renormalisé, SNTS cappé 35 %)
    w_halal_norm = dict(w_halal)

    # 5. Cap ADV (positions ETF)
    w_etf = dict(w_halal)
    for _ in range(10):
        overflow    = 0.0
        capped_tks  = set()
        for tk, w in list(w_etf.items()):
            adv = adv_map.get(tk, 0.0)
            if adv > 0:
                max_w = MAX_ADV_MULT * adv * FILL_RATE / aum_mfcfa
                if w > max_w:
                    overflow += w - max_w
                    w_etf[tk] = max_w
                    capped_tks.add(tk)
        if overflow <= 1e-9:
            break
        free = {tk: w for tk, w in w_etf.items() if tk not in capped_tks}
        tot_free = sum(free.values())
        if tot_free <= 0:
            break
        for tk in free:
            w_etf[tk] += overflow * free[tk] / tot_free

    # Renormaliser w_etf
    tot_etf = sum(w_etf.values())
    if tot_etf > 0:
        w_etf = {tk: w / tot_etf for tk, w in w_etf.items()}

    excluded_out = [
        {"ticker": tk, "w_halal": round(w, 6), "w_brvm30": round(brvmc_raw_w.get(tk, 0.0), 6)}
        for tk, w in excluded_tickers.items()
    ]

    return w_halal_norm, w_etf, excluded_out


# ── Simulation NAV ────────────────────────────────────────────────────────── #

T3_DAYS = 3  # jours de settlement BRVM

def build_nav(all_dates, rebal_dates, w_halal_history, w_etf_history, sika_history, div_history):
    """
    Retourne (nav_index_series, nav_etf_series, rebal_log)
    nav_index = indice halal brut (Total Return, avant frais — pas de T+3, index théorique)
    nav_etf   = VL ETF (après frais + cash buffer + drag T+3 settlement)

    Modélisation T+3 :
      Jour T (rebalancement) : ventes et achats simultanés.
      Jours T+1, T+2, T+3 : la portion vendue/achetée (turnover) est en transit —
      elle gagne le taux sans risque plutôt que le rendement du panier.
      Cela crée un drag sur l'ETF (pas sur l'indice théorique) et augmente la TE.
    """
    nav_index = NAV_BASE
    nav_etf   = NAV_BASE

    nav_index_series = {}
    nav_etf_series   = {}
    rebal_log        = {}

    rb_idx      = 0
    curr_w_idx  = {}
    curr_w_etf  = {}
    prev_date   = None
    total_to    = 0.0

    # {date: turnover_fraction_en_transit} — les 3 jours après chaque rebal
    t3_pending  = {}
    dates_set   = set(all_dates)

    for dt in all_dates:
        # Rebalancement trimestriel
        if rb_idx < len(rebal_dates) and dt >= rebal_dates[rb_idx]:
            rd = rebal_dates[rb_idx]
            new_w_idx = w_halal_history.get(rd, {})
            new_w_etf = w_etf_history.get(rd, {})
            if new_w_idx:
                if curr_w_etf:
                    all_tks  = set(new_w_etf) | set(curr_w_etf)
                    turnover = sum(abs(new_w_etf.get(t, 0) - curr_w_etf.get(t, 0)) for t in all_tks) / 2
                    cost     = turnover * SPREAD_COST
                    nav_index *= (1.0 - cost)
                    nav_etf   *= (1.0 - cost)
                    total_to  += turnover
                    # Marquer les T3_DAYS jours suivants comme en transit (settlement)
                    dt_idx = all_dates.index(dt)
                    for k in range(1, T3_DAYS + 1):
                        if dt_idx + k < len(all_dates):
                            future_d = all_dates[dt_idx + k]
                            t3_pending[future_d] = t3_pending.get(future_d, 0.0) + turnover
                else:
                    turnover, cost = 0.0, 0.0
                curr_w_idx = new_w_idx
                curr_w_etf = new_w_etf
                rebal_log[rd] = {
                    "turnover": round(turnover, 6),
                    "cost_bps": round(cost * 10_000, 1),
                }
            rb_idx += 1

        if not curr_w_idx or prev_date is None:
            prev_date = dt
            nav_index_series[dt] = round(nav_index, 4)
            nav_etf_series[dt]   = round(nav_etf,   4)
            continue

        # Rendement journalier du panier
        ret_idx = 0.0
        for tk, w in curr_w_idx.items():
            h  = sika_history.get(tk, {})
            e1 = h.get(dt)
            e0 = h.get(prev_date)
            p1 = (e1.get("close") if isinstance(e1, dict) else e1) if e1 else None
            p0 = (e0.get("close") if isinstance(e0, dict) else e0) if e0 else None
            if p1 and p0 and p0 > 0:
                ret_idx += w * (p1 / p0 - 1)

        div_contrib = _daily_div_contrib(dt, curr_w_idx, sika_history, div_history)
        ret_idx += div_contrib

        # Indice halal brut — pas de T+3 (index théorique, settlement instantané)
        nav_index = nav_index * (1.0 + ret_idx)

        # ETF : cash drag + frais + drag T+3
        t3_fraction = min(t3_pending.pop(dt, 0.0), 1.0)  # part du portefeuille en transit
        if t3_fraction > 0:
            # Portion en transit gagne RF au lieu du rendement panier
            ret_etf_basket  = (1.0 - t3_fraction) * ret_idx + t3_fraction * RF_DAILY
        else:
            ret_etf_basket  = ret_idx

        ret_etf = (1.0 - CASH_BUFFER) * ret_etf_basket + CASH_BUFFER * RF_DAILY
        nav_etf = nav_etf * (1.0 + ret_etf) * FEE_DAILY

        nav_index_series[dt] = round(nav_index, 4)
        nav_etf_series[dt]   = round(nav_etf,   4)
        prev_date = dt

    return nav_index_series, nav_etf_series, rebal_log, total_to


def _daily_div_contrib(dt, curr_w, sika_history, div_history):
    """
    Approximation TR : réinvestit les dividendes annuels au prorata des jours ouvrés.
    div_history["history"][ticker][annee] = montant FCFA/action
    """
    hist_data = div_history.get("history", {}) if isinstance(div_history, dict) else {}
    contrib   = 0.0
    yr        = dt[:4]
    for tk, w in curr_w.items():
        div_yr  = hist_data.get(tk, {}).get(yr, 0.0)
        if div_yr <= 0:
            continue
        sh   = sika_history.get(tk, {})
        # Prix approximatif = dernier prix connu
        dates_tk = sorted(d for d in sh if d <= dt)
        if not dates_tk:
            continue
        e    = sh[dates_tk[-1]]
        px   = (e.get("close") if isinstance(e, dict) else e) or 0
        if px <= 0:
            continue
        div_yield_ann = div_yr / px
        contrib += w * div_yield_ann / 252.0
    return contrib


# ── Calcul des métriques ──────────────────────────────────────────────────── #

def annualize(ret_total, n_years):
    if n_years <= 0:
        return 0.0
    return (1 + ret_total) ** (1.0 / n_years) - 1

def compute_metrics(nav_series, label=""):
    dates = sorted(nav_series.keys())
    if len(dates) < 2:
        return {}
    vals   = [nav_series[d] for d in dates]
    n_days = len(dates)
    n_yrs  = n_days / 252.0
    perf   = vals[-1] / vals[0] - 1
    ann    = annualize(perf, n_yrs)

    rets   = [(vals[i] / vals[i-1] - 1) for i in range(1, n_days)]
    mean_r = sum(rets) / len(rets) if rets else 0
    var_r  = sum((r - mean_r)**2 for r in rets) / len(rets) if rets else 0
    vol    = math.sqrt(var_r * 252)

    sharpe = (ann - RF_ANN) / vol if vol > 0 else 0.0

    rolling_max = vals[0]
    max_dd      = 0.0
    for v in vals:
        if v > rolling_max:
            rolling_max = v
        dd = (rolling_max - v) / rolling_max
        if dd > max_dd:
            max_dd = dd

    return {
        "perf_total_pct":     round(perf * 100, 2),
        "perf_ann_pct":       round(ann * 100,  2),
        "vol_ann_pct":        round(vol * 100,  2),
        "sharpe":             round(sharpe,      2),
        "max_drawdown_pct":   round(max_dd * 100, 2),
        "n_days":             n_days,
        "label":              label,
    }


# ── Programme principal ───────────────────────────────────────────────────── #

def main():
    print("=" * 60)
    print("  Backtest ETF CGF BRVMHalal")
    print("=" * 60)

    # ── Chargement données ────────────────────────────────────────────────── #
    sika_history = load_json(os.path.join(DATA_DIR, "sika_history.json")) or {}
    div_history  = load_json(os.path.join(DATA_DIR, "dividend_history.json")) or {}

    # Données BRVMCI pour les poids market-cap
    brvmc_rebal_path = os.path.join(BRVMC_DIR, "rebal_detail.json")
    brvmc_rebal = load_json(brvmc_rebal_path)
    if brvmc_rebal is None:
        print("[ERREUR] test_BRVMC/data/rebal_detail.json introuvable")
        sys.exit(1)

    print(f"[OK] sika_history : {len(sika_history)} tickers")
    print(f"[OK] rebal_detail BRVMCI : {len(brvmc_rebal.get('rebalancings',[]))} rebalancements")

    # ── Construire le calendrier de rebalancements ────────────────────────── #
    rebal_dates     = []
    brvmc_w_at_date = {}   # {date: {ticker: w_brvm30}}

    for rb in brvmc_rebal.get("rebalancings", []):
        if rb.get("skipped"):
            continue
        dt = rb.get("date", "")
        if not dt:
            continue
        # Collecter w_brvm30 pour tous les tickers BRVMCI
        w_map = {}
        for b in rb.get("basket", []):
            tk = b.get("ticker")
            w  = b.get("w_brvm30", 0.0)
            if tk:
                w_map[tk] = w
        for e in rb.get("excluded", []):
            tk = e.get("ticker")
            w  = e.get("w_brvm30", 0.0)
            if tk:
                w_map[tk] = w
        brvmc_w_at_date[dt] = w_map
        rebal_dates.append(dt)

    rebal_dates = sorted(set(rebal_dates))
    print(f"[OK] Dates de rebalancement halal : {rebal_dates[0]} -> {rebal_dates[-1]}")

    # ── Construire les poids halal à chaque date ──────────────────────────── #
    all_dates_set = set()
    for tk, hist in sika_history.items():
        all_dates_set.update(hist.keys())
    all_dates = sorted(all_dates_set)

    w_halal_history = {}
    w_etf_history   = {}
    rebal_detail_out = {"rebalancings": []}

    for rd in rebal_dates:
        brvmc_w = brvmc_w_at_date.get(rd, {})
        adv_map = compute_adv(sika_history, rd)
        # AUM approximatif à la date (ajusté si NAV a bougé — on utilise AUM_START pour simplifier)
        aum_approx = AUM_START_MFCFA

        w_halal_norm, w_etf, excluded = compute_halal_weights(brvmc_w, adv_map, aum_approx)

        if not w_halal_norm:
            print(f"  [WARN] {rd} : aucun ticker halal éligible — skip")
            continue

        w_halal_history[rd] = w_halal_norm
        w_etf_history[rd]   = w_etf

        # Construire le basket pour rebal_detail.json
        basket_out = []
        for tk, w_e in sorted(w_etf.items(), key=lambda x: -x[1]):
            e     = sika_history.get(tk, {})
            dates_tk = sorted(d for d in e if d <= rd)
            px = None
            if dates_tk:
                last = e[dates_tk[-1]]
                px = (last.get("close") if isinstance(last, dict) else last)
            adv = adv_map.get(tk, 0.0)
            basket_out.append({
                "ticker":     tk,
                "nom":        TICKER_NAMES.get(tk, tk),
                "w_brvm30":   round(w_halal_norm.get(tk, 0.0), 6),
                "w_etf":      round(w_e, 6),
                "capped":     bool(abs(w_e - w_halal_norm.get(tk, 0.0)) > 1e-4),
                "prix_rebal": round(px, 0) if px else None,
                "adv_mfcfa":  round(adv, 2),
            })

        rebal_detail_out["rebalancings"].append({
            "date":     rd,
            "skipped":  False,
            "basket":   basket_out,
            "excluded": excluded,
            "cap_snts": round(CAP_SNTS * 100, 1),
            "n_basket": len(basket_out),
        })

        snts_w = round(w_etf.get("SNTS", 0) * 100, 1)
        print(f"  {rd} : {len(basket_out)} titres | SNTS={snts_w}% | excl={len(excluded)}")

    # ── Simulation NAV ────────────────────────────────────────────────────── #
    print("\nSimulation NAV...")

    nav_idx, nav_etf, rebal_log, total_to = build_nav(
        all_dates, rebal_dates, w_halal_history, w_etf_history, sika_history, div_history
    )

    # ── Métriques ─────────────────────────────────────────────────────────── #
    m_idx = compute_metrics(nav_idx, "Indice Halal BRVM")
    m_etf = compute_metrics(nav_etf, "ETF CGF BRVMHalal")

    n_years = m_idx.get("n_days", 252) / 252.0
    td_gross = m_etf["perf_ann_pct"] - m_idx["perf_ann_pct"]

    # Tracking Error (ecart-type des rendements différentiels)
    dates_common = sorted(set(nav_idx) & set(nav_etf))
    diff_rets = []
    for i in range(1, len(dates_common)):
        r_idx = nav_idx[dates_common[i]] / nav_idx[dates_common[i-1]] - 1
        r_etf = nav_etf[dates_common[i]] / nav_etf[dates_common[i-1]] - 1
        diff_rets.append(r_etf - r_idx)
    mean_d = sum(diff_rets) / len(diff_rets) if diff_rets else 0
    var_d  = sum((r - mean_d)**2 for r in diff_rets) / len(diff_rets) if diff_rets else 0
    te_ann = math.sqrt(var_d * 252) * 100

    print(f"\n  Indice Halal : {m_idx['perf_ann_pct']:+.2f}%/an | vol={m_idx['vol_ann_pct']:.2f}% | dd={m_idx['max_drawdown_pct']:.2f}%")
    print(f"  ETF Net      : {m_etf['perf_ann_pct']:+.2f}%/an | vol={m_etf['vol_ann_pct']:.2f}% | dd={m_etf['max_drawdown_pct']:.2f}%")
    print(f"  TD (ETF-Idx) : {td_gross:+.2f}%/an")
    print(f"  TE           : {te_ann:.2f}%/an")
    print(f"  Turnover moy : {total_to/len(rebal_dates)*100:.2f}%/rebal")

    # ── Sauvegarder rebal_detail.json ─────────────────────────────────────── #
    rebal_detail_out["metadata"] = {
        "generated_at":  date.today().isoformat(),
        "aum_start_mfcfa": AUM_START_MFCFA,
        "cap_snts_pct":  CAP_SNTS * 100,
        "mgmt_fee_ann":  MGMT_FEE_ANN,
        "cash_buffer":   CASH_BUFFER,
    }

    # Enrichir avec rebal_log (turnover)
    for rb_item in rebal_detail_out["rebalancings"]:
        rd = rb_item["date"]
        log = rebal_log.get(rd, {})
        rb_item["turnover"] = log.get("turnover", 0.0)
        rb_item["cost_bps"] = log.get("cost_bps", 0.0)

    save_json(os.path.join(DATA_DIR, "rebal_detail.json"), rebal_detail_out)
    print("\n[OK] rebal_detail.json sauvegarde")

    # ── Sauvegarder validation_results.json ───────────────────────────────── #
    # Séries historiques
    nav_idx_list = [[d, round(nav_idx[d], 4)] for d in sorted(nav_idx)]
    nav_etf_list = [[d, round(nav_etf[d], 4)] for d in sorted(nav_etf)]

    # Perf par année
    perf_by_year = {}
    all_yr = sorted({d[:4] for d in nav_etf})
    for yr in all_yr:
        dates_yr = [d for d in sorted(nav_etf) if d.startswith(yr)]
        if len(dates_yr) < 2:
            continue
        r_etf = nav_etf[dates_yr[-1]] / nav_etf[dates_yr[0]] - 1
        r_idx = nav_idx.get(dates_yr[-1], nav_idx.get(dates_yr[0], nav_idx[dates_yr[0]])) / nav_idx.get(dates_yr[0], 1) - 1
        perf_by_year[yr] = {
            "etf_pct":   round(r_etf * 100, 2),
            "indice_pct": round(r_idx * 100, 2),
            "td_pct":    round((r_etf - r_idx) * 100, 2),
        }

    validation = {
        "generated_at":    date.today().isoformat(),
        "backtest_start":  all_dates[0],
        "backtest_end":    all_dates[-1],
        "metrics_indice":  m_idx,
        "metrics_etf":     m_etf,
        "tracking_difference_ann_pct": round(td_gross, 2),
        "tracking_error_ann_pct":      round(te_ann, 2),
        "total_turnover_rebal":        round(total_to, 4),
        "avg_turnover_per_rebal_pct":  round(total_to / max(len(rebal_dates), 1) * 100, 2),
        "perf_by_year":                perf_by_year,
        "nav_index_series":            nav_idx_list[-500:],
        "nav_etf_series":              nav_etf_list[-500:],
        "rebal_history":               [
            {
                "date":     rd,
                "turnover": rebal_log.get(rd, {}).get("turnover", 0.0),
                "cost_bps": rebal_log.get(rd, {}).get("cost_bps", 0.0),
            }
            for rd in rebal_dates if rd in rebal_log
        ],
    }

    save_json(os.path.join(DATA_DIR, "validation_results.json"), validation)
    print("[OK] validation_results.json sauvegarde")

    # ── Initialiser nav_latest.json ───────────────────────────────────────── #
    _init_nav_latest(w_etf_history, sika_history, rebal_dates, nav_etf)

    print("\n[DONE] Backtest termine.")


def _init_nav_latest(w_etf_history, sika_history, rebal_dates, nav_etf_series):
    """Initialise nav_latest.json avec le dernier rebalancement."""
    if not rebal_dates or not w_etf_history:
        return

    last_rd  = rebal_dates[-1]
    w_etf    = w_etf_history.get(last_rd, {})
    all_dates = sorted(nav_etf_series.keys())
    last_date = all_dates[-1] if all_dates else date.today().isoformat()

    # NAV indice à la dernière date
    nav_last = nav_etf_series.get(last_date, NAV_BASE)

    basket = []
    for tk, w in sorted(w_etf.items(), key=lambda x: -x[1]):
        sh = sika_history.get(tk, {})
        dates_tk = sorted(d for d in sh if d <= last_date)
        px = None
        lpd = None
        if dates_tk:
            lpd = dates_tk[-1]
            e = sh[lpd]
            px = (e.get("close") if isinstance(e, dict) else e)
        basket.append({
            "ticker":          tk,
            "poids_pct":       round(w * 100, 4),
            "dernier_prix":    round(px, 0) if px else None,
            "last_price_date": lpd,
        })

    # Série de VL historique
    nav_live_series = []
    for d in all_dates:
        if date.fromisoformat(d).weekday() < 5:
            nav_live_series.append([d, round(nav_etf_series[d], 0)])

    nl = {
        "calc_date":        last_date,
        "launched":         False,
        "nav_indice":       round(nav_last, 4),
        "vl_par_part_fcfa": 100000,
        "aum_mfcfa":        round(AUM_START_MFCFA, 1),
        "perf_since_launch": None,
        "change_day_pct":    None,
        "n_parts":          25000,
        "par_fcfa":         100000,
        "source":           "backtest",
        "basket":           basket,
        "nav_live_series":  nav_live_series[-500:],
        "rebal_date":       last_rd,
    }

    nav_path = os.path.join(DATA_DIR, "nav_latest.json")
    if not os.path.exists(nav_path):
        with open(nav_path, "w", encoding="utf-8") as f:
            json.dump(nl, f, ensure_ascii=False, indent=2)
        print(f"[OK] nav_latest.json initialisé (basket {len(basket)} titres, nav={nav_last:.2f})")
    else:
        print(f"[INFO] nav_latest.json déjà existant — non écrasé")


if __name__ == "__main__":
    main()
