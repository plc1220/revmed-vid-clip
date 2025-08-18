#!/bin/bash
set -e
gcsfuse --implicit-dirs --key-file /app/credentials.json ${GCS_BUCKET_NAME} /gcs
exec uvicorn main:app --host 0.0.0.0 --port ${PORT} --workers 1