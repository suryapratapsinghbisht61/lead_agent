#!/bin/sh
# Start the Streamlit dashboard. Hosts like Render tell the app which port to use via $PORT.
exec streamlit run dashboard/streamlit_app.py \
  --server.address 0.0.0.0 \
  --server.port "${PORT:-8501}" \
  --server.headless true
