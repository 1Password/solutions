import os
import asyncio
from flask import Flask, request, render_template, flash, redirect, url_for, session
from dotenv import load_dotenv

# Import 1Password SDK components
from onepassword import *

from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)

# --- Configuration from Environment Variables ---
app.config["SECRET_KEY"] = os.environ.get("FLASK_SECRET_KEY")
if not app.config["SECRET_KEY"]:
    app.logger.warning(
        "FLASK_SECRET_KEY is not set! Flash messages and session security may be compromised."
    )
    app.config["SECRET_KEY"] = "dev-fallback-secret-key-for-flask"

load_dotenv(".env")
OP_SERVICE_ACCOUNT_TOKEN = os.environ.get("OP_SERVICE_ACCOUNT_TOKEN")
OP_VAULT_UUID = os.environ.get("OP_VAULT_UUID")


async def create_op_item_sdk(title, username_val, password_val, notes_content):
    """
    Uses the 1Password Python SDK to create a new Login item,
    using ItemCreateParams and ItemFieldParams.
    """
    app.logger.info("Attempting to initialize 1Password SDK client...")
    op_client = await Client.authenticate(
        auth=OP_SERVICE_ACCOUNT_TOKEN,
        integration_name="FlaskWebApp-1PItemCreator",
        integration_version="1.1.0",  # Example version
    )

    if not op_client:
        app.logger.error(f"SDK not available for item creation")
        return False, "1Password SDK client is not initialized."

    if not OP_VAULT_UUID:
        app.logger.error("OP_VAULT_UUID is not set. Cannot create item.")
        return False, "Target vault (OP_VAULT_UUID) is not configured on the server."

    try:
        app.logger.info(
            f"Constructing item '{title}' for vault '{OP_VAULT_UUID}' using ItemCreateParams."
        )

        fields_to_add = []
        if username_val:
            fields_to_add.append(
                ItemField(
                    id="username",
                    title="Username",
                    value=username_val,
                    fieldType=ItemFieldType.TEXT,
                )
            )
        if password_val:
            fields_to_add.append(
                ItemField(
                    id="password",
                    title="Password",
                    value=password_val,
                    fieldType=ItemFieldType.CONCEALED,
                )
            )

        item_payload = ItemCreateParams(
            vault_id=OP_VAULT_UUID,
            category=ItemCategory.LOGIN,
            title=title,
            fields=(
                fields_to_add if fields_to_add else None
            ),  # Pass None if no fields, or SDK might expect empty list
            notes=notes_content if notes_content else None,  # Pass notes if provided
        )

        app.logger.info(
            f"Attempting to create item '{title}' via SDK with direct params."
        )
        # The client.items.create method expects the ItemCreateParams object directly
        created_item = await op_client.items.create(item_payload)

        app.logger.info(
            f"Successfully created item '{created_item.title}' (ID: {created_item.id}) via SDK."
        )
        return (
            True,
            f"Successfully created item '{created_item.title}' (ID: {created_item.id}).",
        )
    except Exception as e:
        error_msg = f"An unexpected error occurred during SDK item creation: {e}"
        app.logger.error(error_msg)
        return False, error_msg


@app.route("/", methods=["GET", "POST"])
async def index():
    """Main page for creating 1Password items using the SDK."""

    if not OP_VAULT_UUID:
        flash(
            "Application Configuration Error: Target vault (OP_VAULT_UUID) is not set. Item creation is disabled.",
            "error",
        )
        return render_template(
            "index.html",
            sdk_error="OP_VAULT_UUID not set.",
            title_val="",
            username_val="",
            password_val="",
            notes_val="",
        )

    message = None
    success = False
    title_val = request.form.get("title", "")
    username_val = request.form.get("username", "")
    # Password is not re-populated in the form for security upon re-render
    notes_val = request.form.get("notes", "")

    if request.method == "POST":
        # Get password directly from form for POST, as it's not in title_val etc.
        password_from_form = request.form.get("password", "")

        if not title_val:
            flash("Title field is required.", "error")
        else:
            success, message = await create_op_item_sdk(
                title_val, username_val, password_from_form, notes_val
            )
            if success:
                flash(message, "success")
                return redirect(url_for("index"))  # Clear form on success
            else:
                flash(message, "error")

        # Re-render with current form values (except password) if there was an error
        return render_template(
            "index.html",
            message=message,
            success=success,
            title_val=title_val,
            username_val=username_val,
            password_val="",
            notes_val=notes_val,
            sdk_error=None,
        )

    return render_template(
        "index.html",
        title_val="",
        username_val="",
        password_val="",
        notes_val="",
        sdk_error=None,
    )


if __name__ == "__main__":
    if (
        not app.config["SECRET_KEY"]
        or app.config["SECRET_KEY"] == "dev-fallback-secret-key-for-flask"
    ):
        app.logger.warning(
            "CRITICAL: FLASK_SECRET_KEY is not set or using fallback. Set a strong secret key in environment."
        )

    if not OP_SERVICE_ACCOUNT_TOKEN:
        app.logger.critical(
            "CRITICAL: OP_SERVICE_ACCOUNT_TOKEN is not set. The application will not be able to interact with 1Password."
        )

    if not OP_VAULT_UUID:
        app.logger.warning(
            "WARNING: OP_VAULT_UUID is not set. Item creation will fail."
        )
    app.run(
        debug=os.environ.get("FLASK_DEBUG", "false").lower() == "true",
        host="0.0.0.0",
        port=5000,
    )
