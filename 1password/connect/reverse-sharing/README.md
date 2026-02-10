# Basic 1Password Connect Item Creator Webapp

A very simple web application built with Flask and deployable via Docker. It provides a basic web form to create new Login items in a specified 1Password vault using the 1Password Connect REST API. **Note:** This version is a proof of concept that can be deployed locally. For production use, look at our [connect documentation](https://developer.1password.com/docs/connect/get-started/).

## Features

- **Create 1Password Items:** Simple web form to input Title, Username, Password, and Notes for new Login items.
- **1Password Connect Integration:** Interacts directly with your 1Password Connect server API.
- **Web Interface:** Minimal interface built with Flask.
- **Dockerized:** Easy deployment using Docker.
- **Configuration via Environment:** Essential 1Password Connect settings are managed through environment variables.

## 1Password Setup

1. Create a vault in 1Password exclusively for this application and note the UUID.
2. In 1Password admin console, go to Developer -> Connect servers and create a new connect server with `Read, Write` permissions to that vault. Save the 1password-credentials.json file and place in this directory.
3. Create an access token with only `write` permissions to that vault.
4. Copy the token and save it securely. You will need it to create items in the vault.

## Prerequisites

Before you begin, ensure you have the following installed and configured:

1. **Docker Engine:** [Install Docker](https://docs.docker.com/engine/install/)
2. **Environment Variables:** Set up the following environment variables in a `.env` file in this directory:
   - `OP_VAULT_UUID`: The UUID of the target 1Password vault.
   - `FLASK_SECRET_KEY`: (Recommended) A secret key for Flask, needed for features like flashing messages. While not strictly required for _this specific basic version's core function_, it's good practice to include it. Generate a random string (e.g., using `openssl rand -hex 32`).

## Project Structure

Ensure you have the following files in your project directory:

```
├── app.py # Flask application logic
├── Dockerfile # Docker build instructions
├── docker-compose.yml # Docker Compose file for easier management
├── requirements.txt # Python dependencies
├── README.md # This file
├── 1password-credentials.json # Credentials file for 1Password Connect
├── .env file # Environment variables for Docker Compose
└── templates/
    └── index.html # HTML form template for creating items
    └── login.html # HTML form template for entering bearer token
```

## Running the Application

1. **Navigate:** Open a terminal or command prompt and navigate to the project directory containing the `Dockerfile` and application files.
2. **Build and run the Docker Image, tailing the logs:**

   ```bash
   docker compose up -d --build && docker compose logs -f webapp
   ```

3. **Access the Application:** Open your web browser and navigate to `http://localhost:5001`. Enter the bearer token with write access to the target vault (the API token for your 1Password Connect server) in the form.
4. **Create Item:** Fill in the Title (required), Username, Password, and Notes fields for the new 1Password Login item.
5. **Submit:** Click "Create Item". You will see a success or error message displayed on the page.
6. **Check 1Password:** Log in to your 1Password account and check the specified vault to see the newly created item.
