import os
import requests
from flask import Flask, request, render_template, flash, session, redirect, url_for

app = Flask(__name__)

# --- Configuration from Environment Variables ---
# REQUIRED: Secret key for session management.
app.config["SECRET_KEY"] = os.environ.get(
    "FLASK_SECRET_KEY", "dev-secret-key-replace-in-prod"
)
if (
    app.config["SECRET_KEY"] == "dev-secret-key-replace-in-prod"
    and os.environ.get("FLASK_ENV") != "development"
):
    app.logger.warning(
        "WARNING: Using default FLASK_SECRET_KEY in a non-development environment!"
    )

# 1Password Connect API configuration
OP_CONNECT_HOST = os.environ.get("OP_CONNECT_HOST")
OP_VAULT_UUID = os.environ.get("OP_VAULT_UUID")  # Still needed for creating items

# --- Helper Functions ---


def validate_op_token(user_token):
    """
    Validates the user-provided token by making a heartbeat API call.
    Returns True if valid, False otherwise.
    """
    if not OP_CONNECT_HOST:
        app.logger.error("OP_CONNECT_HOST is not set. Cannot validate token.")
        return False

    heartbeat_url = f"{OP_CONNECT_HOST.rstrip('/')}/heartbeat"
    headers = {"Authorization": f"Bearer {user_token}", "Accept": "application/json"}
    try:
        response = requests.get(
            heartbeat_url, headers=headers, timeout=5
        )  # 5-second timeout
        # A 200 OK response means the server is alive and the token is valid for this basic check.
        if response.status_code == 200:
            app.logger.info(f"Token validation successful via heartbeat.")
            return True
        else:
            app.logger.warning(
                f"Token validation failed. Heartbeat status: {response.status_code}, Response: {response.text}"
            )
            return False
    except requests.exceptions.RequestException as e:
        app.logger.error(f"Error during token validation heartbeat request: {e}")
        return False


def create_op_item(title, username, password, notes, user_token):
    """
    Uses the 1Password Connect API to create a new Login item.
    Uses the token provided by the user (and stored in session).
    """
    if not all([OP_CONNECT_HOST, user_token, OP_VAULT_UUID]):
        app.logger.error(
            "Server configuration error or missing user token for item creation."
        )
        return False, "Server configuration error or missing API token for request."

    api_url = f"{OP_CONNECT_HOST.rstrip('/')}/v1/vaults/{OP_VAULT_UUID}/items"
    headers = {
        "Authorization": f"Bearer {user_token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    payload = {
        "vault": {"id": OP_VAULT_UUID},
        "title": title,
        "category": "LOGIN",
        "fields": [
            (
                {
                    "id": "username",
                    "label": "username",
                    "type": "STRING",
                    "purpose": "USERNAME",
                    "value": username or "",
                }
                if username
                else None
            ),
            (
                {
                    "id": "password",
                    "label": "password",
                    "type": "CONCEALED",
                    "purpose": "PASSWORD",
                    "value": password or "",
                }
                if password
                else None
            ),
            # Using notesPlain as it's simpler for this example.
            # For structured notes, you'd add another field object with purpose NOTES.
            (
                {
                    "id": "notes",
                    "label": "notes",
                    "type": "STRING",
                    "purpose": "NOTES",
                    "value": notes or "",
                }
                if notes
                else None
            ),
        ],
    }
    payload["fields"] = [field for field in payload["fields"] if field is not None]
    if (
        not payload["fields"] and notes
    ):  # If only notes are provided and fields is empty
        payload["notesPlain"] = notes  # Fallback to notesPlain if no other fields
    elif not payload["fields"]:
        del payload["fields"]

    try:
        response = requests.post(
            api_url, headers=headers, json=payload, timeout=15
        )  # Increased timeout
        response.raise_for_status()
        return True, f"Successfully created item '{title}' in vault {OP_VAULT_UUID}."
    except requests.exceptions.HTTPError as http_err:
        error_message = f"API Request Failed with status {response.status_code}"
        try:
            error_details = response.json()
            error_message += (
                f" - {error_details.get('message', 'No additional details from API.')}"
            )
        except ValueError:
            error_message += f" - Response: {response.text}"
        app.logger.error(
            f"HTTPError during 1P item creation: {error_message} for item '{title}'"
        )
        return False, error_message
    except requests.exceptions.RequestException as e:
        app.logger.error(
            f"RequestException during 1P item creation: {e} for item '{title}'"
        )
        return False, f"Failed to communicate with the 1Password Connect API: {e}"
    except Exception as e:
        app.logger.error(
            f"An unexpected error occurred during item creation: {e} for item '{title}'"
        )
        return False, "An unexpected error occurred."


