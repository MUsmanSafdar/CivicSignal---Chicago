# Accessibility conformance statement

**Target:** WCAG 2.1 Level AA, Section 508, and the Illinois Information Technology Accessibility Act (IITAA) standards.
**Status:** Partially conformant (self-assessed, 2026-10-25). No third-party audit has been done yet.

## What we did
- **Colour-vision-safe palette.** Risk uses blue (low) to orange (high) instead of red and green. The pairs stay distinct under simulated protanopia, deuteranopia and tritanopia (checked in `tests/test_phase1.py`).
- **Colour is never the only signal.** Risk levels, eligibility results and decisions carry text labels or badges. The heatmap prints each score. The county map has a text-table alternative ("View as table").
- **Contrast.** Body text, captions and status badges are tested for at least 4.5:1 against their backgrounds (`palette.contrast_ratio`, `tests/test_phase1.py`). Interactive blue text on the page gradient is 4.6:1 or better.
- **Structure.** Data tables use real table markup with column headers and a caption. Controls have visible labels.
- **Language access.** Public chatbot responses and key public captions are in English and Spanish (`locales/`). The Spanish text was written without a certified translator and needs native-speaker review before it is relied on for Title VI compliance.
- **No time limits, no flashing content.**

## Known limitations
1. **Plotly charts and maps** are not fully screen-reader accessible. Hover details are not available to keyboard users. The "View as table" expander gives the same numbers as text for the county map; other charts need the same treatment.
2. **Streamlit's own widgets** (sliders, tabs, popovers) come from the framework. We have not verified every one with NVDA, JAWS or VoiceOver.
3. **The embedded SVI website** (`site.html`, inside an iframe) has not been audited separately.
4. **Spanish coverage** is limited to public chatbot text and key captions. Internal and admin screens are English only. Place names and data values appear as stored.
5. **PDF decision packets** are generated with reportlab and are not tagged PDFs. The Markdown packet is the accessible version.
6. **Browser zoom to 200%** has been checked only informally.

## Feedback
Report a barrier to `[accessibility contact email]`. We aim to respond within 5 business days and will offer the information in another format on request.
