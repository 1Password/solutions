# Azure Function for 1Password Item Creation + Share Link Generation

**A step-by-step Azure Portal guide — no terminal commands required.**

A reference implementation for creating 1Password items and generating share links from an Azure Function App, using the official 1Password Python SDK.

---

## 1. Why this approach (and what it solves)

The most common stumbling block when running 1Password automation on Azure is **containerization**: the `op` CLI is distributed as a binary, which means a Dockerfile, an Azure Container Registry, and an image build pipeline. For teams without prior container experience, that's a significant detour. This guide sidesteps the problem entirely by using the **official 1Password Python SDK** instead of the `op` CLI.

The Python SDK is a single `pip` dependency, installable through `requirements.txt`. Azure Functions on the Flex Consumption plan installs `requirements.txt` automatically — no Dockerfile, no Azure Container Registry, no image pipeline.

The SDK covers both common requirements:

- Item creation (`client.items.create`)
- Share link generation (`client.items.shares.create`) — which the self-hosted Connect Server cannot do

**Note for PowerShell-first shops:** 1Password does not currently publish a PowerShell SDK. Going with Python adds one new language to the stack but removes the entire container build problem. A brief sketch of the PowerShell + container alternative is included at the end as a fallback.

### Architecture

```
HTTP webhook  ──POST──▶  Azure Function App (Python, Flex Consumption)
                               │
                               │  reads OP_SERVICE_ACCOUNT_TOKEN via
                               │  Key Vault reference (managed identity)
                               ▼
                         Azure Key Vault
                               │
                               ▼
                    1Password Python SDK
                    ├── items.create(...)   ──▶ new item in dedicated vault
                    └── items.shares.create(...) ──▶ share link
                               │
                               ▼
                    HTTP 200 { shareLink: "https://share.1password..." }
```

---

## 2. Prerequisites

Before starting, confirm you have:

