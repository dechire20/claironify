#!/usr/bin/env bash
# Use an official Python image
FROM python:3.11-slim

# Now you HAVE root access to install ffmpeg!
RUN apt-get update && apt-get install -y ffmpeg && rm -rf /var/lib/apt/lists/*

# Set up your app
WORKDIR /app
COPY . /app
RUN pip install --no-cache-dir -r requirements.txt

# Command to run your app (replace with your actual entry point)
CMD ["gunicorn", "app:app"]
