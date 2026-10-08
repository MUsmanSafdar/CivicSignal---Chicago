"""Cooling centers, shelters and a rule-based chat assistant for the Chicago area."""
import html
from pathlib import Path

import pandas as pd
import json

import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

import chatbot_engine

DATA = Path(__file__).resolve().parent / "data"
GREEN, NEUTRAL, RED = "#2e9e5b", "#f4f1ea", "#c62828"
RG_SCALE = [[0.0, GREEN], [0.5, NEUTRAL], [1.0, RED]]
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


def _gis_map(view, cc, risk):
    """County polygons shaded by Extreme Heat risk, with cooling centers marked on top."""
    geo = _load_geo()
    heat = risk[risk["hazard"] == "Extreme Heat"].copy()
    counts = cc.groupby("county").size()
    heat["centers"] = heat["county"].map(counts).fillna(0).astype(int)
    heat["_score"] = heat["risk_score"].map(lambda x: f"{x:.1f}")
    heat["_svi"] = heat["svi_score"].map(lambda x: f"{x:.2f}")
    fig = px.choropleth_mapbox(
        heat, geojson=geo, locations="county", featureidkey="properties.name",
        color="risk_score", color_continuous_scale=RG_SCALE, range_color=[0, 5],
        hover_name="county", custom_data=["_score", "risk_level", "_svi", "centers"],
        mapbox_style="carto-positron", zoom=8.4, center=CHICAGO_CENTER, opacity=0.55, height=520,
    )
    fig.update_traces(hovertemplate=(
        "<b>%{hovertext} County</b><br>"
        "Extreme Heat risk: %{customdata[0]} / 5.0 (%{customdata[1]})<br>"
        "Social Vulnerability Index: %{customdata[2]}<br>"
        "Cooling centers on this list: %{customdata[3]}<extra></extra>"
    ))
    if not view.empty:
        fig.add_trace(go.Scattermapbox(
            lat=view["latitude"], lon=view["longitude"], mode="markers", marker=dict(size=9, color="#0b3d2e"),
            customdata=view[["address", "hours", "phone"]].values, text=view["name"],
            hovertemplate="<b>%{text}</b><br>%{customdata[0]}<br>%{customdata[1]}<br>%{customdata[2]}<extra></extra>",
            name="Cooling centers", showlegend=False,
        ))
        if len(view) < len(cc):
            fig.update_layout(mapbox=dict(center={"lat": float(view["latitude"].mean()), "lon": float(view["longitude"].mean())},
                                          zoom=11 if len(view) < 8 else 9.5))
    fig.update_layout(
        margin=dict(l=0, r=0, t=0, b=0), paper_bgcolor="#ffffff", font=dict(color="#1d1d1f"),
        coloraxis_colorbar=dict(title=dict(text="Heat risk"), thickness=14, len=0.6),
    )
    return fig


def render():
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
        st.subheader("Ask the assistant")
        st.caption("Runs inside this app with no outside AI. It answers from the lists on this page.")
        if "heat_chat" not in st.session_state:
            st.session_state["heat_chat"] = []
        cols = st.columns(2)
        for i, q in enumerate(QUICK):
            if cols[i % 2].button(q, key=f"heat_q_{i}", use_container_width=True):
                st.session_state["heat_pending"] = q
        typed = st.chat_input("Ask about cooling centers, shelters or heat safety, e.g. 'cooling center 60639'", key="heat_input")
        question = typed or st.session_state.pop("heat_pending", None)
        if question:
            if "tip" in question.lower() and "heat" in question.lower():
                reply = (
                    "**Heat safety**\n\n- Drink water before you feel thirsty and avoid alcohol and heavy meals.\n"
                    "- Stay in air conditioning if you can; use a cooling center if you have none.\n"
                    "- Check on older neighbors, young children and people living alone.\n"
                    "- Never leave a person or pet in a parked car.\n"
                    "- Call **911** for confusion, fainting, hot dry skin or a very high body temperature."
                )
            else:
                reply = chatbot_engine.chat(question, risk, cap, comp)
            st.session_state["heat_chat"].append(("user", question))
            st.session_state["heat_chat"].append(("assistant", reply))
        box = st.container(height=520, border=True)
        with box:
            if not st.session_state["heat_chat"]:
                st.markdown("Try **Cooling centers in Chicago**, or type a ZIP code like **60639**.")
            for role, text in st.session_state["heat_chat"]:
                with st.chat_message(role):
                    st.markdown(text)
        if st.session_state["heat_chat"] and st.button("Clear chat", key="heat_clear"):
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
            fig = _gis_map(view, cc, risk)
            st.plotly_chart(fig, use_container_width=True)
            st.caption(f"{len(view)} cooling centers shown. County shading is Extreme Heat risk (green low, red high, sample scores). Dark dots are cooling centers; hover for address and hours.")

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
