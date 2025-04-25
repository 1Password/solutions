## Identify Abentees

The [identify-absentees.ps1](identify-absentees.ps1) & [identify-absentees.py](identify-absentees.py) scripts will prompt you for a number of days (N) after which you consider a user to not be adequately engaged (or "absent") from 1Password. It will then create a list of users who have not authenticated into 1Password for N days or longer. You can use this list to reach out to disengaged users or as input for other scripts to perform bulk actions on those users.

This script also provides some suggestions for modifying it's output depending on your needs.
