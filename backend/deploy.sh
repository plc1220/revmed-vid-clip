#!/bin/bash

# Exit on error
set -e

# --- Configuration ---
GCP_PROJECT_ID="my-rd-coe-demo-data"

# --- Build and Deploy via Cloud Build ---
echo "Changing to backend directory..."
cd backend

echo "Submitting build to Google Cloud Build..."
gcloud builds submit --config cloudbuild.yaml --project=$GCP_PROJECT_ID

echo "Backend deployment submitted."