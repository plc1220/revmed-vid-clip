#!/bin/bash

# Exit on error
set -e

# --- Configuration ---
GCP_PROJECT_ID="your-gcp-project-id"
IMAGE_NAME="rev-med-backend"
GCR_HOSTNAME="gcr.io"
IMAGE_TAG="$GCR_HOSTNAME/$GCP_PROJECT_ID/$IMAGE_NAME:latest"

# --- Build and Push ---
echo "Building the Docker image..."
docker build -t $IMAGE_NAME .

echo "Tagging the image for GCR..."
docker tag $IMAGE_NAME $IMAGE_TAG

echo "Pushing the image to GCR..."
docker push $IMAGE_TAG

echo "Deployment image pushed to: $IMAGE_TAG"