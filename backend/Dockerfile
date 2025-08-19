# Use an official Python runtime as a parent image
FROM python:3.9-slim

ENV PYTHONUNBUFFERED True

# Set the working directory in the container
WORKDIR /app

# Copy the requirements file into the container at /app
COPY requirements.txt .

# Install any needed packages specified in requirements.txt
RUN apt-get update && apt-get install -y ffmpeg
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application's code from the host to the container at /app
COPY . .

# Make port 8000 available to the world outside this container
ENV PORT 8080
EXPOSE 8080

# Run main.py when the container launches
CMD exec uvicorn main:app --host 0.0.0.0 --port ${PORT} --workers 1