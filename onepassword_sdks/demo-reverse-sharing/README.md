# 1Password SDK Demo: Reverse Sharing - Item Creator

This project is a simple Flask web application that demonstrates how to use the 1Password Python SDK to create new "Login" items in a specified 1Password vault. It serves as an example of "reverse sharing," where an application programmatically adds credentials or other information to a 1Password vault.

## Features

- Web interface to input details for a new 1Password Login item (title, username, password, notes).
- Uses the 1Password Python SDK for secure interaction with your 1Password account.
- Configuration via environment variables for easy setup.
- Includes Docker and Docker Compose configurations for containerized deployment.

## Prerequisites

Before you begin, ensure you have the following:

- **Python 3.7+** (Python 3.9 is used in the Dockerfile)
- **Pip** (Python package installer)
- **1Password Account** with a Service Account configured.
  - You'll need the **Service Account Token**.
  - You'll need the **UUID of the vault** where you want to create items.
- **Docker** and **Docker Compose** (Optional, for containerized deployment)

## Setup

1. **Clone the repository (if you haven't already):**

   ```bash
   git clone <your-repository-url>
   cd demo-reverse-sharing
   ```

2. **Create and configure the `.env` file:**
   Copy the example `.env.example` (if you have one) or create a new `.env` file in the project root:

   ```dotenv
   # .env file
   OP_SERVICE_ACCOUNT_TOKEN="your_1password_service_account_token"
   OP_VAULT_UUID="your_target_1password_vault_uuid"
   FLASK_SECRET_KEY="a_very_strong_random_secret_key_for_flask_sessions"
   FLASK_DEBUG=true # Set to false for production
   ```

   **Important:**

   - Replace placeholders with your actual 1Password Service Account Token and Vault UUID.
   - Generate a strong, unique `FLASK_SECRET_KEY`. You can use `python -c 'import secrets; print(secrets.token_hex(24))'` to generate one.
   - The `FLASK_SECRET_KEY` can also be a 1Password secret reference like `op://connect-secrets/flask-secret-key/credential` if you are using 1Password Connect for secret injection, but for local development, a direct value is simpler. The provided `.env` file shows this pattern.

3. **Install Python dependencies:**
   It's recommended to use a virtual environment:

   ```bash
   python3 -m venv venv
   source venv/bin/activate  # On Windows use `venv\Scripts\activate`
   pip install -r requirements.txt
   ```

## Running the Application

You have a few options to run the application:

### 1. Directly with Python

Ensure your `.env` file is configured and you have activated your virtual environment.

```bash
python app.py
```

The application will be available at `http://127.0.0.1:5000` (or `http://0.0.0.0:5000`).

### 2. Using Docker

This method builds a Docker image and runs the application in a container.

1. **Build the Docker image:**

   ```bash
   docker build -t op-sdk-item-creator .
   ```

2. **Run the Docker container:**
   You'll need to pass the environment variables from your `.env` file (or directly).

   ```bash
   docker run -p 5001:5000 \
     --env-file .env \
     op-sdk-item-creator
   ```

   The application will be available at `http://localhost:5001`.

### 3. Using Docker Compose

This is often the easiest way for local development with containers.

1. **Ensure your `.env` file is present and correctly configured in the same directory as `docker-compose.yml`.** Docker Compose will automatically pick it up.

2. **Start the application:**

   ```bash
   docker-compose up
   ```

   To run in detached mode (in the background):

   ```bash
   docker-compose up -d
   ```

   The application will be available at `http://localhost:5001`.

3. **To stop the application:**

   ```bash
   docker-compose down
   ```

## Usage

1. Open your web browser and navigate to the application (e.g., `http://localhost:5001` if using Docker Compose or the Docker run command above, or `http://localhost:5000` if running directly with Python).
2. You will see a form to create a new 1Password Login item.
3. Fill in the "Title", "Username", "Password", and "Notes" fields. The "Title" field is required.
4. Click "Create Item".
5. The application will attempt to create the item in your configured 1Password vault using the SDK.
6. You will see a success or error message displayed on the page.

## Configuration Details

The application uses the following environment variables (typically set in the `.env` file):

- `OP_SERVICE_ACCOUNT_TOKEN`: Your 1Password Service Account token. **Required.**
- `OP_VAULT_UUID`: The UUID of the 1Password vault where new items will be created. **Required.**
- `FLASK_SECRET_KEY`: A secret key used by Flask for session management and security. **Required for production.** If not set, a less secure fallback is used, and a warning is issued.
- `FLASK_DEBUG`: Set to `true` for development mode (enables debug output and auto-reloader). Defaults to `false` (production mode).

## Security Notes

- **`FLASK_SECRET_KEY`**: It is crucial to set a strong, unique `FLASK_SECRET_KEY` for your application, especially in production. Do not use the default or a weak key.
- **`OP_SERVICE_ACCOUNT_TOKEN`**: Treat your 1Password Service Account Token like a password. Keep it confidential and secure. Do not commit it directly into your version control system if the repository is public. The `.env` file approach helps keep it out of he codebase.
- **Error Handling**: The application includes basic error handling and will display messages if item creation fails or if critical configurations are missing. Check the application logs for more detailed error information.

## Project Structure

```bash
.
├── .env                  # Local environment variables (ignored by git)
├── app.py                # Main Flask application logic
├── Dockerfile            # Instructions to build the Docker image
├── docker-compose.yml    # Docker Compose configuration
├── requirements.txt      # Python dependencies
└── templates/
    └── index.html        # HTML template for the web interface
```

---

This demo provides a basic framework. You can extend it further, for example, by adding support for different item categories, custom fields, or more robust error handling and user feedback.
