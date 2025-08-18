#!/bin/bash

# Exit on error
set -e

# --- Configuration ---
GCP_PROJECT_ID="my-rd-coe-demo-gen-ai"
IMAGE_NAME="rev-med-frontend"
GCR_HOSTNAME="asia-southeast1-docker.pkg.dev"
IMAGE_TAG="$GCR_HOSTNAME/$GCP_PROJECT_ID/revmedia-vid-clip/$IMAGE_NAME:latest"

# --- Build and Push ---
echo "Changing to frontend directory..."
cd frontend

echo "Building the Docker image..."
sudo -E docker build -t $IMAGE_NAME .

echo "Tagging the image for GCR..."
sudo -E docker tag $IMAGE_NAME $IMAGE_TAG

echo "Pushing the image to GCR..."
sudo -E docker push $IMAGE_TAG

echo "Deployment image pushed to: $IMAGE_TAG"

echo "Deploying to Cloud Run..."
BACKEND_URL=$(gcloud run services describe revmedia-backend --platform managed --region asia-southeast1 --format 'value(status.url)')
gcloud run deploy revmedia-frontend --image=$IMAGE_TAG --region=asia-southeast1 --platform=managed --allow-unauthenticated --timeout=600 --cpu=2 --memory=4Gi --max-instances=4 --startup-probe="httpGet.port=8080,timeoutSeconds=240,periodSeconds=240" --set-env-vars=API_BASE_URL=$BACKEND_URL