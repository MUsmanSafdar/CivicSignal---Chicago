"""Public website view: statewide SVI and hazard explorer, embedded in the app."""
from pathlib import Path
import streamlit as st
import streamlit.components.v1 as components

_HERE = Path(__file__).parent
_PAGE = next((p for p in (_HERE / "site.html", _HERE / "assets" / "site.html") if p.exists()), None)


def render():
    if _PAGE is None:
        st.error("Website page file is missing (site.html).")
        return
    st.caption("Statewide view: social vulnerability (SVI) and hazard risk for all 102 Illinois counties.")
    components.html(_PAGE.read_text(encoding="utf-8"), height=1000, scrolling=True)