- **1Password Business or Teams account** with owner/admin access (needed to create service accounts)
- **Azure subscription** with permission to create resource groups, Function Apps, and Key Vaults (Contributor or Owner on the target subscription)
- A browser signed in to [portal.azure.com](https://portal.azure.com)
- A GitHub account (used to deploy code via GitHub Actions — required for this guide; see Part D for why).

---

## 3. Part A — 1Password setup

### A1. Create a dedicated vault for one-off shares

A dedicated vault scoped to the service account is the recommended pattern for items intended to be shared via link. Only the service account should have access — no human users, no groups.

1. Open the 1Password web app (`[domain].1password.com`) or desktop app.
2. In the left sidebar, click **New Vault**.
3. Name it something like `Automated Shares` and save.
4. Do **not** grant any user or group access. Only the service account (next step) should reach it.
5. Copy the vault ID from the URL: it looks like `https://[domain].1password.com/vaults/abcd1234efgh5678ijklmnop` — the `abcd1234...` segment is the ID.

### A2. Create a service account with item + share permissions

1. In the 1Password admin dashboard, **Developer** → **Service Accounts**.
2. Click **New Service Account**.
3. Name it something descriptive like `azure-function-integration`.
4. Under **Vault Access**, add the `Automated Shares` vault with **Read, Write, and Share** permissions. The Share permission is mandatory — without it, `items.shares.create()` fails.
5. Also add any team-shared vaults your automation workflows need to write into, with at minimum **Read** and **Write**.
6. Click **Create** and **copy the token**. You will not see it again. Paste it somewhere temporary (a scratch note) for the next section — you'll move it to Azure Key Vault and then delete it from the scratch note.

---

## 4. Part B — Azure infrastructure (all in the Portal)

### B1. Create a resource group

1. In the Azure Portal, click **Create a resource** (top left).
2. Search for **Resource group** and click **Create**.
3. Fill in:

- **Subscription:** your subscription
- **Resource group name:** `rg-onepassword-automation`
- **Region:** pick one close to your primary webhook source (e.g., `East US`, `Canada Central`)

4. Click **Review + create** → **Create**.

### B2. Create the Key Vault

1. Click **Create a resource** → search **Key Vault** → **Create**.
2. **Basics** tab:

- **Resource group:** `rg-onepassword-automation`
- **Key vault name:** `kv-onepassword-<something-unique>` (must be globally unique)
- **Region:** same as the resource group
- **Pricing tier:** Standard

3. **Access configuration** tab:

- **Permission model:** select **Azure role-based access control** (RBAC). This is the modern default and is easier to reason about than access policies.

4. Leave the other tabs on defaults.
5. Click **Review + create** → **Create**.

### B3. Store the service account token as a secret

1. Open the Key Vault you just created.
2. You'll see a banner saying you don't have access to view secrets — that's expected with the RBAC model. Grant yourself access first:

- Click **Access control (IAM)** in the left blade.
- Click **Add** → **Add role assignment**.
- Role: **Key Vault Secrets Officer**
- Assign access to: **User, group, or service principal**
- Select your own account.
- **Review + assign**.

3. Wait ~60 seconds for the role to propagate, then in the Key Vault left blade, click **Secrets** → **Generate/Import**.
4. Fill in:

- **Upload options:** Manual
- **Name:** `OP-SERVICE-ACCOUNT-TOKEN` (Key Vault secret names can't contain underscores; use hyphens)
- **Secret value:** paste the service account token from step A2

5. Click **Create**.
6. Open the secret, click the current version, and **copy the Secret Identifier** (it's a URL like `https://kv-onepassword-xxx.vault.azure.net/secrets/OP-SERVICE-ACCOUNT-TOKEN/<version-id>`). You'll use this in step B6.
7. Delete the token from your scratch note.

### B4. Create the Function App

1. Click **Create a resource** → search **Function App** → **Create**.
2. On the **Select a hosting plan** screen, pick **Flex Consumption**. This plan supports Python 3.11, installs `requirements.txt` automatically, scales to zero, and charges per execution.
3. **Basics** tab:

- **Resource group:** `rg-onepassword-automation`
- **Function App name:** `func-onepassword-share-<unique>` (globally unique, becomes part of the URL)
- **Region:** same as the resource group
- **Runtime stack:** Python
- **Version:** 3.11 (or latest supported)
- **Instance size:** 2048 MB is plenty

4. **Storage** tab: accept defaults (a new storage account will be created).
5. **Networking** tab: accept defaults unless your organization requires private endpoints.
6. **Monitoring** tab: enable Application Insights (strongly recommended — this is how you'll debug).
7. **Deployment** tab: skip for now (we'll wire up deployment in Part D).
8. Click **Review + create** → **Create**. Provisioning takes 2–3 minutes.

### B5. Enable the Function App's system-assigned managed identity

1. Open the Function App resource.
2. In the left blade, find **Settings** → **Identity**.
3. On the **System assigned** tab, flip **Status** to **On**.
4. Click **Save**, confirm the prompt.
5. Copy the **Object (principal) ID** that appears — you don't strictly need it, but it's good to have.

### B6. Give the Function App read access to the Key Vault secret

1. Navigate back to your Key Vault.
2. Click **Access control (IAM)** → **Add** → **Add role assignment**.
3. Role: **Key Vault Secrets User** (read-only on secrets — least privilege).
4. Assign access to: **Managed identity**.
5. Click **Select members**, then in the dropdown pick **Function App** and select your function app name.
6. **Review + assign**.

### B7. Wire the secret into the Function App as an environment variable

The function code will read `OP_SERVICE_ACCOUNT_TOKEN` from its environment. Azure Functions supports **Key Vault references** that resolve secrets at startup without the app ever seeing the Key Vault URL as code.

1. Open the Function App.
2. In the left blade, go to **Settings** → **Environment variables**.
3. On the **App settings** tab, click **+ Add** and create the following entries one at a time. For the first, paste the Secret Identifier from B3 inside the Key Vault reference syntax.

| Name                       | Value                                                                   |
| -------------------------- | ----------------------------------------------------------------------- |
| `OP_SERVICE_ACCOUNT_TOKEN` | `@Microsoft.KeyVault(SecretUri=<paste the Secret Identifier URL here>)` |
| `OP_VAULT_ID`              | the vault ID you copied in step A1                                      |
| `OP_INTEGRATION_NAME`      | `Azure Function Integration`                                            |
| `OP_INTEGRATION_VERSION`   | `v1.0.0`                                                                |

4. Click **Apply** (at the bottom), then **Confirm**. The app will restart.
5. After ~30 seconds, refresh the page. The `OP_SERVICE_ACCOUNT_TOKEN` entry should show a green check next to it, meaning the Key Vault reference resolved successfully. A red X means the managed identity doesn't have permission yet — give it another minute and refresh.

---

## 5. Part C — Prepare the function code

You need three small files. Create them locally in a folder (call it `op-share-function/`) using any editor — Notepad works.

1. requirements.txt
2. host.json
3. function_app.py

---

## 6. Part D — Deploy the code (GitHub Actions)

This sets up an Azure-managed GitHub Actions pipeline that performs a **remote build** (running `pip install -r requirements.txt` on Azure). Every push to the repo auto-deploys, and updates take effect within a few minutes of committing a change.

> **Why GitHub Actions specifically:** On the Flex Consumption plan, the Kudu `/ZipDeployUI` page does **not** run `pip install`, and the `SCM_DO_BUILD_DURING_DEPLOYMENT` / `ENABLE_ORYX_BUILD` app settings are ignored. The remote-build trigger has to be passed by the deploy _client_, and the `Azure/functions-action@v1` GitHub Action is the only fully portal-driven path that does this. If you skip the GitHub Actions setup or omit the `remote-build: true` flag, the function will fail at startup with `ModuleNotFoundError: No module named 'onepassword'`.

### D1. Put the code in a new GitHub repository

1. Go to [github.com](https://github.com) and create a new **private** repository, e.g. `your-org/op-share-function`.
2. In the GitHub web UI, click **Add file** → **Upload files**. Drag in `function_app.py`, `requirements.txt`, and `host.json`. Commit to `main`.

### D2. Connect the Function App to the repo

1. In the Azure Portal, open your Function App.
2. Left blade → **Deployment** → **Deployment Center**.
3. **Source:** GitHub.
4. Click **Authorize** and sign in to GitHub.
5. Pick the **Organization**, **Repository**, and **Branch** (`main`).
6. **Workflow option:** **Add a workflow** (Azure generates a GitHub Actions YAML file and commits it to the repo).
7. **Authentication:** **User-assigned managed identity** is the cleanest option; let the portal create one for you, or use basic auth if your org permits it.
8. Click **Save**. Azure creates the workflow file in your repo and kicks off the first deployment.

### D3. Verify the workflow has `remote-build: true`

This is the critical step. In your GitHub repo, open `.github/workflows/<generated-name>.yml`. Find the `Azure/functions-action@v1` step and confirm it contains:

```yaml
- name: "Deploy to Azure Functions"
  uses: Azure/functions-action@v1
  with:
    app-name: ${{ env.AZURE_FUNCTIONAPP_NAME }}
    package: ${{ env.AZURE_FUNCTIONAPP_PACKAGE_PATH }}
    remote-build: true # REQUIRED for Flex Consumption
```

If `remote-build: true` isn't there, click the pencil icon to edit the YAML, add the line, and commit. The next push triggers a deploy that builds dependencies on the Azure side. Watch the **Actions** tab in your repo — you should see `pip install -r requirements.txt` running during the deploy.

### D4. Verify the install succeeded

Open Kudu (Function App → **Development Tools** → **Advanced Tools** → **Go**) and navigate in the browser to:

```
https://<your-func-app>.scm.azurewebsites.net/api/vfs/site/wwwroot/.python_packages/lib/site-packages/
```

You should see an `onepassword/` directory in the listing. If it's missing, the remote build didn't run — revisit step D3.

### D5. Redeploying after code changes

To push an update:

1. Edit the file in the GitHub web UI (click the file, then the pencil icon) or commit a change locally and `git push`.
2. Click the **Actions** tab in the repo to watch the workflow run. It takes 2–4 minutes — most of that is `pip install` on the Azure side.
3. When the workflow shows a green check, the new code is live. The Function App restarts automatically as part of the deploy.

For changes to **environment variables** (App Settings or Key Vault references) rather than code, no redeploy is needed — the Function App restarts automatically when you click **Apply** on the Environment variables page, and new values are picked up immediately.

> Don't edit code directly in the Azure Portal's **Code + Test** pane. Those changes will be overwritten by the next GitHub Actions deploy. Treat the repo as the source of truth.

---

## 7. Part E — Test it

### E1. Get the function URL and key

1. Open the Function App.
2. Overview → **Functions** → click **create_shared_item** (it should appear once deployment is complete; refresh if it doesn't).
3. Click **Get Function URL** (top of the page) → copy the URL with the `?code=...` key appended.

### E2. Smoke test

Use any HTTP tool. Below are two options that don't require installing anything.

**Option A — Postman web app** ([postman.com](https://www.postman.com))

- Method: `POST`
- URL: paste the function URL from E1
- Headers: `Content-Type: application/json`
- Body (raw → JSON):
  ```json
  {
    "title": "Smoke test credential",
    "username": "test.user@example.com",
    "password": "Correct-Horse-Battery-Staple-42",
    "website": "https://example.com",
    "expireAfter": "ONE_DAY",
    "oneTimeOnly": false
  }
  ```
  `website`, `expireAfter`, and `oneTimeOnly` are optional. You can also pass `recipients` (a list of email strings) when your 1Password account policy allows recipient-restricted links; omit it for “anyone with the link” shares.

**Option B — Azure Portal's built-in test pane**

1. In the Function App, open your function.
2. Click **Code + Test** in the left blade.
3. Click **Test/Run** at the top.
4. Paste the JSON above into the **Body** field. Click **Run**.

### E3. What to expect

On success (HTTP 200):

```json
{
  "itemId": "xyz123abc456",
  "vaultId": "abcd1234efgh5678ijklmnop",
  "shareLink": "https://share.1password.com/s#...",
  "expireAfter": "ONE_DAY",
  "oneTimeOnly": false
}
```

Verify:

- The item appears in the `Automated Shares` vault in the 1Password app.
- Opening the share link in a private browser window loads a 1Password share page with the credential.

### E4. When things go wrong

- `**ModuleNotFoundError: No module named 'onepassword'**` → `requirements.txt` didn't run during deploy. On Flex Consumption this almost always means `remote-build: true` is missing from the GitHub Actions workflow. Fix: see Part D, step D3. Verify with the Kudu `api/vfs/...` URL in step D4.
- `**Error: msg='data did not match any variant of untagged enum Invocation at line 1 column N'**` → the SDK received a shape it could not deserialize (often when extending `ItemCreateParams` or share APIs with the wrong types). The Rust core surfaces an opaque enum-mismatch error instead of a clear field message. Fix: match the SDK’s typed models and required fields (for example, if you add `websites`, use the SDK’s `Website` type and include fields such as `autofill_behavior` rather than ad hoc dicts).
- **401 from 1Password** → service account token is wrong or lacks permissions. Check B6 access and A2 permissions (Share permission must be explicitly added).
- **Key Vault reference resolution failed** (red X in B7) → managed identity role assignment hasn't propagated, or the Key Vault Secret URI is malformed. Re-check B6 and re-paste the URI in B7.
- **Function not visible after deploy** → restart the Function App from its **Overview** page, then refresh **Functions**.
- **Application Insights** (left blade → **Monitoring** → **Logs**) is the single best debugging tool. Every `logging.info` / `logging.exception` call in the code lands there.

---

## 8. Part F — Wire Jira to the function

Since the function already accepts a POST webhook, the remaining work is just on the Jira side.

1. In Jira, go to **Settings** (gear icon) → **System** → **WebHooks** (or, for Jira Automation, create an automation rule with a **Send web request** action).
2. Point the webhook at the function URL from E1 (including the `?code=...` key).
3. Map the issue fields to the JSON body shown in E2. Jira Automation lets you template the body with smart values like `{{issue.fields.summary}}`.
4. Optional but recommended: generate a second function key for Jira specifically (Function App → your function → **Function Keys** → **New function key**), so you can revoke it independently.

The email-delivery piece (sending the share link to the requester) is a separate concern — once the function returns the share link in the response, Jira Automation can pipe that into an **Send email** action, or you can route the response to a Logic App.

---

## 9. Security & hardening checklist

Before production, confirm:

- Service account has access only to the vaults it needs, at the minimum permission level.
- `Automated Shares` vault has no human members — only the service account.
- Function key is treated as a secret (store it in Jira's secret manager, not in plain-text automation config).
- Key Vault has **purge protection** and **soft delete** on (defaults are fine, but verify on the Key Vault **Properties** blade).
- Application Insights has a log retention policy that complies with your data policy (default is 90 days).
- Consider locking down the Function App with IP restrictions if Jira Cloud egress IPs are available, or with Private Endpoints if you're on an isolated SKU later.
- Rotate the 1Password service account token on a schedule; Azure Key Vault makes version rotation painless (upload new version, the Key Vault reference automatically picks up the latest).

---

## 10. Appendix — PowerShell + container alternative (sketch)

If you later want to switch to PowerShell, the path looks like this:

1. Build a Docker image based on `mcr.microsoft.com/azure-functions/powershell:4` that installs the `op` CLI via a RUN step pulling the binary from `https://cache.agilebits.com/dist/1P/op2/pkg/...`.
2. Push the image to Azure Container Registry (create one via **Create a resource** → **Container Registry**).
3. Create a Function App on the **Container Apps** hosting plan and point it at the image.
4. Write `run.ps1` that uses `op item create` and `op item share` with the service account token.

This is the heavier operational path — the Python SDK route above avoids it. Treat this as the fallback only if a hard constraint forces PowerShell.

---

## 11. Summary of what this delivers

| Typical integration requirement                                  | Addressed by                                      |
| ---------------------------------------------------------------- | ------------------------------------------------- |
| Serverless, not VM-hosted                                        | Azure Function App, Flex Consumption plan         |
| Item creation                                                    | `client.items.create(...)`                        |
| Share link generation (Connect Server can't do this)             | `client.items.shares.create(...)`                 |
| Dedicated vault owned only by service account                    | Part A1 + A2                                      |
| Webhook-triggered (from Jira)                                    | HTTP-triggered function, Part F                   |
| No container build required                                      | Python SDK via `requirements.txt`                 |
| Deployable through Azure UI                                      | Deployment Center → GitHub Actions                |
| Managed-identity auth for the token                              | Key Vault + system-assigned identity, Parts B5–B7 |
| Return-the-share-link contract so Jira/logic apps can forward it | JSON response body in E3                          |

Total clicks to stand it up from scratch, once the code is in a repo: roughly 40. Total time, including the first deploy: under an hour.
