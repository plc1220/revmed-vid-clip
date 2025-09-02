#!/bin/bash
set -euo pipefail

# Configurable variables
PROJECT_ID=${PROJECT_ID:-my-rd-coe-demo-data}
REGION=${REGION:-asia-southeast1}
REPO_NAME="revmed-app"
QUEUE_NAME="face-recognition-queue"

info()  { echo -e "\033[1;34m[INFO]\033[0m $*"; }
warn()  { echo -e "\033[1;33m[WARN]\033[0m $*"; }
error() { echo -e "\033[1;31m[ERROR]\033[0m $*"; exit 1; }

# Ensure required APIs are enabled
REQUIRED_APIS=(
  artifactregistry.googleapis.com
  cloudtasks.googleapis.com
  run.googleapis.com
  cloudbuild.googleapis.com
)
for api in "${REQUIRED_APIS[@]}"; do
  if ! gcloud services list --enabled --project="$PROJECT_ID" --format="value(config.name)" | grep -q "$api"; then
    info "Enabling API: $api"
    gcloud services enable "$api" --project="$PROJECT_ID" --quiet
  else
    info "API $api already enabled."
  fi
done

# Ensure Artifact Registry repo exists
info "Checking for Artifact Registry repository..."
if ! gcloud artifacts repositories describe "$REPO_NAME" --project="$PROJECT_ID" --location="$REGION" > /dev/null 2>&1; then
  info "Creating Artifact Registry repository '$REPO_NAME'..."
  gcloud artifacts repositories create "$REPO_NAME" \
    --repository-format=docker \
    --location="$REGION" \
    --description="Docker repository for revmed-app" \
    --project="$PROJECT_ID" \
    --quiet
else
  info "Artifact Registry repository '$REPO_NAME' already exists."
fi

# Ensure Cloud Tasks queue exists
info "Checking for Cloud Tasks queue..."
if ! gcloud tasks queues describe "$QUEUE_NAME" --location="$REGION" --project="$PROJECT_ID" > /dev/null 2>&1; then
  info "Creating Cloud Tasks queue '$QUEUE_NAME'..."
  gcloud tasks queues create "$QUEUE_NAME" --location="$REGION" --project="$PROJECT_ID" --quiet
else
  info "Cloud Tasks queue '$QUEUE_NAME' already exists."
fi

# Deploy backend service
#info "Deploying backend service..."
#(cd backend && gcloud builds submit --config cloudbuild.yaml --project="$PROJECT_ID" --quiet)

# # Deploy face recognition service
# info "Deploying face recognition service..."
# gcloud builds submit --config backend/face_recognition_microservice/cloudbuild.yaml . --project="$PROJECT_ID" --quiet

# Deploy frontend service
info "Deploying frontend service..."
(cd frontend && gcloud builds submit --config cloudbuild.yaml --project="$PROJECT_ID" --quiet)

info "✅ All services deployed successfully!"