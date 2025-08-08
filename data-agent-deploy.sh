#!/bin/bash

# This script helps deploy a Data Agent to AgentSpace.
# Please fill in the placeholder variables before running.

# --- Prerequisites ---
# Make sure your GCP project is allowlisted for Data Agent access.
# Make sure the end users have the required BigQuery IAM roles.

# --- Configuration ---
export PROJECT_NUMBER="YOUR_PROJECT_NUMBER"
export LOCATION="YOUR_LOCATION"
export ENGINE_ID="YOUR_ENGINE_ID"
export BQ_PROJECT_ID="YOUR_BQ_PROJECT_ID"
export BQ_DATASET_ID="YOUR_BQ_DATASET_ID"
export AUTH_ID="orcas-authorization-test" # Customizable
export CLIENT_ID="YOUR_CLIENT_ID"
export CLIENT_SECRET="YOUR_CLIENT_SECRET"
export DISPLAY_NAME="My Data Agent" # Customizable
export AGENT_DESCRIPTION="An agent to query our BigQuery data." # Customizable

# --- OAuth URIs (Fixed) ---
TOKEN_URI="https://oauth2.googleapis.com/token"
AUTHORIZATION_URI="https://accounts.google.com/o/oauth2/v2/auth?client_id=${CLIENT_ID}&redirect_uri=https%3A%2F%2Fvertexaisearch.cloud.google.com%2Fstatic%2Foauth%2Foauth.html&scope=https%3A%2F%2Fwww.googleapis.com%2Fauth%2Fcloud-platform&include_granted_scopes=true&response_type=code&access_type=offline&prompt=consent"

# --- Step 1: Create Authorization Resource ---
echo "Creating Authorization Resource..."
curl -X POST \
  -H "Authorization: Bearer $(gcloud auth print-access-token)" \
  -H "Content-Type: application/json" \
  -H "X-Goog-User-Project: ${PROJECT_NUMBER}" \
  "https://discoveryengine.googleapis.com/v1alpha/projects/${PROJECT_NUMBER}/locations/${LOCATION}/authorizations?authorizationId=${AUTH_ID}" \
  -d '{
  "name": "projects/'"${PROJECT_NUMBER}"'/locations/'"${LOCATION}"'/authorizations/'"${AUTH_ID}"'",
  "serverSideOauth2": {
    "clientId": "'"${CLIENT_ID}"'",
    "clientSecret": "'"${CLIENT_SECRET}"'",
    "authorizationUri": "'"${AUTHORIZATION_URI}"'",
    "tokenUri": "'"${TOKEN_URI}"'"
  }
}'

# The command above will return an AUTHORIZATION_RESOURCE_NAME.
# Example: projects/YOUR_PROJECT_NUMBER/locations/YOUR_LOCATION/authorizations/YOUR_AUTH_ID
# This is captured automatically in the next step.
export AUTHORIZATION_RESOURCE_NAME="projects/${PROJECT_NUMBER}/locations/${LOCATION}/authorizations/${AUTH_ID}"


# --- Step 2: Create Agent ---
echo "Creating Agent..."
AGENT_RESPONSE=$(curl -X POST \
  -H "Authorization: Bearer $(gcloud auth print-access-token)" \
  -H "Content-Type: application/json" \
  -H "X-Goog-User-Project: ${PROJECT_NUMBER}" \
  "https://discoveryengine.googleapis.com/v1alpha/projects/${PROJECT_NUMBER}/locations/${LOCATION}/collections/default_collection/engines/${ENGINE_ID}/assistants/default_assistant/agents" \
  -d '{
    "displayName": "'"${DISPLAY_NAME}"'",
    "description": "'"${AGENT_DESCRIPTION}"'",
    "icon": {
       "uri": "https://fonts.gstatic.com/s/i/short-term/release/googlesymbols/corporate_fare/default/24px.svg"
     },
    "managed_agent_definition": {
      "tool_settings": {
        "tool_description": "'"${AGENT_DESCRIPTION}"'"
      },
      "data_science_agent_config": {
        "bq_project_id": "'"${BQ_PROJECT_ID}"'",
        "bq_dataset_id": "'"${BQ_DATASET_ID}"'"
      }
    },
    "authorizations": [
      "'"${AUTHORIZATION_RESOURCE_NAME}"'"
    ]
  }')

echo "Agent creation response: ${AGENT_RESPONSE}"
export AGENT_ID=$(echo ${AGENT_RESPONSE} | grep -o '"name": "[^"]*' | sed 's/"name": ".*\///' | sed 's/"//')
export AGENT_RESOURCE_NAME="projects/${PROJECT_NUMBER}/locations/${LOCATION}/collections/default_collection/engines/${ENGINE_ID}/assistants/default_assistant/agents/${AGENT_ID}"

# --- Step 3: Deploy Agent ---
echo "Deploying Agent..."
curl -X POST \
  -H "Authorization: Bearer $(gcloud auth print-access-token)" \
  -H "Content-Type: application/json" \
  -H "X-Goog-User-Project: ${PROJECT_NUMBER}" \
  "https://discoveryengine.googleapis.com/v1alpha/projects/${PROJECT_NUMBER}/locations/${LOCATION}/collections/default_collection/engines/${ENGINE_ID}/assistants/default_assistant/agents/${AGENT_ID}:deploy" \
  -d '{
    "name": "'"${AGENT_RESOURCE_NAME}"'"
  }'

echo "Deployment initiated. It may take up to 10 minutes to complete."
