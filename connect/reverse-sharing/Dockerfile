# Use an official Python runtime as a parent image
FROM python:3.13-alpine

# Set the working directory in the container
WORKDIR /app

# Copy the dependencies file to the working directory
COPY requirements.txt .

# Install any needed packages specified in requirements.txt
# --no-cache-dir reduces image size
# --trusted-host pypi.python.org can sometimes help bypass network issues in restricted environments
RUN pip install --no-cache-dir --trusted-host pypi.python.org -r requirements.txt

# Copy the current directory contents into the container at /app
COPY . .

# Make port 5000 available to the world outside this container
# Note: Gunicorn will bind to this port. Flask dev server also uses it by default.
EXPOSE 5000

# Define environment variables (placeholders, should be set during 'docker run')
# These are just examples, DO NOT HARDCODE secrets here.
# ENV OP_VAULT_UUID=your_vault_id
# ENV FLASK_SECRET_KEY=set_a_strong_secret_key_here

# Run app.py using gunicorn when the container launches
# Gunicorn is a production-ready WSGI server.
# --bind 0.0.0.0:5000 makes the app accessible from outside the container.
# app:app refers to the Flask application instance 'app' found in the file 'app.py'.
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "app:app"]