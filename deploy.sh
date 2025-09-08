#!/bin/bash
set -euo pipefail

# Configurable variables
PROJECT_ID="mp-ai-video"
PROJECT_NUMBER="1020529541571"
REGION="asia-southeast1"
REPO_NAME="revmed-app"
QUEUE_NAME="face-recognition-queue"
GCS_BUCKET_NAME="mp-ai-video-clipping-bucket"
BACKEND_URL="https://backend-${PROJECT_NUMBER}.${REGION}.run.app"
FACE_RECOGNITION_JOB_URL="https://${REGION}-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/${PROJECT_NUMBER}/jobs/face-recognition-job:run"
SERVICE_ACCOUNT_NAME="video-clipping-sa"
SERVICE_ACCOUNT_EMAIL="${SERVICE_ACCOUNT_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"

info()  { echo -e "\033[1;34m[INFO]\033[0m $*"; }
warn()  { echo -e "\033[1;33m[WARN]\033[0m $*"; }
error() { echo -e "\033[1;31m[ERROR]\033[0m $*"; exit 1; }

# Ensure required APIs are enabled
REQUIRED_APIS=(
  artifactregistry.googleapis.com
  cloudtasks.googleapis.com
  run.googleapis.com
  cloudbuild.googleapis.com
  iam.googleapis.com
)
for api in "${REQUIRED_APIS[@]}"; do
  if ! gcloud services list --enabled --project="$PROJECT_ID" --format="value(config.name)" | grep -q "$api"; then
    info "Enabling API: $api"
    gcloud services enable "$api" --project="$PROJECT_ID" --quiet
  else
    info "API $api already enabled."
  fi
done

# Create service account if it doesn't exist
info "Checking for service account..."
if ! gcloud iam service-accounts describe "$SERVICE_ACCOUNT_EMAIL" --project="$PROJECT_ID" > /dev/null 2>&1; then
  info "Creating service account '$SERVICE_ACCOUNT_NAME'..."
  gcloud iam service-accounts create "$SERVICE_ACCOUNT_NAME" \
    --display-name="RevMed App Service Account" \
    --description="Service account for RevMed video clipping application" \
    --project="$PROJECT_ID" \
    --quiet
else
  info "Service account '$SERVICE_ACCOUNT_NAME' already exists."
fi

# Grant necessary IAM roles to the service account
info "Granting IAM roles to service account..."
ROLES=(
  "roles/run.invoker"
  "roles/cloudtasks.enqueuer"
  "roles/storage.objectViewer"
  "roles/storage.objectCreator"
)

for role in "${ROLES[@]}"; do
  info "Granting role $role to service account..."
  gcloud projects add-iam-policy-binding "$PROJECT_ID" \
    --member="serviceAccount:$SERVICE_ACCOUNT_EMAIL" \
    --role="$role" \
    --quiet
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

# Face recognition job
echo "Deploying face recognition job..."
gcloud builds submit backend --config ./backend/face_recognition_microservice/cloudbuild.yaml \
  --substitutions=_PROJECT_ID=${PROJECT_ID},_REGION=${REGION},_REPO_NAME=${REPO_NAME},_SERVICE_ACCOUNT_EMAIL=${SERVICE_ACCOUNT_EMAIL}

# Backend service
echo "Deploying backend service..."
gcloud builds submit ./backend --config ./backend/cloudbuild.yaml \
  --substitutions=_PROJECT_ID=${PROJECT_ID},_REGION=${REGION},_REPO_NAME=${REPO_NAME},_FACE_RECOGNITION_JOB_URL=${FACE_RECOGNITION_JOB_URL},_QUEUE_NAME=${QUEUE_NAME},_SERVICE_ACCOUNT_EMAIL=${SERVICE_ACCOUNT_EMAIL}

# Frontend service
echo "Deploying frontend service..."
gcloud builds submit ./frontend --config ./frontend/cloudbuild.yaml \
  --substitutions=_PROJECT_ID=${PROJECT_ID},_REGION=${REGION},_REPO_NAME=${REPO_NAME},_API_BASE_URL=${BACKEND_URL},_GCS_BUCKET_NAME=${GCS_BUCKET_NAME},_SERVICE_ACCOUNT_EMAIL=${SERVICE_ACCOUNT_EMAIL}

info "✅ All services deployed successfully!"