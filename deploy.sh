#!/bin/bash

# Set your Google Cloud project ID
export PROJECT_ID=$(gcloud config get-value project)

if [ -z "$PROJECT_ID" ]; then
    echo "Google Cloud project ID not set. Please run 'gcloud config set project YOUR_PROJECT_ID'"
    exit 1
fi

echo "Deploying to project: $PROJECT_ID"

# Submit the build to Google Cloud Build
gcloud builds submit --config cloudbuild.yaml .

echo "Deployment submitted. Check the Google Cloud Console for progress."