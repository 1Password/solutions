# Scripted Provisioning with the 1Password CLI Tool

## Overview

This script leverages the 1Password Command Line Interface (CLI) v2 to process a list of names and email addresses from a CSV file, allowing you to invite, suspend, reactivate, or delete users based on your selection.

Additionally, you can opt to manually enter user details instead of using a CSV file or export a CSV list of existing users, which can then be used for the aforementioned actions. The script specifically looks for `Name` and `Email` headers in the CSV and ignores other columns.

## Account Configuration

To enable provisioning through the CLI, configure your 1Password account by navigating to <https://start.1password.com/settings/provisioning/cli>. This creates a "Provisioning Manager" group with the `Provision People` permission, allowing group members to invite users via the 1Password CLI. Add the dedicated provisioning account to this group, and include additional accounts as needed.

## Setup

Your input file must be a CSV with the following requirements:
- It must include a header row.

Example CSV format:
```
Name,Email
FirstName LastName,email@example.com
OtherName MoreName,another_email@example.com
```

### Additional Notes
- Names can include multiple components (e.g., `Wendy van der Appleseed` is valid).
- Non-Latin characters (e.g., Simplified Chinese) are supported but have not been thoroughly tested; results may vary.