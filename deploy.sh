#!/bin/bash

# Exit on error
set -e

# Create Artifact Registry repository if it doesn't exist
echo "Checking for Artifact Registry repository..."
if ! gcloud artifacts repositories describe revmed-app --project=my-rd-coe-demo-data --location=asia-southeast1 > /dev/null 2>&1; then
  echo "Creating Artifact Registry repository 'revmed-app'..."
  gcloud artifacts repositories create revmed-app \
    --repository-format=docker \
    --location=asia-southeast1 \
    --description="Docker repository for revmed-app" \
    --project=my-rd-coe-demo-data
else
  echo "Artifact Registry repository 'revmed-app' already exists."
fi

# Backend service
echo "Deploying backend service..."
(cd backend && gcloud builds submit --config cloudbuild.yaml)

# Face recognition service
#echo "Deploying face recognition service..."
#(cd backend/face_recognition_microservice && gcloud builds submit --config cloudbuild.yaml)

# Frontend service
#echo "Deploying frontend service..."
#(cd frontend && gcloud builds submit --config cloudbuild.yaml)

echo "All services deployed successfully!"