import azure.functions as func
import logging
import os
import json
import subprocess
import sys

from onepassword.client import Client
from onepassword import (
    AutofillBehavior,
    ItemCreateParams,
    ItemCategory,
    ItemField,
    ItemFieldType,
    ItemShareParams,
    ItemShareDuration,
    Website,
)

app = func.FunctionApp(http_auth_level=func.AuthLevel.FUNCTION)


@app.route(route="create-shared-item", methods=["POST"])
async def create_shared_item(req: func.HttpRequest) -> func.HttpResponse:
    logging.info("Received request to create + share 1Password item")

    # --- Parse and validate request body ---
    try:
        body = req.get_json()
    except ValueError:
        return _json_error("Request body must be valid JSON", 400)

    title = body.get("title")
    username = body.get("username")
    password = body.get("password")
    website = body.get("website")
    recipient_emails = body.get("recipients", [])  # optional; empty = anyone with link
    expire_after = body.get("expireAfter", "SEVEN_DAYS")
    one_time_only = bool(body.get("oneTimeOnly", False))

    if not (title and username and password):
        return _json_error(
            "Fields 'title', 'username', and 'password' are required", 400
        )

    # --- Pull config from environment ---
    token = os.environ.get("OP_SERVICE_ACCOUNT_TOKEN")
    vault_id = os.environ.get("OP_VAULT_ID")
    if not (token and vault_id):
        logging.error("Missing OP_SERVICE_ACCOUNT_TOKEN or OP_VAULT_ID")
        return _json_error("Server misconfiguration", 500)

    integration_name = os.environ.get("OP_INTEGRATION_NAME", "1Password Azure Function")
    integration_version = os.environ.get("OP_INTEGRATION_VERSION", "v1.0.0")

    # --- Talk to 1Password ---
    try:
        client = await Client.authenticate(
            auth=token,
            integration_name=integration_name,
            integration_version=integration_version,
        )

        # Create the login item
        fields = [
            ItemField(
                id="username",
                title="username",
                field_type=ItemFieldType.TEXT,
                value=username,
            ),
            ItemField(
                id="password",
                title="password",
                field_type=ItemFieldType.CONCEALED,
                value=password,
            ),
        ]

        create_params = ItemCreateParams(
            title=title,
            category=ItemCategory.LOGIN,
            vault_id=vault_id,
            fields=fields,
        )
        if website:
            create_params.websites = [
                Website(
                    url=website,
                    label="website",
                    autofill_behavior=AutofillBehavior.ANYWHEREONWEBSITE,
                )
            ]

        item = await client.items.create(create_params)
        logging.info("Created item %s in vault %s", item.id, vault_id)

        # Fetch share policy for the account/vault
        policy = await client.items.shares.get_account_policy(vault_id, item.id)

        # If specific recipients were passed, validate them against the policy
        valid_recipients = []
        if recipient_emails:
            valid_recipients = await client.items.shares.validate_recipients(
                policy, recipient_emails
            )

        duration_map = {
            "ONE_HOUR": ItemShareDuration.ONEHOUR,
            "ONE_DAY": ItemShareDuration.ONEDAY,
            "SEVEN_DAYS": ItemShareDuration.SEVENDAYS,
            "FOURTEEN_DAYS": ItemShareDuration.FOURTEENDAYS,
            "THIRTY_DAYS": ItemShareDuration.THIRTYDAYS,
        }

        share_params = ItemShareParams(
            recipients=valid_recipients,
            expireAfter=duration_map.get(expire_after, ItemShareDuration.SEVENDAYS),
            oneTimeOnly=one_time_only,
        )

        share_link = await client.items.shares.create(item, policy, share_params)
        logging.info("Generated share link for item %s", item.id)

        return func.HttpResponse(
            json.dumps(
                {
                    "itemId": item.id,
                    "vaultId": vault_id,
                    "shareLink": share_link,
                    "expireAfter": expire_after,
                    "oneTimeOnly": one_time_only,
                }
            ),
            status_code=200,
            mimetype="application/json",
        )

    except Exception as exc:
        logging.exception("Failed to create or share item")
        return _json_error(f"1Password operation failed: {exc}", 500)


def _json_error(message: str, status_code: int) -> func.HttpResponse:
    return func.HttpResponse(
        json.dumps({"error": message}),
        status_code=status_code,
        mimetype="application/json",
    )