# --- Routes ---


@app.route("/login", methods=["GET", "POST"])
def login():
    """Handles the token submission and validation via API call."""
    if request.method == "POST":
        entered_token = request.form.get("api_token")

        if not entered_token:
            flash("API Token is required.", "error")
            return redirect(url_for("login"))

        if not OP_CONNECT_HOST:
            app.logger.critical(
                "OP_CONNECT_HOST is not configured on the server. Cannot validate token."
            )
            flash(
                "Application configuration error. Please contact administrator.",
                "error",
            )
            return redirect(url_for("login"))

        if validate_op_token(entered_token):
            session["op_connect_token"] = entered_token
            session["authenticated"] = True
            flash("Login successful!", "success")
            return redirect(url_for("index"))
        else:
            flash(
                "Invalid API Token or failed to connect to 1Password Connect server.",
                "error",
            )
            return redirect(url_for("login"))

    if session.get("authenticated"):
        return redirect(url_for("index"))

    return render_template("login.html")


@app.route("/logout")
def logout():
    """Clears the session to log the user out."""
    session.pop("op_connect_token", None)
    session.pop("authenticated", None)
    flash("You have been logged out.", "info")
    return redirect(url_for("login"))


@app.route("/", methods=["GET", "POST"])
def index():
    """Main page for creating 1Password items. Requires validated token in session."""
    if not session.get("authenticated") or not session.get("op_connect_token"):
        flash("Please login with your API token first.", "info")
        return redirect(url_for("login"))

    # Ensure server is configured with essential variables for item creation
    if not all([OP_CONNECT_HOST, OP_VAULT_UUID]):
        app.logger.error(
            "FATAL: Server is missing critical 1Password Connect environment variables (OP_CONNECT_HOST, OP_VAULT_UUID) for item creation."
        )
        flash(
            "Application is not configured correctly to create items. Please contact the administrator.",
            "error",
        )
        session.pop("op_connect_token", None)  # Log out user as app is misconfigured
        session.pop("authenticated", None)
        return redirect(url_for("login"))

    message = None
    success = False
    if request.method == "POST":
        title = request.form.get("title")
        username = request.form.get("username")
        password = request.form.get("password")
        notes = request.form.get("notes")

        user_token_from_session = session.get("op_connect_token")

        if not title:
            message = "Title field is required."
            success = False
        # user_token_from_session should always exist due to the check at the beginning of this route
        else:
            success, message = create_op_item(
                title, username, password, notes, user_token_from_session
            )

        return render_template("index.html", message=message, success=success)

    return render_template("index.html")


if __name__ == "__main__":
    if (
        not app.config["SECRET_KEY"]
        or app.config["SECRET_KEY"] == "dev-secret-key-replace-in-prod"
    ):
        print("*" * 30)
        print(
            "WARNING: FLASK_SECRET_KEY is not set or is using the default development key."
        )
        print(
            "Please set a strong, random FLASK_SECRET_KEY environment variable for production."
        )
        print("*" * 30)

    if not OP_CONNECT_HOST:
        print("*" * 30)
        print(
            "ERROR: Missing OP_CONNECT_HOST environment variable! Cannot validate tokens or make API calls."
        )
        print("*" * 30)
        # exit(1) # Critical, might want to exit

    if not OP_VAULT_UUID:
        print("*" * 30)
        print(
            "WARNING: Missing OP_VAULT_UUID environment variable! Item creation will fail."
        )
        print("*" * 30)

    app.run(debug=True, host="0.0.0.0", port=5000)
