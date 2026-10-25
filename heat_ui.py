"""Cooling centers, shelters and a rule-based chat assistant for the Chicago area."""
from pathlib import Path

import pandas as pd
import json

import plotly.graph_objects as go
import streamlit as st

import chatbot_engine
from rate_limit import SlidingWindowLimiter, clean_chat_input

_ROOT = Path(__file__).resolve().parent
DATA = _ROOT / "data" if (_ROOT / "data" / "cooling_centers.csv").exists() else _ROOT
from palette import NEED_SCALE, ramp_color, text_on  # one-hue ramp, colour-vision safe
from heat_need import need_table, HIGH_NEED
from i18n import t as _t
CHICAGO_CENTER = {"lat": 41.85, "lon": -87.95}

QUICK = [
    "Cooling centers in Chicago",
    "Cooling centers in Evanston",
    "Shelters in Cook County",
    "Heat safety tips",
    "Emergency contacts for Cook County",
]


@st.cache_data
def _load_geo():
    return json.load(open(DATA / "illinois_counties.geojson"))


@st.cache_data
def _load():
    cc = pd.read_csv(DATA / "cooling_centers.csv", dtype={"zip": str})
    sh = pd.read_csv(DATA / "shelters.csv", dtype={"zip": str})
    risk = pd.read_csv(DATA / "county_risk.csv")
    cap = pd.read_csv(DATA / "county_capacity.csv")
    comp = pd.read_csv(DATA / "complaints.csv")
    return cc, sh, risk, cap, comp


