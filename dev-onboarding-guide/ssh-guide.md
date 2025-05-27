# Team SSH Key Onboarding Guide (Using 1Password)

## 1. Introduction

This guide offers a suggested standard process for using 1Password to manage your team's SSH keys securely and efficiently. By using 1Password for your SSH keys, you benefit from:

- **Enhanced Security:** Private keys are encrypted in your 1Password vault and only loaded into the SSH agent when needed, often protected by biometrics or Windows Hello.
- **Improved Convenience:** No more repeatedly typing passphrases for SSH operations.
- **Centralized Management:** Manage all your SSH keys alongside your other passwords and sensitive information in 1Password.
- **Easy Setup & Consistency:** Establishes a consistent and secure SSH key management practice across the team.

## 2. Prerequisites

- **1Password Account:** A 1Password Business, Teams, or individual account (if team members manage their own).
- **1Password Desktop Application:** Installed on macOS, Windows, or Linux.
  - [1Password Downloads Page](https://1password.com/downloads/)
- **(Recommended) 1Password Browser Extension:** Installed.
- **(Optional, for checker script & advanced use) 1Password CLI (`op`):** Installed.
  - [Install the 1Password CLI](https://developer.1password.com/docs/cli/get-started/)

## 3. Setup Instructions

### 3.1. Enable the 1Password SSH Agent

You need to enable the SSH agent in the 1Password desktop app.

1. **Open the 1Password desktop application.**
2. **Navigate to Preferences/Settings:**
   - **macOS:** `1Password` menu > `Settings` (or `Preferences`) > `Developer` tab.
   - **Windows:** `⋮` (menu button) > `Settings` > `Developer` tab.
   - **Linux:** `Menu` > `Settings` (or `Ctrl+,`) > `Developer` tab.
3. **Find the "SSH Agent" section.**
4. **Check the box for "Use the SSH agent"** (or "Turn on SSH agent").
5. **(Recommended)** Enable the option "Authorize SSH key use with biometrics or system password."
6. **Set a default SSH key (optional):** If you have a key you use frequently, you can set it as the default.
7. **Close the settings.** You might see on-screen instructions about how 1Password configures the SSH agent socket (`SSH_AUTH_SOCK`). Usually, restarting your terminal session will set this up automatically.

### 3.2. Generate or Import SSH Keys

#### Generate a New SSH Key in 1Password (Recommended)

1. In the 1Password desktop app, select the vault where you want to save the key.
2. Click the "+ New Item" button and select "SSH Key."
3. Choose "Generate a new private key."
4. Select the key type (Ed25519 is recommended, or RSA) and bit length (4096 recommended for RSA).
5. Give your key a clear title (e.g., `GitHub - [Your Name]`, `AWS Production - [Your Name]`).
6. Click "Save." The public key will be visible within the item.

#### Import an Existing SSH Key into 1Password

If you must continue using an existing key, you can import it.

1. In the 1Password desktop app, click the "+ New Item" button and select "SSH Key."
2. Choose "Import an existing key."
3. Drag and drop your private key file (e.g., `id_rsa`) or select the file.
4. Give your key a clear title.
5. **Important:** After importing, **securely delete the original private key file** (e.g., `~/.ssh/id_rsa`) from your disk.

### 3.3. Add Your Public Key to Services

Once you've generated or imported an SSH key, you need to add its public key to the services you'll be connecting to (GitHub, GitLab, AWS, internal servers, etc.).

1. Open the SSH key item in 1Password.
2. Click the "Copy" icon next to the public key field to copy the public key.
3. Navigate to the SSH key settings page on each service and paste the copied public key.
   - **GitHub:** `Settings` > `SSH and GPG keys` > `New SSH key`
   - **GitLab:** `Preferences` > `SSH Keys`
   - For servers, add it to the `~/.ssh/authorized_keys` file on the server.

### 3.4. Verify SSH Client Configuration

Once the 1Password SSH agent is enabled, it should typically be used by your system's SSH client automatically. This happens because the `SSH_AUTH_SOCK` environment variable is set to point to the 1Password agent's socket file.

- **Restart Your Terminal Session:** After enabling the SSH agent or making changes to shell configuration files like `~/.zshrc`, `~/.bashrc`, or `~/.config/fish/config.fish`, restart your terminal session or open a new tab/window.
- **Verification:** You can check if `SSH_AUTH_SOCK` points to a 1Password-related path by running the following in your terminal:

  ```bash
  echo $SSH_AUTH_SOCK
  ```

  The output should contain "1Password" (e.g., `/Users/youruser/Library/Group Containers/XXXXXXXXXX.com.1password/t/agent.sock`).

- **`~/.ssh/config` file (If Needed):**
  While usually not required, if you need specific configurations or have conflicts with other SSH agents, you can explicitly point to the 1Password agent in your `~/.ssh/config` file (adjust the path to your actual `SSH_AUTH_SOCK` value):

  ```bash
  Host *
      IdentityAgent "~/Library/Group Containers/2BUA8C4S2C.com.1password/t/agent.sock"
  ```

  **Note:** The path for `IdentityAgent` can vary by OS and 1Password version. Check the 1Password app's settings for the correct path if you need to specify it manually.

## 4. Using Biometrics or System Password

With the 1Password SSH agent correctly set up, when you use an `ssh` command (e.g., `git pull`, `ssh user@server`), 1Password should prompt you for biometric authentication (fingerprint, face) or your system password. This allows secure and quick authentication instead of typing key passphrases.

## 5. Best Practices

- **Descriptive Key Names:** Name your SSH keys in 1Password clearly, indicating the service/machine and owner (e.g., `GitLab - MyProject - MacBookPro`, `AWS Staging Server Access`).
- **Key Separation (Recommended):** If feasible, consider using different SSH keys for different critical services or environments.
- **Regular Review:** Periodically review the public keys registered on your connected services (GitHub, etc.) and remove any that are no longer needed.
- **Avoid Exporting Private Keys:** Only export private keys from 1Password if absolutely necessary and for a specific, secure purpose.

## 6. Troubleshooting

- **"Agent not running or not detected":**
  - Ensure the SSH agent is enabled in the 1Password desktop app settings.
  - Try restarting your terminal session.
  - Run `echo $SSH_AUTH_SOCK` to see if the expected path is displayed.
- **"Still being prompted for the passphrase of an old key file":**
  - Check if old private key files (e.g., `~/.ssh/id_rsa`) still exist on your disk. If so, delete them securely.
  - Check your `~/.ssh/config` file for any settings that explicitly point to an old key (`IdentityFile ~/.ssh/id_rsa`).
- **"Key not recognized by the server (Permission denied (publickey))":**
  - Verify that the correct public key has been added to the server's `~/.ssh/authorized_keys` file or the service's SSH key settings.
  - Confirm the 1Password SSH agent is serving the correct key (you can check with `ssh-add -L`; your 1Password key should be listed).
  - Check the SSH daemon logs on the server (e.g., `/var/log/auth.log` or `/var/log/secure`) for more detailed error messages.

---

### About the [SSH Setup Checker Script](/ssh-checker.sh)

**What it does:**

This script is a small diagnostic tool designed to help you quickly verify if your local environment is correctly configured to use 1Password as your SSH agent. It performs several checks:

1. **`SSH_AUTH_SOCK` Variable:** Verifies that the `SSH_AUTH_SOCK` environment variable is set and appears to point to the 1Password agent.
2. **Agent Accessibility & Key Listing:** Attempts to connect to the SSH agent (via `ssh-add -L`) to list loaded SSH keys, looking for indicators that they are managed by 1Password.
3. **GitHub Connection Test (Optional):** Offers to run a test SSH connection to `git@github.com`. This doesn't check your GitHub permissions but allows you to observe if 1Password prompts for authentication (e.g., biometrics) as expected.

**Why you might want to use it:**

- **Troubleshooting:** If you're having trouble connecting to SSH servers after setting up 1Password for SSH, this script can help pinpoint common configuration issues.
- **Verification:** After following the setup guide, run this script to confirm everything is working as expected.
- **Self-Service Check:** Quickly perform a self-service diagnostic before reaching out for support.
- **Peace of Mind:** Ensure your SSH operations are indeed being securely handled by 1Password.
