#!/bin/bash

# Exit on error
set -e

# --- Configuration ---
GCP_PROJECT_ID="my-rd-coe-demo-gen-ai"
IMAGE_NAME="rev-med-backend"
GCR_HOSTNAME="asia-southeast1-docker.pkg.dev"
IMAGE_TAG="$GCR_HOSTNAME/$GCP_PROJECT_ID/revmedia-vid-clip/$IMAGE_NAME:latest"
SERVICE_ACCOUNT_KEY_PATH="credentials.json" # Assumes key is in the root directory
GCS_BUCKET_NAME="revmedia-vid-clip-bucket" # <-- IMPORTANT: SET YOUR BUCKET NAME HERE

# --- Pre-deployment Steps ---
echo "Checking for service account key..."
if [ ! -f "$SERVICE_ACCOUNT_KEY_PATH" ]; then
    echo "Service account key file not found at $SERVICE_ACCOUNT_KEY_PATH"
    exit 1
fi

echo "Copying service account key to backend directory..."
cp "$SERVICE_ACCOUNT_KEY_PATH" backend/credentials.json

# --- Build and Push ---
echo "Changing to backend directory..."
cd backend

echo "Building the Docker image..."
sudo -E docker build -t $IMAGE_NAME .

echo "Tagging the image for Artifact Registry..."
sudo -E docker tag $IMAGE_NAME $IMAGE_TAG

echo "Pushing the image to Artifact Registry..."
sudo -E docker push $IMAGE_TAG

echo "Deployment image pushed to: $IMAGE_TAG"

# --- Deploy to Cloud Run ---
echo "Deploying to Cloud Run..."
gcloud run deploy revmedia-backend \
    --image=$IMAGE_TAG \
    --region=asia-southeast1 \
    --platform=managed \
    --allow-unauthenticated \
    --update-secrets=GOOGLE_APPLICATION_CREDENTIALS=revmed-vid-clip-gcs-rw:latest \
    --service-account=452883396851-compute@developer.gserviceaccount.com \
    --execution-environment=gen1 \
    --set-env-vars=GCS_BUCKET_NAME=$GCS_BUCKET_NAME

# --- Post-deployment Cleanup ---
echo "Removing service account key from backend directory..."
# We are still inside the 'backend' directory
rm credentials.json