#!/bin/bash

echo "1Password SSH Setup Checker"
echo "------------------------------------"

# Color definitions (optional)
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Helper function: display check status
print_status() {
    if [ "$2" = "OK" ]; then
        echo -e "[${GREEN}OK${NC}] $1"
    elif [ "$2" = "FAIL" ]; then
        echo -e "[${RED}FAIL${NC}] $1"
    elif [ "$2" = "WARN" ]; then
        echo -e "[${YELLOW}WARN${NC}] $1"
    else
        echo -e "[INFO] $1"
    fi
}

# 1. Check SSH_AUTH_SOCK environment variable
echo
print_status "Checking SSH_AUTH_SOCK environment variable..."
if [ -n "$SSH_AUTH_SOCK" ]; then
    print_status "SSH_AUTH_SOCK is set: $SSH_AUTH_SOCK" "OK"
    if [[ "$SSH_AUTH_SOCK" == *1Password* || "$SSH_AUTH_SOCK" == *1password* ]]; then
        print_status "SSH_AUTH_SOCK appears to point to a 1Password agent." "OK"
    else
        print_status "SSH_AUTH_SOCK may not point to a 1Password agent." "WARN"
        echo "   Current value: $SSH_AUTH_SOCK"
        echo "   Please ensure the SSH agent is enabled in 1Password desktop settings,"
        echo "   restart your terminal, or check your shell configuration file (~/.zshrc, ~/.bash_profile, etc.)."
    fi
else
    print_status "SSH_AUTH_SOCK is not set." "FAIL"
    echo "   Please ensure the SSH agent is enabled in 1Password desktop settings,"
    echo "   restart your terminal, or check your shell configuration file."
fi

# 2. Check if keys are loaded in the SSH agent (ssh-add -L)
echo
print_status "Checking for keys loaded in the SSH agent (ssh-add -L)..."
# ssh-add -L can return an error code if the agent isn't running, so capture output
agent_keys_output=$(ssh-add -L 2>&1)
agent_keys_exit_code=$?

if [ $agent_keys_exit_code -eq 0 ]; then
    if [[ "$agent_keys_output" == *"1Password"* || "$agent_keys_output" == *"1password"* || "$agent_keys_output" == *"//"* ]]; then # Common 1P key comment format
        print_status "1Password managed keys were listed from the SSH agent." "OK"
        echo "   Listed keys:"
        echo -e "   ${agent_keys_output}"
    elif [[ "$agent_keys_output" == "The agent has no identities." ]]; then
        print_status "No keys are loaded in the SSH agent." "WARN"
        echo "   Ensure you have generated/imported SSH keys in 1Password and they are configured for use with the agent."
        echo "   Alternatively, if your 1Password app is locked, try unlocking it."
    else
        print_status "Keys were listed from the SSH agent, but it's unclear if they are from 1Password." "WARN"
        echo "   Listed keys:"
        echo -e "   ${agent_keys_output}"
        echo "   Please verify these are the keys you manage with 1Password."
    fi
elif [ $agent_keys_exit_code -eq 2 ]; then # Error code for "Could not open a connection to your authentication agent."
    print_status "Could not connect to SSH agent. Is it running? (ssh-add -L returned error)" "FAIL"
    echo "   Check your SSH_AUTH_SOCK setting and the status of the 1Password SSH agent."
else # Other errors
    print_status "Error running ssh-add -L (Code: $agent_keys_exit_code)." "FAIL"
    echo "   Error output: $agent_keys_output"
fi

# 3. Test SSH connection to GitHub (optional)
echo
print_status "Testing SSH connection to GitHub (ssh -T git@github.com)..."
echo "   This test will attempt to authenticate to GitHub."
echo "   Observe if 1Password prompts for biometrics or your system password."
echo "   A successful message often looks like 'Hi username! You've successfully authenticated...'"
echo "   (Do you want to run this test? [y/N])"
read -r run_github_test

if [[ "$run_github_test" =~ ^[Yy]$ ]]; then
    echo "   Running: ssh -T git@github.com ..."
    ssh -T git@github.com
    echo "   Test complete. Check the output above and any 1Password prompts."
else
    print_status "GitHub connection test was skipped."
fi

echo
echo "------------------------------------"
echo "Check complete. If you encounter any issues, please refer to the onboarding guide"
echo "or consult your team lead."