def _centroids(geo, names):
    """Bounding-box centre of each named county polygon, for text labels."""
    out = {}

    def walk(c, pts):
        if c and isinstance(c[0], (int, float)):
            pts.append(c)
        else:
            for x in c:
                walk(x, pts)

    for f in geo["features"]:
        n = f["properties"].get("name")
        if n in names:
            pts = []
            walk(f["geometry"]["coordinates"], pts)
            xs, ys = [p[0] for p in pts], [p[1] for p in pts]
            out[n] = ((min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2)
    return out


def _gis_map(view, cc, need):
    """County polygons in ONE hue (dark orange = higher heat-wave need, light = lower), star markers for cooling centers."""
    geo = _load_geo()
    fig = go.Figure()
    fig.add_trace(go.Choropleth(
        geojson=geo, locations=need["county"], z=need["need"], featureidkey="properties.name",
        colorscale=NEED_SCALE, zmin=0, zmax=100, marker_line_color="#ffffff", marker_line_width=1.5,
        customdata=need[["heat_score", "svi", "centers"]].values,
        hovertemplate=("<b>%{location} County</b><br>Heat-wave need: %{z:.0f} / 100<br>Extreme Heat risk: %{customdata[0]:.1f} / 5"
                       "<br>Social Vulnerability Index: %{customdata[1]:.2f}<br>Cooling centers on this list: %{customdata[2]}<extra></extra>"),
        colorbar=dict(title=dict(text="Heat-wave need<br>(0 lower to 100 higher)"), thickness=14, len=0.7), name="County need",
    ))
    cen = _centroids(geo, set(need["county"]))
    fig.add_trace(go.Scattergeo(
        lon=[cen[c][0] for c in need["county"] if c in cen], lat=[cen[c][1] for c in need["county"] if c in cen],
        text=[f"{c}<br>{n:.0f}" for c, n in zip(need["county"], need["need"]) if c in cen],
        mode="text", textfont=dict(size=12, color=[text_on(ramp_color(n / 100)) for c, n in zip(need["county"], need["need"]) if c in cen]), hoverinfo="skip", showlegend=False,
    ))
    if not view.empty:
        fig.add_trace(go.Scattergeo(
            lon=view["longitude"], lat=view["latitude"], mode="markers", name="\u2605 Cooling center",
            marker=dict(symbol="star", size=14, color="#ffffff", line=dict(color="#1d1d1f", width=1.6)),
            customdata=view[["address", "hours", "phone"]].values, text=view["name"],
            hovertemplate="<b>\u2605 %{text}</b><br>%{customdata[0]}<br>%{customdata[1]}<br>%{customdata[2]}<extra></extra>",
        ))
    geo_cfg = dict(visible=False, projection_type="mercator", bgcolor="rgba(0,0,0,0)", fitbounds="locations")
    if 0 < len(view) < len(cc):
        lat, lon = float(view["latitude"].mean()), float(view["longitude"].mean())
        pad = 0.08 if len(view) < 8 else 0.3
        geo_cfg.update(fitbounds=False, lonaxis_range=[lon - pad * 1.3, lon + pad * 1.3], lataxis_range=[lat - pad, lat + pad])
    fig.update_geos(**geo_cfg)
    fig.update_layout(margin=dict(l=0, r=0, t=0, b=0), paper_bgcolor="#ffffff", font=dict(color="#1d1d1f"), height=560,
                      legend=dict(orientation="h", yanchor="bottom", y=0.01, xanchor="left", x=0.01, bgcolor="rgba(255,255,255,0.9)"))
    return fig


def _need_bars(need):
    """Horizontal bars of the same index with printed values (text alternative to the map colours)."""
    d = need.sort_values("need")
    fig = go.Figure(go.Bar(
        x=d["need"], y=d["county"], orientation="h", text=[f"{v:.0f}" for v in d["need"]], textposition="outside",
        marker=dict(color=[ramp_color(v / 100) for v in d["need"]], line=dict(color="#7f2704", width=0.6)),
        customdata=d[["heat_score", "svi", "centers"]].values,
        hovertemplate="<b>%{y}</b><br>Need %{x:.0f}<br>Heat risk %{customdata[0]:.1f}/5<br>SVI %{customdata[1]:.2f}<br>Centers listed %{customdata[2]}<extra></extra>",
    ))
    fig.update_layout(height=max(240, 46 * len(d) + 80), margin=dict(l=10, r=30, t=10, b=10), paper_bgcolor="#ffffff", plot_bgcolor="#ffffff",
                      xaxis=dict(range=[0, 110], title="Heat-wave need index (0 to 100)"), font=dict(color="#1d1d1f"), showlegend=False)
    return fig


def render(lang: str = "en"):
    cc, sh, risk, cap, comp = _load()
    asof = str(cc["last_refreshed_utc"].iloc[0])[:10]

    st.markdown(
        "<div style='text-align:center;padding:1rem 0 0.2rem'><h1 style='margin:0;font-size:2.3rem'>Cooling Centers &amp; Shelters</h1>"
        "<p style='color:#515154;margin:0.3rem 0 0'>Where to go during a heat wave or other emergency in the Chicago area, plus an assistant you can ask.</p></div>",
        unsafe_allow_html=True,
    )
    st.warning(
        f"Cooling-center data comes from public Illinois cooling-center map layers and was last refreshed **{asof}**. "
        "Hours change often, so call before you go, or call **311** (Chicago) or **211**. "
        "The shelter list is a sample file and must be verified before anyone relies on it."
    )

    left, right = st.columns([1, 1.4], gap="large")

    # ---------------- chat assistant
    with left:
        st.subheader(_t("ui.chat.title", lang))
        st.caption(_t("ui.chat.caption", lang))
        st.caption(_t("ui.chat.translation_note", lang))
        if "heat_chat" not in st.session_state:
            st.session_state["heat_chat"] = []
        cols = st.columns(2)
        for i, q in enumerate(_t("ui.quick", lang).split("\n")):
            if cols[i % 2].button(q, key=f"heat_q_{i}", use_container_width=True):
                st.session_state["heat_pending"] = q
        typed = st.chat_input(_t("ui.chat.placeholder", lang), key="heat_input")
        question = typed or st.session_state.pop("heat_pending", None)
        if question:
            question = clean_chat_input(question)
            if question and not st.session_state.setdefault("_heat_limiter", SlidingWindowLimiter()).allow():
                st.warning(_t("ui.chat.rate_limited", lang, seconds=int(st.session_state["_heat_limiter"].retry_after()) + 1))
                question = None
        if question:
            _ql = question.lower()
            if ("tip" in _ql and "heat" in _ql) or ("consejo" in _ql and "calor" in _ql):
                reply = _t("chat.heat_tips", lang)
            else:
                reply = chatbot_engine.chat(question, risk, cap, comp, lang=lang)
            st.session_state["heat_chat"].append(("user", question))
            st.session_state["heat_chat"].append(("assistant", reply))
        box = st.container(height=520, border=True)
        with box:
            if not st.session_state["heat_chat"]:
                st.markdown("Try **Cooling centers in Chicago**, or type a ZIP code like **60639**.")
            for role, text in st.session_state["heat_chat"]:
                with st.chat_message(role):
                    st.markdown(text)
        if st.session_state["heat_chat"] and st.button(_t("ui.chat.clear", lang), key="heat_clear"):
            st.session_state["heat_chat"] = []
            st.rerun()

    # ---------------- map and list
    with right:
        st.subheader("Chicago-area heat map")
        f1, f2 = st.columns(2)
        sources = ["All"] + sorted(cc["source"].unique())
        src = f1.selectbox("Source", sources, key="heat_src")
        cities = ["All"] + sorted(cc["city"].unique(), key=lambda c: (c != "Chicago", c))
        city = f2.selectbox("City", cities, key="heat_city")
        zip_q = st.text_input("ZIP code (optional)", key="heat_zip", max_chars=5, placeholder="60639")
        view = cc.copy()
        if src != "All":
            view = view[view["source"] == src]
        if city != "All":
            view = view[view["city"] == city]
        if zip_q.strip():
            view = view[view["zip"].str.startswith(zip_q.strip())]
        if view.empty:
            st.info("No cooling centers match. Clear a filter or call 311 / 211.")
        else:
            need = need_table(risk, cc)
            if need.empty:
                st.info("Heat risk scores are not loaded, so the county shading is unavailable.")
            else:
                top = need.iloc[0]
                k = st.columns(4)
                k[0].metric("Cooling centers shown", len(view), f"of {len(cc)} listed", delta_color="off")
                k[1].metric("Highest-need county", top["county"], f"index {top['need']:.0f} of 100", delta_color="off")
                k[2].metric("Counties scored", len(need))
                k[3].metric("With no center listed", int((need["centers"] == 0).sum()))
                st.plotly_chart(_gis_map(view, cc, need), use_container_width=True)
                st.caption("Shading: one colour, darker orange = higher heat-wave need (half Extreme Heat risk, half Social Vulnerability Index; "
                           "sample scores). \u2605 = cooling center. Each county is also labelled with its number. Hover for address and hours.")
                gaps = need[need["gap"]]
                if not gaps.empty:
                    st.warning("High need (index " + f"{HIGH_NEED:.0f}" + "+) and no cooling center on this list: " + ", ".join(gaps["county"]) +
                               ". The list may be incomplete there; call 211 to check.")
                st.markdown("**Heat-wave need by county**")
                st.plotly_chart(_need_bars(need), use_container_width=True)
                with st.expander("View as table (text alternative)"):
                    st.dataframe(need.rename(columns={"county": "County", "heat_score": "Extreme Heat risk (0-5)", "svi": "SVI (0-1)",
                                                      "need": "Need index (0-100)", "centers": "Centers listed", "gap": "High need, none listed"}),
                                 hide_index=True, use_container_width=True)

    st.divider()
    st.subheader("Cooling center list")
    if not view.empty:
        show = view[["name", "address", "city", "zip", "hours", "phone", "source"]].rename(columns={
            "name": "Name", "address": "Address", "city": "City", "zip": "ZIP", "hours": "Hours", "phone": "Phone", "source": "Source"})
        st.dataframe(show, hide_index=True, use_container_width=True, height=360)
        st.download_button("Download this list (CSV)", show.to_csv(index=False).encode("utf-8"), "chicago_cooling_centers.csv", "text/csv")

    st.subheader("Emergency shelters")
    st.caption("Sample shelter list for the seven Chicago-area counties. Capacity and hours are not verified. Call ahead.")
    counties = ["All"] + sorted(sh["county"].unique())
    pick = st.selectbox("County", counties, key="heat_sh_county")
    s = sh if pick == "All" else sh[sh["county"] == pick]
    st.dataframe(
        s.rename(columns={"county": "County", "shelter_name": "Shelter", "address": "Address", "city": "City", "zip": "ZIP",
                          "capacity": "Capacity", "shelter_type": "Type", "phone": "Phone", "open_24h": "Open 24h"}),
        hide_index=True, use_container_width=True,
    )
