# 1Password Vault Migration App

This web app allows you to move vaults from one 1Password account to another. It uses the 1Password JS SDK, as well as 1Password CLI to handle actions not yet supported by the SDK at this time.

## Overview

This app helps you to move vaults between 1Password accounts by:

- Giving you a simple web page to connect to your source and destination 1Password accounts using service account tokens.
- Showing you all the vaults from the source account so you can pick which ones to move.
- Moving the vaults you select (or all of them) to the destination account.
- Using a mix of the SDK and CLI to handle certain tasks.

## Requirements

- [Docker](https://docs.docker.com/get-started/get-docker/)
- [1Password CLI](https://developer.1password.com/docs/cli/get-started)
- [1Password Service Account](https://developer.1password.com/docs/service-accounts/get-started#create-a-service-account) that can access your source and destination accounts:
  - The source token needs read access, so it can see vaults and items in the source account.
  - The destination token needs create vault permissions, so it can make new vaults and add items in the destination vault.

## Installation

1. [Install Docker on your computer](https://docs.docker.com/get-started/get-docker/)
2. Clone or download this project to your computer.
3. In your terminal, navigate to the project folder. To build and run the Docker image with the Dockerfile, run the following in your terminal:
```
docker compose up -d
```

## Usage

1. Open your browser and go to `https://localhost:3001`.
2. On the welcome page, click **Vault Migration** in the sidebar to get to the migration tool.
3. Enter the 1Password service account tokens for your source and destination accounts in the Migration Setup form, then select **Connect**.
4. You’ll see a table with all the vaults from the source account. You can:
   - Check the boxes for the vaults you want to move and select **Migrate Selected Vaults**.
   - Select **Migrate All Vaults** to move everything.
5. Verify your information is in the destination account once the vault migration completes.

## Special Handling with CLI

- **Vault Creation**: The app uses 1Password CLI (`op vault create`) to make new vaults in the destination account, since vault creation isn't yet supported by the SDK.

## Security Features

- Runs on HTTPS with a self-signed certificate (good for local testing).
- Keeps service account tokens in `sessionStorage` on the browser side, so they’re not stored on the server.
- Has retry logic that waits longer each time if the API says "too many requests" or there’s a conflict.
- Uses `p-limit` to make sure we don’t send too many requests at once and overwhelm the 1Password API.

## Troubleshooting

If something goes wrong:

- Make sure Docker is installed and running on your computer.
- Double-check your 1Password service account tokens for both source and destination accounts—they need to be valid, with read access for the source token and create vaults for the destination token.
- Make sure the Docker container is running and you can reach it at `https://localhost:3001`. You can see the logs with `docker logs <container-name>` to figure out what’s up.
- If your browser complains about SSL, just accept the self-signed certificate for `localhost`.

## Limitations

- Neither the 1Password SDK, CLI, nor vault data export can access or report on passkey fields. To transfer passkeys between 1Password accounts, use the 1Password desktop or mobile app.
- The SDK does not natively support retrieving archived items for vault migration.
- The application uses a self-signed certificate for HTTPS, suitable for local testing but requiring a valid certificate for production deployment.
- Vault names cannot be modified during migration; the script appends "(Migrated)" to the destination vault names.
- The application has fixed concurrency limits (2 vaults and 1 item processed simultaneously), which may need adjustment for large-scale migrations.