#!/bin/bash
# Azure App Service (Linux) startup command: bash startup.sh
python -m streamlit run app.py \
  --server.port "${PORT:-8000}" --server.address 0.0.0.0 --server.headless true \
  --browser.gatherUsageStats false --server.enableXsrfProtection true
