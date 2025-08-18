# Use an official Python runtime as a parent image
FROM python:3.9-slim

ENV PYTHONUNBUFFERED=True

# Set the working directory in the container
WORKDIR /app

# Copy the requirements file into the container at /app
COPY requirements.txt .

# Install any needed packages specified in requirements.txt
# Install gcsfuse and other dependencies
RUN apt-get update && apt-get install -y \
    ffmpeg \
    curl \
    fuse \
    lsb-release \
    gnupg && \
    curl https://packages.cloud.google.com/apt/doc/apt-key.gpg | tee /usr/share/keyrings/cloud.google.asc && \
    echo "deb [signed-by=/usr/share/keyrings/cloud.google.asc] https://packages.cloud.google.com/apt gcsfuse-bookworm main" | tee /etc/apt/sources.list.d/gcsfuse.list && \
    apt-get update && \
    apt-get install -y gcsfuse && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Create the mount point for GCS
RUN mkdir -p /gcs

RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application's code from the host to the container at /app
COPY . .
COPY credentials.json /app/credentials.json


# Make port 8000 available to the world outside this container
ENV PORT=8080
RUN unset GOOGLE_APPLICATION_CREDENTIALS
EXPOSE 8080

# Make the startup script executable
COPY startup.sh .
RUN chmod +x startup.sh

# Run the startup script when the container launches
CMD ["./startup.sh"]