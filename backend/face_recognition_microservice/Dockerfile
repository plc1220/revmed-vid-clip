# Use a compatible Python version
FROM python:3.9

# Set the working directory
WORKDIR /app

# Install system dependencies required for dlib and opencv
RUN apt-get update && apt-get install -y \
    build-essential \
    cmake \
    libsm6 \
    libxext6 \
    libxrender-dev \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Copy and install Python dependencies
COPY face_recognition_microservice/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the application code and shared gcs_service
COPY face_recognition_microservice/main.py .
COPY gcs_service.py .

# Command to run the job
CMD ["python", "main.py"]