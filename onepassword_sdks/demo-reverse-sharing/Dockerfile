# Use an official Python runtime as a parent image
# Adjust the Python version if you are using 3.13 specifically, e.g., python:3.13-slim
FROM python:3.9-slim

# Set the working directory in the container
WORKDIR /app

# Install libgcc1 which provides libgcc_s.so.1
# Also good practice to clean up apt lists afterwards to keep image size down
RUN apt-get update && \
    apt-get install -y libgcc1 && \
    rm -rf /var/lib/apt/lists/*

# Copy the dependencies file to the working directory
COPY requirements.txt .

# Install any needed packages specified in requirements.txt
# Using --no-cache-dir to reduce image size
RUN pip install --no-cache-dir -r requirements.txt

# Copy the current directory contents into the container at /app
COPY . .

# Make port 5000 available to the world outside this container
EXPOSE 5000

# Define environment variables that need to be set during 'docker run'
# These are placeholders; actual values should be provided at runtime.
# ENV OP_SERVICE_ACCOUNT_TOKEN=your_service_account_token
# ENV OP_VAULT_UUID=your_target_vault_uuid
# ENV FLASK_SECRET_KEY=your_strong_flask_secret_key
# ENV FLASK_DEBUG=false # Set to true for development debugging

# Run app.py using gunicorn when the container launches
# Gunicorn is a production-ready WSGI server.
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "app:app"]
