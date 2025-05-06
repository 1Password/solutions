# Basic 1Password Connect Item Creator Webapp

A very simple web application built with Flask and deployable via Docker. It provides a basic web form to create new Login items in a specified 1Password vault using the 1Password Connect REST API. **Note:** This version does not include any user authentication.

## Features

- **Create 1Password Items:** Simple web form to input Title, Username, Password, and Notes for new Login items.
- **1Password Connect Integration:** Interacts directly with your 1Password Connect server API.
- **Web Interface:** Minimal interface built with Flask.
- **Dockerized:** Easy deployment using Docker.
- **Configuration via Environment:** Essential 1Password Connect settings are managed through environment variables.

## 1Password Setup

1. Create a vault in 1Password exclusively for this application.
2. In 1Password admin console, go to Developer -> Connect servers and create a new connect server with Read, Write permissions to that vault.
3. Create an access token with only write permissions to that vault.
4. Copy the token and save it securely. You will need it to create items in the vault.

## Prerequisites

Before you begin, ensure you have the following installed and configured:

1. **Docker Engine:** [Install Docker](https://docs.docker.com/engine/install/)

## Project Structure

Ensure you have the following files in your project directory:

```
├── app.py # Flask application logic
├── Dockerfile # Docker build instructions
├── docker-compose.yml # Docker Compose file for easier management
├── requirements.txt # Python dependencies
├── README.md # This file
├── 1password-credentials.json # Credentials file for 1Password Connect
└── templates/
    └── index.html # HTML form template for creating items
    └── login.html # HTML form template for entering bearer token
```

## Configuration

This application requires essential 1Password Connect details provided as environment variables when running the Docker container.

- `OP_VAULT_UUID`: The UUID of the target 1Password vault.
- `FLASK_SECRET_KEY`: (Recommended) A secret key for Flask, needed for features like flashing messages. While not strictly required for _this specific basic version's core function_, it's good practice to include it. Generate a random string (e.g., using `openssl rand -hex 32`).

## Running the Application

1. **Navigate:** Open a terminal or command prompt and navigate to the project directory containing the `Dockerfile` and application files.
2. **Build the Docker Image:**

   ```bash
   docker build -t op-connect-webapp-basic .
   ```

3. **Run the Docker Container:** Replace the placeholder values with your actual configuration details.

   ```bash
   docker run -d \
     -p 5000:5000 \
     -e OP_VAULT_UUID="YOUR_TARGET_VAULT_UUID" \
     -e FLASK_SECRET_KEY="generate-a-strong-random-secret" \
     --name my-basic-op-app \
     op-connect-webapp-basic
   ```

   - `-d`: Run in detached mode (background).
   - `-p 5000:5000`: Map port 5000 on your host to port 5000 in the container.
   - `-e VARIABLE="VALUE"`: Set the required environment variables.
   - `--name my-basic-op-app`: Assign a name to the container.

## Usage

1. **Access:** Open your web browser and navigate to `http://localhost:5000` (or the IP address of your Docker host if running remotely).
2. **Enter the bearer token:** In the form, enter the connect token with write access to the target vault (the API token for your 1Password Connect server).
3. **Create Item:** Fill in the Title (required), Username, Password, and Notes fields for the new 1Password Login item.
4. **Submit:** Click "Create Item". You will see a success or error message displayed on the page.

## Stopping the Application

1. **Stop the container:**

   ```bash
   docker stop my-basic-op-app
   ```

2. **Remove the container:** (Optional, if you don't need it anymore)

   ```bash
   docker rm my-basic-op-app
   ```
