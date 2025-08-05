# Administrators: Get started with 1Password for SSH & Git

This guide will help you get your team started using the [1Password SSH Agent](https://developer.1password.com/docs/ssh) to manage their SSH keys and sign Git commits. By using 1Password for SSH, your team benefits from:

- **Enhanced security:** Private keys are encrypted in your 1Password vault and only loaded into the SSH agent when needed, optionally protected by biometrics or Windows Hello.
- **Streamlined authentication:** No more repeatedly typing passphrases for SSH operations.
- **Automatic setup:** Automatically generate SSH keys and configure Git commit signing from the 1Password app.
- **Centralized Management:** Manage all your SSH keys alongside your other passwords and sensitive information in 1Password.
- **Consistency:** Establish a consistent and secure SSH key management practice across the team.

## Prerequisites

To use 1Password for SSH & Git, your team members will need:

- A [1Password subscription](https://start.1password.com/sign-up/plan)
- The [1Password desktop application](https://1password.com/downloads/)
- The [1Password browser extension](https://1password.com/downloads/browser-extension)
- [1Password CLI](https://developer.1password.com/docs/cli/get-started/) (optional, to use the SSH setup validation script)

## Step 1: Make sure developer tools are enabled for your team

First, make sure your [team policies](https://support.1password.com/team-policies/) are set up for developer tools.

First, turn on the policy to allow 1Password to automatically create SSH configuration files. This enables your team to easily connect to hosts using SSH keys stored in 1Password.

1. Sign in to your account on 1Password.com
2. Select **Policies** in the sidebar
3. Select **Manage** under "Sharing and permissions".
4. Under Developer Permissions, make sure "Allow automatic creation of SSH configuration file" is toggled on.

Then, under Sidebar Navigation, make sure **Developer Tools** is toggled off. If the setting is toggled on, your team **will not** see the SSH agent in their app.

## Step 2: Review best practices

You can help your team use SSH best practices by sharing the following principles wiht them:

- **Descriptive key names:** Name your SSH keys in 1Password clearly, indicating the service/machine and owner (e.g., `GitLab - MyProject - MacBookPro`, `AWS Staging Server Access`).
- **Key separation (recommended):** If feasible, consider using different SSH keys for different critical services or environments.
- **Regular review:** Periodically review the public keys registered on your connected services (GitHub, etc.) and remove any that are no longer needed.
- **Avoid exporting private keys:** Only export private keys from 1Password if absolutely necessary and for a specific, secure purpose.
- **Use system authentication:** Make sure your team members have [Touch ID](https://support.1password.com/touch-id-mac/), [Windows Hello](https://support.1password.com/windows-hello/), or [system authentication](https://support.1password.com/system-authentication-linux/) turned on in the 1Password app. With system authentication turned on, when you use an `ssh` command (e.g., `git pull`, `ssh user@server`), 1Password prompts you for biometric authentication (fingerprint, face) or your system password. This allows secure and quick authentication instead of typing key passphrases.

## Step 3: Help your team get started

When you're ready to onboard your team to 1Password for SSH & Git, have your team members follow the steps in the following articles:

1. [Get started with 1Password for SSH](https://developer.1password.com/docs/ssh/get-started)
3. [Sign Git commits with SSH](https://developer.1password.com/docs/ssh/git-commit-signing)

### Step 4: Verify SSH Client Configuration

If your team uses Mac or Linux devices, you can use the SSH Setup Checker script to verify their local environment is correctly configured.

After the 1Password SSH agent is set up, it should typically be used by the system's SSH client automatically. This happens because the `SSH_AUTH_SOCK` environment variable is set to point to the 1Password agent's socket file.

To verify that their SSH setup is correct after enabling the SSH agent or making changes to shell configuration files, your team members can:

1. Open a terminal session, or restart an existing terminal session in a new tab or window.
2. Check if `SSH_AUTH_SOCK` points to a 1Password-related path by running the following command:

  ```bash
  echo $SSH_AUTH_SOCK
  ```

  The output should contain "1Password" (for example, `/Users/youruser/Library/Group Containers/XXXXXXXXXX.com.1password/t/agent.sock`).

- If you need specific configurations or have conflicts with other SSH agents, you can explicitly point to the 1Password agent in your `~/.ssh/config` file by adjusting the path to your actual `SSH_AUTH_SOCK` value:

  ```bash
  Host *
      IdentityAgent "~/Library/Group Containers/2BUA8C4S2C.com.1password/t/agent.sock"
  ```

## Troubleshooting

- **"Agent not running or not detected":**
  - Make sure the SSH agent is enabled in the 1Password desktop app settings.
  - Try restarting your terminal session.
  - Run `echo $SSH_AUTH_SOCK` to see if the expected path is displayed.
- **"Still being prompted for the passphrase of an old key file":**
  - Check if old private key files (e.g., `~/.ssh/id_rsa`) still exist on your disk. If so, delete them securely.
  - Check your `~/.ssh/config` file for any settings that explicitly point to an old key (`IdentityFile ~/.ssh/id_rsa`).
- **"Key not recognized by the server (Permission denied (publickey))":**
  - Verify that the correct public key has been added to the server's `~/.ssh/authorized_keys` file or the service's SSH key settings.
  - Confirm the 1Password SSH agent is serving the correct key (you can check with `ssh-add -L`; your 1Password key should be listed).
  - Check the SSH daemon logs on the server (e.g., `/var/log/auth.log` or `/var/log/secure`) for more detailed error messages.

