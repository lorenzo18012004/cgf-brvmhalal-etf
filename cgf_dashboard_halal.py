"""
CGF BRVMHalal ETF — Dashboard Streamlit
========================================
ETF islamique BRVM — univers Shariah-compliant, SONATEL cappé à 35 %
"""
import os, json, math
from datetime import datetime, timezone, date

import streamlit as st
import pandas as pd
import plotly.graph_objects as go

# ── Config page ──────────────────────────────────────────────────────────── #
st.set_page_config(
    page_title="CGF BRVMHalal ETF",
    page_icon="☪",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ── Chemins ──────────────────────────────────────────────────────────────── #
DATA_DIR = os.path.join(os.path.dirname(__file__), "data")


# ── Helpers ──────────────────────────────────────────────────────────────── #
@st.cache_data(ttl=300)
def load_json(path, default=None):
    if not os.path.exists(path):
        return default
    with open(path, encoding="utf-8") as f:
        return json.load(f)

def load_json_fresh(path, default=None):
    if not os.path.exists(path):
        return default
    with open(path, encoding="utf-8") as f:
        return json.load(f)

def fmt_pct(v, decimals=2):
    if v is None:
        return "—"
    return f"{v:+.{decimals}f}%"

def fmt_num(v, decimals=0):
    if v is None:
        return "—"
    return f"{v:,.{decimals}f}"

def _section(title):
    st.markdown(f"""
    <div style="border-top:2px solid #b8973f;margin:28px 0 12px 0;padding-top:8px">
      <span style="font-size:11px;font-weight:700;letter-spacing:2px;color:#b8973f;text-transform:uppercase">{title}</span>
    </div>""", unsafe_allow_html=True)

# ── CSS ───────────────────────────────────────────────────────────────────── #
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap');
*, .stApp { font-family: 'Inter', sans-serif !important; }
.stApp { background: #f7f8fa; }
.block-container { padding: 2rem 2.5rem 3rem; max-width: 1300px; }
div[data-testid="metric-container"] {
  background: #fff; border-radius: 10px; padding: 16px 20px;
  border: 1px solid #e5e7eb; box-shadow: 0 1px 3px rgba(0,0,0,.05);
}
div[data-testid="metric-container"] > label { font-size: 10px !important; color: #6b7280 !important; letter-spacing: 1.5px; text-transform: uppercase; }
div[data-testid="metric-container"] > div { font-size: 22px !important; font-weight: 700 !important; color: #0c1a2e !important; }
h1 { color: #0c1a2e !important; font-weight: 700 !important; }
</style>
""", unsafe_allow_html=True)

# ── En-tête ───────────────────────────────────────────────────────────────── #
col_logo, col_title = st.columns([1, 5])
with col_logo:
    st.markdown("""
    <div style="background:#0c1a2e;color:#b8973f;border-radius:10px;
         padding:12px 16px;text-align:center;font-weight:700;font-size:22px;
         letter-spacing:1px;margin-top:4px">
      ☪ CGF
    </div>""", unsafe_allow_html=True)
with col_title:
    st.markdown("""
    <h1 style="margin:0;font-size:28px">CGF BRVMHalal ETF</h1>
    <p style="margin:2px 0 0;color:#6b7280;font-size:13px">
      Indice islamique BRVM &mdash; univers Shariah-compliant &mdash; SONATEL cappé 35 %
    </p>""", unsafe_allow_html=True)

st.markdown("---")

# ── Données ───────────────────────────────────────────────────────────────── #
nl      = load_json_fresh(os.path.join(DATA_DIR, "nav_latest.json"))
launch  = load_json_fresh(os.path.join(DATA_DIR, "launch_state.json"))
val     = load_json(os.path.join(DATA_DIR, "validation_results.json"))
rebal   = load_json(os.path.join(DATA_DIR, "rebal_detail.json"))
intra   = load_json_fresh(os.path.join(DATA_DIR, "intraday_nav.json"))

launched     = nl.get("launched", False) if nl else False
launch_date  = (launch or {}).get("launch_date")
calc_date    = (nl or {}).get("calc_date", "—")

# ── Métriques principales ─────────────────────────────────────────────────── #
_section("Valeur Liquidative")

vl   = (nl or {}).get("vl_par_part_fcfa")
aum  = (nl or {}).get("aum_mfcfa")
chg  = (nl or {}).get("change_day_pct")
perf = (nl or {}).get("perf_since_launch")
nav_idx = (nl or {}).get("nav_indice")
n_parts = (nl or {}).get("n_parts", 25000)

nav_anch = float((launch or {}).get("nav_index_at_launch") or 100)
par_fcfa = float((launch or {}).get("par_fcfa") or 100000)

c1, c2, c3, c4, c5 = st.columns(5)
with c1:
    vl_disp = f"{int(vl):,} FCFA" if vl else "—"
    st.metric("VL par part", vl_disp)
with c2:
    chg_d = fmt_pct(chg)
    st.metric("Variation jour", chg_d)
with c3:
    st.metric("AUM (M FCFA)", fmt_num(aum, 1) if aum else "—")
with c4:
    perf_d = fmt_pct(perf) if launched else "Non lancé"
    st.metric("Perf. depuis lancement", perf_d)
with c5:
    st.metric("Dernière MAJ", calc_date)

if not launched:
    ldt = launch_date or "—"
    st.info(f"ETF pas encore lancé — lancement prévu le {ldt}. Les données affichées sont issues du backtest.")

# ── Performance historique ────────────────────────────────────────────────── #
_section("Performance historique")

nav_series = (nl or {}).get("nav_live_series", [])
val_idx    = (val or {}).get("nav_index_series", [])
val_etf    = (val or {}).get("nav_etf_series", [])

if val_etf:
    # Backtest + live
    df_etf = pd.DataFrame(val_etf, columns=["date", "nav"]).set_index("date")
    df_idx = pd.DataFrame(val_idx, columns=["date", "nav"]).set_index("date") if val_idx else None

    # Normaliser à 100
    base_etf = df_etf["nav"].iloc[0]
    base_idx = df_idx["nav"].iloc[0] if df_idx is not None else base_etf

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=df_etf.index, y=(df_etf["nav"] / base_etf * 100).round(2),
        name="ETF CGF BRVMHalal (net)", line=dict(color="#b8973f", width=2),
    ))
    if df_idx is not None:
        fig.add_trace(go.Scatter(
            x=df_idx.index, y=(df_idx["nav"] / base_idx * 100).round(2),
            name="Indice Halal BRVM (brut)", line=dict(color="#0c1a2e", width=1.5, dash="dot"),
        ))
    fig.update_layout(
        height=380, margin=dict(l=0, r=0, t=10, b=0),
        plot_bgcolor="#fff", paper_bgcolor="#fff",
        legend=dict(orientation="h", y=-0.12),
        xaxis=dict(showgrid=False), yaxis=dict(showgrid=True, gridcolor="#f0f0f0"),
        hovermode="x unified",
    )
    fig.update_yaxes(title_text="Base 100")
    st.plotly_chart(fig, use_container_width=True)
else:
    st.info("Aucune série de performance disponible.")

# ── Métriques backtest ────────────────────────────────────────────────────── #
if val:
    _section("Métriques backtest")
    m_etf = val.get("metrics_etf", {})
    m_idx = val.get("metrics_indice", {})
    td    = val.get("tracking_difference_ann_pct")
    te    = val.get("tracking_error_ann_pct")
    to    = val.get("avg_turnover_per_rebal_pct")

    cols = st.columns(6)
    labels = [
        ("Perf. ETF/an", fmt_pct(m_etf.get("perf_ann_pct"))),
        ("Perf. Indice/an", fmt_pct(m_idx.get("perf_ann_pct"))),
        ("Tracking Diff.", fmt_pct(td)),
        ("Tracking Error", f"{te:.2f}%" if te else "—"),
        ("Vol. annualisée", f"{m_etf.get('vol_ann_pct', 0):.2f}%" if m_etf else "—"),
        ("Max Drawdown", f"-{m_etf.get('max_drawdown_pct', 0):.2f}%" if m_etf else "—"),
    ]
    for col, (lbl, val_txt) in zip(cols, labels):
        with col:
            st.metric(lbl, val_txt)

    # Perf par année
    perf_by_yr = val.get("perf_by_year", {})
    if perf_by_yr:
        st.markdown("**Performance par année**")
        rows = []
        for yr, p in sorted(perf_by_yr.items()):
            rows.append({
                "Année": yr,
                "ETF (%)": f"{p['etf_pct']:+.2f}%",
                "Indice (%)": f"{p['indice_pct']:+.2f}%",
                "TD (%)": f"{p['td_pct']:+.2f}%",
            })
        df_yr = pd.DataFrame(rows).set_index("Année")

        def _color_td(val):
            try:
                v = float(val.replace("%", "").replace("+", ""))
                return f"color: {'#2d7a4f' if v >= 0 else '#c0392b'}"
            except Exception:
                return ""

        st.dataframe(
            df_yr.style.applymap(_color_td, subset=["TD (%)"]),
            use_container_width=True, height=min(200, 40 + 35 * len(rows))
        )

# ── Composition du portefeuille ───────────────────────────────────────────── #
_section("Composition du portefeuille")

if nl and nl.get("basket"):
    df_basket = pd.DataFrame(nl["basket"])

    # Ajouter poids cible depuis dernier rebalancement
    _rebals = [r for r in (rebal or {}).get("rebalancings", []) if not r.get("skipped") and r.get("basket")]
    _last_rb = _rebals[-1] if _rebals else {}
    _w_cible = {b["ticker"]: round(b.get("w_etf", 0) * 100, 4) for b in _last_rb.get("basket", [])}
    _w_halal = {b["ticker"]: round(b.get("w_brvm30", 0) * 100, 4) for b in _last_rb.get("basket", [])}

    rows = []
    for _, r in df_basket.iterrows():
        rows.append({
            "Ticker":           r["ticker"],
            "Poids live (%)":   round(r["poids_pct"], 2),
            "Cible ETF (%)":    _w_cible.get(r["ticker"], "—"),
            "Indice Halal (%)": _w_halal.get(r["ticker"], "—"),
            "Dernier prix":     f"{int(r['dernier_prix']):,}" if r.get("dernier_prix") else "—",
        })

    df_out = pd.DataFrame(rows)
    st.dataframe(df_out, use_container_width=True, height=300, hide_index=True)

    # Graphique composition (camembert)
    fig_pie = go.Figure(go.Pie(
        labels=[r["Ticker"] for r in rows],
        values=[r["Poids live (%)"] for r in rows],
        hole=0.4,
        marker=dict(colors=[
            "#0c1a2e", "#b8973f", "#2d7a4f", "#c0392b", "#2980b9",
            "#8e44ad", "#e67e22", "#16a085", "#7f8c8d",
        ]),
    ))
    fig_pie.update_layout(
        height=320, margin=dict(l=0, r=0, t=10, b=10),
        paper_bgcolor="#fff", showlegend=True,
        legend=dict(orientation="h"),
    )
    st.plotly_chart(fig_pie, use_container_width=True)
else:
    st.info("Données basket non disponibles.")

# ── Rebalancement ─────────────────────────────────────────────────────────── #
_section("Historique des rebalancements")

if rebal:
    rebals_list = [r for r in rebal.get("rebalancings", []) if not r.get("skipped")]
    if rebals_list:
        rows_rb = []
        for rb in rebals_list:
            n_b = rb.get("n_basket", len(rb.get("basket", [])))
            n_e = len(rb.get("excluded", []))
            snts_w = next((b["w_etf"] * 100 for b in rb.get("basket", []) if b["ticker"] == "SNTS"), None)
            rows_rb.append({
                "Date":           rb["date"],
                "Nb titres":      n_b,
                "SNTS (%)":       f"{snts_w:.1f}%" if snts_w else "—",
                "Exclus":         n_e,
                "Turnover (%)":   f"{rb.get('turnover', 0) * 100:.2f}%",
                "Coût (bps)":     f"{rb.get('cost_bps', 0):.1f}",
            })
        df_rb = pd.DataFrame(rows_rb).set_index("Date")
        st.dataframe(df_rb, use_container_width=True, height=min(400, 40 + 35 * len(rows_rb)))
    else:
        st.info("Aucun rebalancement disponible.")
else:
    st.info("rebal_detail.json introuvable.")

# ── Dividendes ────────────────────────────────────────────────────────────── #
_section("Dividendes")

div_hist = load_json(os.path.join(DATA_DIR, "dividend_history.json")) or {}
hist_data = div_hist.get("history", {}) if isinstance(div_hist, dict) else {}

if hist_data:
    rows_div = []
    for tk, years in hist_data.items():
        for yr, amt in sorted(years.items(), reverse=True):
            rows_div.append({"Ticker": tk, "Année": yr, "Dividende (FCFA/action)": f"{amt:,.0f}"})
    df_div = pd.DataFrame(rows_div)
    st.dataframe(df_div, use_container_width=True, height=300, hide_index=True)
else:
    st.info("Aucune donnée de dividendes disponible.")

# ── Méthodologie ──────────────────────────────────────────────────────────── #
_section("Méthodologie")
st.markdown("""
| Paramètre | Valeur |
|-----------|--------|
| Univers | Titres Shariah-compliant de l'indice BRVMCI |
| Pondération | Market-cap, SONATEL cappé à 35 % |
| Rebalancement | Trimestriel |
| Frais de gestion | 0,60 %/an |
| Cash buffer | 1 % |
| Taux sans risque | 3,0 %/an (UEMOA) |
| Seuil min. halal | 0,5 % du sous-indice |
| Méthode dividendes | Total Return (réinvestissement) |
""")

# ── Footer ────────────────────────────────────────────────────────────────── #
st.markdown("---")
st.markdown(
    f"<p style='text-align:center;font-size:11px;color:#9ca3af'>"
    f"CGF Bourse — BRVMHalal ETF — Données au {calc_date} — "
    f"<em>Ce document ne constitue pas un conseil en investissement</em>"
    f"</p>",
    unsafe_allow_html=True,
)
