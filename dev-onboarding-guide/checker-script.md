### About the [SSH Setup Checker Script](ssh-checker.sh)

**What it does:**

This script is a small diagnostic tool designed to help you quickly verify if your local macOS environment is correctly configured to use 1Password as your SSH agent. It performs several checks:

1. **`SSH_AUTH_SOCK` variable:** Verifies that the `SSH_AUTH_SOCK` environment variable is set and appears to point to the 1Password agent.
2. **Agent accessibility & key listing:** Attempts to connect to the SSH agent (via `ssh-add -L`) to list loaded SSH keys, looking for indicators that they are managed by 1Password.
3. **GitHub connection test (optional):** Offers to run a test SSH connection to `git@github.com`. This doesn't check your GitHub permissions but allows you to observe if 1Password prompts for authentication as expected.

**Why you might want to use it:**

- **Troubleshooting:** If you're having trouble connecting to SSH servers after [setting up 1Password for SSH](ssh-guide.md), this script can help pinpoint common configuration issues.
- **Verification:** After following the setup guide, run this script to confirm everything is working as expected.
- **Self-service check:** Quickly perform a self-service diagnostic before reaching out for support.
- **Peace of mind:** Make sure your SSH operations are indeed being securely handled by 1Password.
