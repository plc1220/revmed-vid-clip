#!/bin/bash

# Start the backend API in the background
(cd backend && uvicorn main:app --host 0.0.0.0 --port 8000) &

# Give the backend a few seconds to start
sleep 5

# Start the Streamlit UI in the foreground
(cd frontend && streamlit run app.py)