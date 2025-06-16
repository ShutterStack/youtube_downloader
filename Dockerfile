# Use a Python base image. Python 3.9-slim-buster is a good balance of size and features.
FROM python:3.9-slim-buster

# Set the working directory inside the container
WORKDIR /app

# Install system dependencies, including FFmpeg
# apt-get update: Updates the list of available packages
# apt-get install -y: Installs packages without asking for confirmation
# ffmpeg: The multimedia framework required by yt-dlp for post-processing (e.g., MP3 conversion, merging)
# build-essential: Needed if you have any Python packages that require compilation (good practice)
# libsm6 libxext6: Common dependencies for some video/audio libraries
RUN apt-get update && \
    apt-get install -y --no-install-recommends ffmpeg build-essential libsm6 libxext6 && \
    rm -rf /var/lib/apt/lists/*

# Copy the requirements file into the working directory
COPY requirements.txt ./requirements.txt

# Install Python dependencies
# --no-cache-dir: Reduces image size by not caching pip packages
# --upgrade pip: Ensures pip is up-to-date
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy the Streamlit application file into the working directory
COPY app.py ./app.py

# Expose the port that Streamlit runs on (default is 8501)
EXPOSE 8501

# Command to run the Streamlit application
# --server.port sets the port for Streamlit
# --server.enableCORS=false is often used in Docker to avoid CORS issues
CMD ["streamlit", "run", "app.py", "--server.port=8501", "--server.enableCORS=false"]
