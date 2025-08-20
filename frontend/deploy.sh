#!/bin/bash

# Exit on error
set -e

# --- Configuration ---
GCP_PROJECT_ID="my-rd-coe-demo-data"

# --- Build and Deploy via Cloud Build ---
echo "Changing to frontend directory..."
cd frontend

echo "Submitting build to Google Cloud Build..."
gcloud builds submit --config cloudbuild.yaml --project=$GCP_PROJECT_ID

echo "Frontend deployment submitted."