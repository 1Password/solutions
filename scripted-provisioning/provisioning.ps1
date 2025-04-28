# Define some colors to make the console output look nice
$CYAN = "`e[96m"
$YELLOW = "`e[93m"
$RED = "`e[91m"
$GREEN = "`e[92m"
$RESET = "`e[0m"
$BLINK = "`e[5m"

# Takes a string and wraps it into lines that fit within a certain width - useful for table formatting
function Wrap-Text {
    param (
        [string]$Text,
        [int]$MaxWidth
    )

    if (-not $Text) { return @("") }

    $lines = [System.Collections.ArrayList]::new()
    $currentLine = ""
    $words = $Text -split "\s+"

    foreach ($word in $words) {
        if ($word.Length -gt $MaxWidth) {
            while ($word.Length -gt $MaxWidth) {
                if ($currentLine) { $null = $lines.Add($currentLine); $currentLine = "" }
                $null = $lines.Add($word.Substring(0, $MaxWidth))
                $word = $word.Substring($MaxWidth)
            }
            if ($word) { $currentLine = if ($currentLine) { "$currentLine $word" } else { $word } }
        }
        else {
            $potentialLine = if ($currentLine) { "$currentLine $word" } else { $word }
            if ($potentialLine.Length -le $MaxWidth) { $currentLine = $potentialLine }
            else {
                if ($currentLine) { $null = $lines.Add($currentLine) }
                $currentLine = $word
            }
        }
    }

    if ($currentLine) { $null = $lines.Add($currentLine) }
    if (-not $lines) { $lines = @("") }
    return $lines
}

# Renders a table with results (Name, Email, Status, Message) in a clean, boxed format
function Show-Table {
    param (
        [System.Collections.Generic.List[PSObject]]$Data,
        [int]$MaxMessageLength = 30
    )

    if (-not $Data -or $Data.Count -eq 0) {
        Write-Host "`n$YELLOW😕 No data to display.$RESET"
        return
    }

    # Define the table headers and figure out the max width for each column
    $headers = @("Name", "Email", "Status", "Message")
    $maxLengths = @{ Name = $headers[0].Length; Email = $headers[1].Length; Status = $headers[2].Length; Message = $headers[3].Length }
    $maxLines = [System.Collections.Generic.List[int]]::new()
    $wrappedData = [System.Collections.Generic.List[PSObject]]::new()

    # Go through each item, wrap long messages, and calculate the column widths
    foreach ($item in $Data) {
        $name = if ($item.Name) { $item.Name.ToString() } else { "" }
        $email = if ($item.Email) { $item.Email.ToString() } else { "" }
        $status = if ($item.Status) { $item.Status.ToString() } else { "" }
        $message = if ($item.Message) { [string]$item.Message } else { "" }

        $wrappedMessage = Wrap-Text -Text $message -MaxWidth $MaxMessageLength
        $messageLines = $wrappedMessage.Count

        $maxLengths.Name = [math]::Max($maxLengths.Name, $name.Length)
        $maxLengths.Email = [math]::Max($maxLengths.Email, $email.Length)
        $maxLengths.Status = [math]::Max($maxLengths.Status, $status.Length)
        $maxLengths.Message = [math]::Max($maxLengths.Message, ($wrappedMessage | Measure-Object -Property Length -Maximum).Maximum)

        $maxLines.Add([math]::Max(1, $messageLines))
        $wrappedData.Add([PSCustomObject]@{
            Name = $name
            Email = $email
            Status = $status
            Message = $wrappedMessage
        })
    }

    # Add a bit of padding to the columns and cap their width so they don’t get too wide
    $keys = $maxLengths.Keys | ForEach-Object { $_ }
    foreach ($key in $keys) {
        $maxLengths[$key] = [math]::Max($maxLengths[$key] + 4, 15)
        $maxLengths[$key] = [math]::Min($maxLengths[$key], 40)
    }

    # Create the table borders using Unicode characters for a boxed look
    $topBorder = "┌" + ("─" * $maxLengths.Name) + "┬" + ("─" * $maxLengths.Email) + "┬" + ("─" * $maxLengths.Status) + "┬" + ("─" * $maxLengths.Message) + "┐"
    $midBorder = "├" + ("─" * $maxLengths.Name) + "┼" + ("─" * $maxLengths.Email) + "┼" + ("─" * $maxLengths.Status) + "┼" + ("─" * $maxLengths.Message) + "┤"
    $rowBorder = "├" + ("─" * $maxLengths.Name) + "┼" + ("─" * $maxLengths.Email) + "┼" + ("─" * $maxLengths.Status) + "┼" + ("─" * $maxLengths.Message) + "┤"
    $bottomBorder = "└" + ("─" * $maxLengths.Name) + "┴" + ("─" * $maxLengths.Email) + "┴" + ("─" * $maxLengths.Status) + "┴" + ("─" * $maxLengths.Message) + "┘"
    $headerRow = "│ " + $headers[0].PadRight($maxLengths.Name - 2) + " │ " + $headers[1].PadRight($maxLengths.Email - 2) + " │ " + $headers[2].PadRight($maxLengths.Status - 2) + " │ " + $headers[3].PadRight($maxLengths.Message - 2) + " │"

    # Output the table to the console
    Write-Host "`n$CYAN$topBorder$RESET"
    Write-Host "$CYAN$headerRow$RESET"
    Write-Host "$CYAN$midBorder$RESET"

    for ($i = 0; $i -lt $wrappedData.Count; $i++) {
        $item = $wrappedData[$i]
        $rowLines = $maxLines[$i]
        # Make sure $item.Message is an array of strings to avoid any weird indexing issues
        $item.Message = @($item.Message | ForEach-Object { [string]$_ })

        for ($j = 0; $j -lt $rowLines; $j++) {
            $nameText = if ($j -eq 0) { $item.Name } else { "" }
            $emailText = if ($j -eq 0) { $item.Email } else { "" }
            $statusText = if ($j -eq 0) { $item.Status } else { "" }
            $messageText = if ($j -lt $item.Message.Count) { [string]$item.Message[$j] } else { "" }

            $nameText = [string]$nameText
            $emailText = [string]$emailText
            $statusText = [string]$statusText
            $messageText = [string]$messageText

            $row = "│ " + $nameText.PadRight($maxLengths.Name - 2) + " │ " + $emailText.PadRight($maxLengths.Email - 2) + " │ " + $statusText.PadRight($maxLengths.Status - 2) + " │ " + $messageText.PadRight($maxLengths.Message - 2) + " │"
            Write-Host $row
        }

        if ($i -lt ($wrappedData.Count - 1)) {
            Write-Host "$CYAN$rowBorder$RESET"
        }
    }

    Write-Host "$CYAN$bottomBorder$RESET"
    
    # Clean up memory
    [System.GC]::Collect()
}

# Shows a simpler table of users or emails for confirmation before proceeding with an action
function Show-EmailList {
    param (
        [string[]]$Emails,
        [string]$Action,
        [string[]]$Names = @()  # Optional: Names for CSV confirmation
    )

    if (-not $Emails -or $Emails.Count -eq 0) {
        Write-Host "`n$YELLOW😕 No users/emails to display.$RESET"
        return
    }

    # Set up headers based on whether we have names (two columns) or just emails (one column)
    $headerText = if ($Names) { "Users to $Action" } else { "Emails to $Action" }
    $headers = if ($Names) { @("Name", "UUID/Email") } else { @($headerText) }
    $maxLengths = if ($Names) { @{ Name = $headers[0].Length; Identifier = $headers[1].Length } } else { @{ Email = $headers[0].Length } }
    $maxLines = [System.Collections.Generic.List[int]]::new()
    $wrappedData = [System.Collections.Generic.List[PSObject]]::new()

    # Calculate the max width needed for each column
    if ($Names) {
        for ($i = 0; $i -lt $Emails.Count; $i++) {
            $name = if ($Names[$i]) { $Names[$i] } else { "" }
            $maxLengths.Name = [math]::Max($maxLengths.Name, $name.Length)
            $maxLengths.Identifier = [math]::Max($maxLengths.Identifier, $Emails[$i].Length)
            $maxLines.Add(1)
            $wrappedData.Add([PSCustomObject]@{ Name = $name; Identifier = $Emails[$i] })
        }

        $maxLengths.Name = [math]::Max($maxLengths.Name + 4, 15)
        $maxLengths.Identifier = [math]::Max($maxLengths.Identifier + 4, 15)

        # Build the table borders for a two-column layout
        $topBorder = "┌" + ("─" * $maxLengths.Name) + "┬" + ("─" * $maxLengths.Identifier) + "┐"
        $midBorder = "├" + ("─" * $maxLengths.Name) + "┼" + ("─" * $maxLengths.Identifier) + "┤"
        $rowBorder = "├" + ("─" * $maxLengths.Name) + "┼" + ("─" * $maxLengths.Identifier) + "┤"
        $bottomBorder = "└" + ("─" * $maxLengths.Name) + "┴" + ("─" * $maxLengths.Identifier) + "┘"
        $headerRow = "│ " + $headers[0].PadRight($maxLengths.Name - 2) + " │ " + $headers[1].PadRight($maxLengths.Identifier - 2) + " │"

        # Output the table
        Write-Host "`n$YELLOW$topBorder$RESET"
        Write-Host "$YELLOW$headerRow$RESET"
        Write-Host "$YELLOW$midBorder$RESET"

        for ($i = 0; $i -lt $wrappedData.Count; $i++) {
            $row = "│ " + $wrappedData[$i].Name.PadRight($maxLengths.Name - 2) + " │ " + $wrappedData[$i].Identifier.PadRight($maxLengths.Identifier - 2) + " │"
            Write-Host "$YELLOW$row$RESET"
            if ($i -lt ($wrappedData.Count - 1)) {
                Write-Host "$YELLOW$rowBorder$RESET"
            }
        }

        Write-Host "$YELLOW$bottomBorder$RESET"
    }
    else {
        # Single-column table for manual input, just showing emails
        foreach ($email in $Emails) {
            $maxLengths.Email = [math]::Max($maxLengths.Email, $email.Length)
            $maxLines.Add(1)
            $wrappedData.Add([PSCustomObject]@{ Email = $email })
        }

        $maxLengths.Email = [math]::Max($maxLengths.Email + 4, 15)
        $topBorder = "┌" + ("─" * $maxLengths.Email) + "┐"
        $midBorder = "├" + ("─" * $maxLengths.Email) + "┤"
        $rowBorder = "├" + ("─" * $maxLengths.Email) + "┤"
        $bottomBorder = "└" + ("─" * $maxLengths.Email) + "┘"
        $headerRow = "│ " + [string]$headerText.PadRight($maxLengths.Email - 2) + " │"

        Write-Host "`n$YELLOW$topBorder$RESET"
        Write-Host "$YELLOW$headerRow$RESET"
        Write-Host "$YELLOW$midBorder$RESET"

        for ($i = 0; $i -lt $wrappedData.Count; $i++) {
            $row = "│ " + $wrappedData[$i].Email.PadRight($maxLengths.Email - 2) + " │"
            Write-Host "$YELLOW$row$RESET"
            if ($i -lt ($wrappedData.Count - 1)) {
                Write-Host "$YELLOW$rowBorder$RESET"
            }
        }

        Write-Host "$YELLOW$bottomBorder$RESET"
    }

    # Clean up memory
    [System.GC]::Collect()
}

# Displays a table of users (UUID, Name, Email, State) when listing users
function Show-UserList {
    param (
        [string]$Action
    )

    # Fetch the user list from the 1Password CLI
    $opResult = Invoke-OpCommand @("user", "list")
    if (-not $opResult[0]) {
        Write-Host "`n$RED😕 Failed to retrieve user list: $($opResult[1])$RESET"
        return $null
    }

    $userListRaw = $opResult[1]
    if (-not $userListRaw) {
        Write-Host "`n$YELLOW😕 No users found.$RESET"
        return $null
    }

    $userListLines = $userListRaw -split "\n" | Where-Object { $_ -match '\S' }
    if ($userListLines.Count -lt 2) {
        Write-Host "`n$YELLOW😕 No users found in the list.$RESET"
        return $null
    }

    # Parse each user entry and filter based on the action we're performing
    $userData = @()
    for ($i = 1; $i -lt $userListLines.Count; $i++) {
        $line = $userListLines[$i].Trim()
        if (-not $line) { continue }
        if ($line.Length -lt 26) { continue }

        $uuid = $line.Substring(0, 26).Trim()
        $remaining = $line.Substring(26).Trim()
        $stateMatch = [regex]::Match($remaining, '\s+(SUSPENDED|TRANSFER_SUSPENDED|ACTIVE|PENDING|RECOVERY_STARTED|TRANSFER_STARTED)\s+')
        if (-not $stateMatch.Success) { continue }

        $state = $stateMatch.Groups[1].Value
        $stateStart = $stateMatch.Index
        $stateLength = $stateMatch.Length
        $beforeState = $remaining.Substring(0, $stateStart).Trim()
        $afterState = $remaining.Substring($stateStart + $stateLength).Trim()
        $emailMatch = [regex]::Match($beforeState, '[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}')
        if (-not $emailMatch.Success) { continue }

        $email = $emailMatch.Value
        $emailStart = $emailMatch.Index
        $name = $beforeState.Substring(0, $emailStart).Trim()
        if (-not $name) { $name = "Unknown" }

        $includeUser = $false
        if ($Action -eq "suspend") {
            $includeUser = $state -in @("ACTIVE", "PENDING", "RECOVERY_STARTED", "TRANSFER_STARTED")
        }
        elseif ($Action -eq "reactivate") {
            $includeUser = $state -in @("SUSPENDED", "TRANSFER_SUSPENDED")
        }
        else {
            $includeUser = $true
        }

        if ($includeUser) {
            $userData += [PSCustomObject]@{
                UUID  = $uuid
                Name  = $name
                Email = $email
                State = $state
            }
        }
    }

    if (-not $userData) {
        Write-Host "`n$YELLOW😕 No users found matching the criteria for $Action.$RESET"
        return $null
    }

    # Set up the table for displaying the user list
    $headers = @("UUID", "Name", "Email", "State")
    $maxLengths = @{ UUID = $headers[0].Length; Name = $headers[1].Length; Email = $headers[2].Length; State = $headers[3].Length }
    $maxLines = [System.Collections.Generic.List[int]]::new()
    $wrappedData = [System.Collections.Generic.List[PSObject]]::new()

    foreach ($user in $userData) {
        $maxLengths.UUID = [math]::Max($maxLengths.UUID, $user.UUID.Length)
        $maxLengths.Name = [math]::Max($maxLengths.Name, $user.Name.Length)
        $maxLengths.Email = [math]::Max($maxLengths.Email, $user.Email.Length)
        $maxLengths.State = [math]::Max($maxLengths.State, $user.State.Length)
        $maxLines.Add(1)
        $wrappedData.Add([PSCustomObject]@{
            UUID  = $user.UUID
            Name  = $user.Name
            Email = $user.Email
            State = $user.State
        })
    }

    $keys = $maxLengths.Keys | ForEach-Object { $_ }
    foreach ($key in $keys) {
        $maxLengths[$key] = [math]::Max($maxLengths[$key] + 4, 15)
    }

    $topBorder = "┌" + ("─" * $maxLengths.UUID) + "┬" + ("─" * $maxLengths.Name) + "┬" + ("─" * $maxLengths.Email) + "┬" + ("─" * $maxLengths.State) + "┐"
    $midBorder = "├" + ("─" * $maxLengths.UUID) + "┼" + ("─" * $maxLengths.Name) + "┼" + ("─" * $maxLengths.Email) + "┼" + ("─" * $maxLengths.State) + "┤"
    $rowBorder = "├" + ("─" * $maxLengths.UUID) + "┼" + ("─" * $maxLengths.Name) + "┼" + ("─" * $maxLengths.Email) + "┼" + ("─" * $maxLengths.State) + "┤"
    $bottomBorder = "└" + ("─" * $maxLengths.UUID) + "┴" + ("─" * $maxLengths.Name) + "┴" + ("─" * $maxLengths.Email) + "┴" + ("─" * $maxLengths.State) + "┘"
    $headerRow = "│ " + $headers[0].PadRight($maxLengths.UUID - 2) + " │ " + $headers[1].PadRight($maxLengths.Name - 2) + " │ " + $headers[2].PadRight($maxLengths.Email - 2) + " │ " + $headers[3].PadRight($maxLengths.State - 2) + " │"

    Write-Host "`n$CYAN$topBorder$RESET"
    Write-Host "$CYAN$headerRow$RESET"
    Write-Host "$CYAN$midBorder$RESET"

    for ($i = 0; $i -lt $wrappedData.Count; $i++) {
        $uuidText = [string]$wrappedData[$i].UUID
        $nameText = [string]$wrappedData[$i].Name
        $emailText = [string]$wrappedData[$i].Email
        $stateText = [string]$wrappedData[$i].State
        $row = "│ " + $uuidText.PadRight($maxLengths.UUID - 2) + " │ " + $nameText.PadRight($maxLengths.Name - 2) + " │ " + $emailText.PadRight($maxLengths.Email - 2) + " │ " + $stateText.PadRight($maxLengths.State - 2) + " │"
        Write-Host $row
        if ($i -lt ($wrappedData.Count - 1)) {
            Write-Host "$CYAN$rowBorder$RESET"
        }
    }

    Write-Host "$CYAN$bottomBorder$RESET"
    [System.GC]::Collect()
    return $userData
}

# Executes commands via the 1Password CLI and processes the output
function Invoke-OpCommand {
    param (
        [string[]]$Arguments
    )

    $processInfo = [System.Diagnostics.ProcessStartInfo]::new()
    $processInfo.FileName = "op"
    $processInfo.Arguments = $Arguments -join " "
    $processInfo.RedirectStandardOutput = $true
    $processInfo.RedirectStandardError = $true
    $processInfo.UseShellExecute = $false
    $processInfo.CreateNoWindow = $true

    try {
        $process = [System.Diagnostics.Process]::Start($processInfo)
        $stdOut = $process.StandardOutput.ReadToEnd()
        $stdErr = $process.StandardError.ReadToEnd()
        $process.WaitForExit()
        $exitCode = $process.ExitCode

        if ($exitCode -ne 0 -or ($stdErr -and $stdErr -match "\[ERROR\]")) {
            return $false, $stdErr
        }

        $resultMessage = switch ($Arguments[1]) {
            "provision" { "Provisioned successfully" }
            "suspend" { "Suspended successfully" }
            "reactivate" { "Reactivated successfully" }
            "delete" { "Deleted successfully" }
            default { $stdOut }
        }
        return $true, $resultMessage
    }
    catch {
        $errorMessage = if ($_.Exception.Message) { $_.Exception.Message } else { "Unknown error" }
        switch -Wildcard ($errorMessage) {
            "*TRANSFER_PENDING*" {
                if ($Arguments[1] -eq "provision") { return $true, "Provisioned successfully (transfer in progress)" }
                return $false, "User transfer in progress"
            }
            "*TRANSFER_STARTED*" {
                if ($Arguments[1] -eq "provision") { return $true, "Provisioned successfully (transfer in progress)" }
                return $false, "User transfer in progress"
            }
            "*already a member*" { return $false, "User already exists" }
            "*not found*" { return $false, "User not found" }
            "*Resource Invalid*" { return $false, "Invalid domain" }
            "*expected at most 0 arguments*" { return $false, "Invalid command syntax" }
            default { return $false, $errorMessage }
        }
    }
    finally {
        if ($process) { $process.Dispose() }
       
        # Clean up memory
        [System.GC]::Collect()
    }
}

# Start the script with a friendly welcome message
Write-Host "`n$CYAN🚀 Welcome to the 1Password User Management Script! 🎉$RESET"
Write-Host "This script provisions, suspends, reactivates, or deletes users from a CSV file or manually."
Write-Host "CSV must have 'Name' and 'Email' columns (case-insensitive) if used.`n"

# Make sure the 1Password CLI is installed before proceeding
if (-not (Get-Command op -ErrorAction SilentlyContinue)) {
    Write-Host "$RED😕 Error: 1Password CLI (op) not found. Please install it.$RESET"
    Write-Host "Download from: https://developer.1password.com/docs/cli/get-started/`n"
    exit 1
}

# Check if we're authenticated with the 1Password CLI
$authCheck = Invoke-OpCommand @("user", "list")
if (-not $authCheck[0]) {
    # If we're not authenticated, prompt for the account shorthand to sign in
    Write-Host "$YELLOW🔐 Looks like we need to authenticate with 1Password CLI.$RESET"
    $accountShorthand = $null
    while (-not $accountShorthand) {
        Write-Host "Please enter your 1Password account shorthand (e.g., 'myaccount' for 'myaccount.1password.com'): "
        $accountShorthand = Read-Host -Prompt "$YELLOW➡️ Account shorthand: "
        Write-Host ""
        if (-not $accountShorthand) {
            Write-Host "$RED😕 Account shorthand cannot be empty. Please try again.$RESET"
            continue
        }
        # Validate that the shorthand only uses letters, numbers, and hyphens
        if ($accountShorthand -notmatch '^[a-zA-Z0-9-]+$') {
            Write-Host "$RED😕 Invalid account shorthand format: $accountShorthand. Use letters, numbers, and hyphens only.$RESET"
            $accountShorthand = $null
            continue
        }
    }

    # Sign in to 1Password CLI and grab the session token
    $processInfo = [System.Diagnostics.ProcessStartInfo]::new()
    $processInfo.FileName = "op"
    $processInfo.Arguments = "signin --account $accountShorthand --raw"
    $processInfo.RedirectStandardOutput = $true
    $processInfo.RedirectStandardError = $true
    $processInfo.UseShellExecute = $false
    $processInfo.CreateNoWindow = $true

    try {
        $process = [System.Diagnostics.Process]::Start($processInfo)
        $sessionToken = $process.StandardOutput.ReadToEnd().Trim()
        $stdErr = $process.StandardError.ReadToEnd()
        $process.WaitForExit()
        $exitCode = $process.ExitCode

        if ($exitCode -ne 0 -or ($stdErr -and $stdErr -match "\[ERROR\]")) {
            Write-Host "$RED😕 Failed to authenticate with 1Password CLI: $stdErr$RESET`n"
            exit 1
        }

        # Set the session token as an environment variable for future commands
        $envVarName = "OP_SESSION_$accountShorthand"
        [System.Environment]::SetEnvironmentVariable($envVarName, $sessionToken, [System.EnvironmentVariableTarget]::Process)
        Write-Host "$GREEN✅ Successfully authenticated with 1Password CLI.$RESET`n"
    }
    catch {
        Write-Host "$RED😕 Error during authentication: $($_.Exception.Message)$RESET`n"
        exit 1
    }
    finally {
        if ($process) { $process.Dispose() }
    }
}
else {
    Write-Host "$GREEN✅ Already authenticated with 1Password CLI.$RESET`n"
}

# Ask the user how they’d like to manage users (CSV, manual, export, or quit)
$inputMethod = $null
$validMethods = @("csv", "manual", "export", "quit")
$firstPrompt = $true

while (-not $inputMethod) {
    Write-Host "`n$YELLOW📋 How would you like to manage users?$RESET"
    if ($firstPrompt) {
        Write-Host "  1. Use a CSV file`n  2. Manually enter user details`n  3. Actually I want to export a csv list`n  4. Quit`n"
        $choice = Read-Host -Prompt "$YELLOW➡️ Enter 1, 2, 3, or 4: "
        Write-Host ""
        $inputMethod = switch ($choice) {
            "1" { "csv" }
            "2" { "manual" }
            "3" { "export" }
            "4" { "quit" }
            default { $null }
        }
        if (-not $inputMethod) {
            Write-Host "$RED😕 Invalid entry: $choice. Please enter 1, 2, 3, or 4.$RESET"
            continue
        }
    }
    else {
        $validMethods = @("csv", "manual", "quit")
        Write-Host "  1. Use a CSV file`n  2. Manually enter user details`n  3. Quit`n"
        $choice = Read-Host -Prompt "$YELLOW➡️ Enter 1, 2, or 3: "
        Write-Host ""
        $inputMethod = switch ($choice) {
            "1" { "csv" }
            "2" { "manual" }
            "3" { "quit" }
            default { $null }
        }
        if (-not $inputMethod) {
            Write-Host "$RED😕 Invalid entry: $choice. Please enter 1, 2, or 3.$RESET"
            continue
        }
    }

    # If they chose to export, show the user list and save it to a CSV file
    if ($inputMethod -eq "export") {
        $userList = Show-UserList -Action "delete"
        if (-not $userList) {
            Write-Host "$RED😕 Failed to export user list. Continuing...$RESET"
        }
        else {
            $timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
            $outputCsv = "user_list_${timestamp}.csv"
            $userList | Select-Object UUID, Name, Email, State | Export-Csv -Path $outputCsv -NoTypeInformation
            $fullOutputPath = (Get-Item $outputCsv).FullName
            Write-Host "$CYAN📊 User list exported to $fullOutputPath$RESET"
        }
        $inputMethod = $null
        $firstPrompt = $false
        continue
    }
}

if ($inputMethod -eq "quit") {
    Write-Host "$CYAN👋 Exiting script.$RESET`n"
    exit 0
}

# Ask what action the user wants to perform (provision, suspend, reactivate, delete, or quit)
$validActions = @("provision", "suspend", "reactivate", "delete", "quit")
$action = $null
while (-not $action) {
    Write-Host "`n$YELLOW📋 What would you like to do?$RESET"
    Write-Host "  1. Provision users (invite to 1Password)`n  2. Suspend users (disable account access)`n  3. Reactivate users (restore account access)`n  4. Delete users (permanently remove)`n  5. Quit`n"
    $choice = Read-Host -Prompt "$YELLOW➡️ Enter 1, 2, 3, 4, or 5: "
    Write-Host ""
    $action = switch ($choice) {
        "1" { "provision" }
        "2" { "suspend" }
        "3" { "reactivate" }
        "4" { "delete" }
        "5" { "quit" }
        default { $null }
    }
    if (-not $action) {
        Write-Host "$RED😕 Invalid entry: $choice. Please enter 1, 2, 3, 4, or 5.$RESET"
        continue
    }
}

if ($action -eq "quit") {
    Write-Host "$CYAN👋 Exiting script.$RESET`n"
    exit 0
}

# Set up a list to store the results of our actions
$results = [System.Collections.Generic.List[PSObject]]::new()

# Handle CSV input: read users from a file and process them
if ($inputMethod -eq "csv") {
    $defaultCsv = "people.csv"
    $csvPath = $null
    while (-not $csvPath) {
        Write-Host "`n$YELLOW📄 Enter the path to your CSV file (default: $defaultCsv, type 'quit' to exit):$RESET`n"
        $inputPath = Read-Host -Prompt "$YELLOW➡️ Path: "
        Write-Host ""
        if ($inputPath -eq "quit") {
            Write-Host "$CYAN👋 Exiting script.$RESET`n"
            exit 0
        }
        $csvPath = if ($inputPath) { $inputPath } else { $defaultCsv }
        if (-not (Test-Path $csvPath)) {
            Write-Host "$RED😕 Invalid file path: $csvPath does not exist. Please enter a valid file path or type 'quit' to exit.$RESET"
            $csvPath = $null
            continue
        }
    }

    # We're assuming the CSV always has a header row
    $skipFirst = 1

    try {
        $csvData = Import-Csv -Path $csvPath
        if (-not $csvData) {
            Write-Host "`n$RED😕 CSV file is empty.$RESET`n"
            exit 1
        }

        # Check that the CSV has the required fields based on the action
        if ($action -eq "provision") {
            # For provisioning, we need Name and Email columns
            $nameCol = $csvData[0].PSObject.Properties.Name | Where-Object { $_ -match "^Name$" }
            $emailCol = $csvData[0].PSObject.Properties.Name | Where-Object { $_ -match "^Email$" }
            if (-not $nameCol -or -not $emailCol) {
                Write-Host "`n$RED😕 CSV must have 'Name' and 'Email' columns for provisioning.$RESET`n"
                exit 1
            }
        }
        else {
            # For suspend, delete, reactivate, we need either a UUID or Email column
            $uuidCol = $csvData[0].PSObject.Properties.Name | Where-Object { $_ -match "^UUID$" }
            $emailCol = $csvData[0].PSObject.Properties.Name | Where-Object { $_ -match "^Email$" }
            if (-not $uuidCol -and -not $emailCol) {
                Write-Host "`n$RED😕 CSV must have either 'UUID' or 'Email' column for $action.$RESET`n"
                exit 1
            }
        }
    }
    catch {
        Write-Host "`n$RED😕 Error reading CSV: $($_.Exception.Message)$RESET`n"
        exit 1
    }

    # Gather identifiers and names for the confirmation table if needed
    $csvIdentifiers = @()
    $csvNames = @()
    foreach ($row in $csvData) {
        if ($action -eq "provision") {
            # For provisioning, grab Name and Email
            $name = if ($row.$nameCol) { $row.$nameCol -replace '"', "'" } else { "" }
            $email = if ($row.$emailCol) { $row.$emailCol } else { "" }
            $identifier = $email
        }
        else {
            # For suspend, delete, reactivate, use UUID if present, otherwise fall back to Email
            $uuid = if ($row.PSObject.Properties.Name -contains "UUID") { $row.UUID } else { "" }
            $email = if ($row.PSObject.Properties.Name -contains "Email") { $row.Email } else { "" }
            $identifier = if ($uuid) { $uuid } else { $email }
            $name = if ($row.PSObject.Properties.Name -contains "Name") { $row.Name } else { "" }
        }
        $csvIdentifiers += $identifier
        $csvNames += $name
    }

    # Give a warning before doing anything destructive and show a confirmation table
    if ($action -in @("suspend", "reactivate", "delete")) {
        Write-Host "`n"
        $msg = switch ($action) {
            "suspend" { "Suspending users disables their account access!" }
            "reactivate" { "Reactivating users will restore their account access!" }
            "delete" { "Deleting users and their Private vaults is permanent!" }
        }
        Write-Host "$RED$BLINK⚠️ WARNING: $msg$RESET`n"
        # Display the table with Names and UUID/Email
        Show-EmailList -Emails $csvIdentifiers -Action $action -Names $csvNames
        Write-Host "`n"
        $confirm = $null
        while (-not $confirm) {
            $confirm = Read-Host -Prompt "$YELLOW➡️ Type 'YES' to continue, or anything else to exit: "
            Write-Host ""
            if ($confirm -ne "YES") {
                Write-Host "$CYAN👋 Exiting script to prevent accidental $action.$RESET`n"
                exit 0
            }
            # No need for invalid input message here since any non-"YES" input exits
        }
    }

    # Process the users in the CSV file using multi-threading
    Write-Host "`n$CYAN🔧 Processing $($csvData.Count) users for $action...$RESET`n"
    $jobs = [System.Collections.ArrayList]::new()
    $maxThreads = 3
    $total = $csvData.Count
    $current = 0

    foreach ($row in $csvData) {
        while (@($jobs | Where-Object { $_.State -eq 'Running' }).Count -ge $maxThreads) {
            Start-Sleep -Milliseconds 100
        }

        $current++
        $percent = ($current / $total) * 100
        Write-Progress -Activity "Processing Users" -Status "$action user $current of $total" -PercentComplete $percent

        # Pull out only the fields we need based on the action
        if ($action -eq "provision") {
            # For provisioning, we just need Name and Email
            $name = if ($row.$nameCol) { $row.$nameCol -replace '"', "'" } else { "" }
            $email = if ($row.$emailCol) { $row.$emailCol } else { "" }
            $identifier = $email  # Not used for provisioning, but needed for consistency
        }
        else {
            # For suspend, delete, reactivate, prefer UUID if present, otherwise use Email
            $uuid = if ($row.PSObject.Properties.Name -contains "UUID") { $row.UUID } else { "" }
            $email = if ($row.PSObject.Properties.Name -contains "Email") { $row.Email } else { "" }
            $identifier = if ($uuid) { $uuid } else { $email }
            $name = if ($row.PSObject.Properties.Name -contains "Name") { $row.Name } else { "" }  # Optional, for results
        }

        $job = Start-ThreadJob -ScriptBlock {
            param($name, $identifier, $action)

            function Invoke-OpCommand {
                param (
                    [string[]]$Arguments
                )

                $processInfo = [System.Diagnostics.ProcessStartInfo]::new()
                $processInfo.FileName = "op"
                $processInfo.Arguments = $Arguments -join " "
                $processInfo.RedirectStandardOutput = $true
                $processInfo.RedirectStandardError = $true
                $processInfo.UseShellExecute = $false
                $processInfo.CreateNoWindow = $true

                try {
                    $process = [System.Diagnostics.Process]::Start($processInfo)
                    $stdOut = $process.StandardOutput.ReadToEnd()
                    $stdErr = $process.StandardError.ReadToEnd()
                    $process.WaitForExit()
                    $exitCode = $process.ExitCode

                    if ($exitCode -ne 0 -or ($stdErr -and $stdErr -match "\[ERROR\]")) {
                        return $false, $stdErr
                    }

                    $resultMessage = switch ($Arguments[1]) {
                        "provision" { "Provisioned successfully" }
                        "suspend" { "Suspended successfully" }
                        "reactivate" { "Reactivated successfully" }
                        "delete" { "Deleted successfully" }
                        default { $stdOut }
                    }
                    return $true, $resultMessage
                }
                catch {
                    $errorMessage = if ($_.Exception.Message) { $_.Exception.Message } else { "Unknown error" }
                    switch -Wildcard ($errorMessage) {
                        "*TRANSFER_PENDING*" {
                            if ($Arguments[1] -eq "provision") { return $true, "Provisioned successfully (transfer in progress)" }
                            return $false, "User transfer in progress"
                        }
                        "*TRANSFER_STARTED*" {
                            if ($Arguments[1] -eq "provision") { return $true, "Provisioned successfully (transfer in progress)" }
                            return $false, "User transfer in progress"
                        }
                        "*already a member*" { return $false, "User already exists" }
                        "*not found*" { return $false, "User not found" }
                        "*Resource Invalid*" { return $false, "Invalid domain" }
                        "*expected at most 0 arguments*" { return $false, "Invalid command syntax" }
                        default { return $false, $errorMessage }
                    }
                }
                finally {
                    if ($process) { $process.Dispose() }
                    [System.GC]::Collect()
                }
            }

            $status = "Success"
            $message = ""
            $fullMessage = ""

            if (-not $identifier) {
                $status = "Failed"
                $message = if ($action -eq "provision") { "Missing email address" } else { "Missing UUID or email address" }
                $fullMessage = $message
            }
            else {
                $opArgs = switch ($action) {
                    "provision" { @("user", "provision", "--name", "`"$name`"", "--email", $identifier) }
                    "suspend" { @("user", "suspend", $identifier, "--deauthorize-devices-after", "5m") }
                    "reactivate" { @("user", "reactivate", $identifier) }
                    "delete" { @("user", "delete", $identifier) }
                }
                $message = switch ($action) {
                    "provision" { "Provisioned successfully" }
                    "suspend" { "Suspended successfully" }
                    "reactivate" { "Reactivated successfully" }
                    "delete" { "Deleted successfully" }
                }
                $opResult = Invoke-OpCommand -Arguments $opArgs
                if ($opResult[0] -eq $false) {
                    $status = "Failed"
                    $message = $opResult[1]
                    $fullMessage = $message
                }
                else {
                    $status = "Success"
                    $message = $opResult[1]
                    $fullMessage = $message
                }
            }

            return [PSCustomObject]@{
                Name        = $name
                Email       = $identifier
                Status      = $status
                Message     = $message
                FullMessage = $fullMessage
            }
        } -ArgumentList $name, $identifier, $action

        $null = $jobs.Add($job)
    }

    foreach ($job in $jobs) {
        $result = $job | Receive-Job -Wait -AutoRemoveJob
        $results.Add($result)
    }
}
else {
    # Handle manual input: ask for user details one by one
    Write-Host "`n$CYAN🔧 Manually managing a user for $action...$RESET`n"
    $identifiers = @()

    if ($action -in @("suspend", "reactivate", "delete")) {
        $identifierInput = $null
        while (-not $identifierInput) {
            Write-Host "$YELLOW📋 Enter the user(s) UUID or email (separate multiple entries with commas, type 'list' to see filtered users, or 'quit' to exit):$RESET`n"
            $identifierInput = Read-Host -Prompt "$YELLOW➡️ UUID(s) or Email(s): "
            Write-Host ""
            if ($identifierInput -eq "quit") {
                Write-Host "$CYAN👋 Exiting script.$RESET`n"
                exit 0
            }
            if ($identifierInput -eq "list") {
                $userList = Show-UserList -Action $action
                if (-not $userList) {
                    Write-Host "`n$CYAN👋 Exiting script due to no users found.$RESET`n"
                    exit 0
                }
                $identifierInput = $null
                continue
            }
            if (-not $identifierInput) {
                Write-Host "$RED😕 UUID or email cannot be empty. Please enter a valid UUID or email, or type 'list' or 'quit'.$RESET`n"
                continue
            }
            else {
                $identifiers = $identifierInput -split "," | ForEach-Object { $_.Trim() }
                $allValid = $true
                foreach ($identifier in $identifiers) {
                    if (-not ($identifier -match '^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$') -and
                        -not ($identifier -match '^[a-zA-Z0-9]{26}$')) {
                        Write-Host "$RED😕 Invalid UUID or email format: $identifier. Please enter valid UUID(s) or email(s), or type 'list' or 'quit'.$RESET`n"
                        $allValid = $false
                        break
                    }
                }
                if (-not $allValid) {
                    $identifierInput = $null
                    continue
                }
            }
        }
    }
    else {
        $emailInput = $null
        while (-not $emailInput) {
            Write-Host "$YELLOW📋 Enter the user's email (type 'quit' to exit):$RESET`n"
            $emailInput = Read-Host -Prompt "$YELLOW➡️ Email: "
            Write-Host ""
            if ($emailInput -eq "quit") {
                Write-Host "$CYAN👋 Exiting script.$RESET`n"
                exit 0
            }
            if (-not $emailInput) {
                Write-Host "$RED😕 Email cannot be empty. Please enter a valid email address or type 'quit' to exit.$RESET`n"
                continue
            }
            if ($emailInput -notmatch '^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$') {
                Write-Host "$RED😕 Invalid email format: $emailInput. Please enter a valid email address or type 'quit' to exit.$RESET`n"
                $emailInput = $null
                continue
            }
        }
        $identifiers = @($emailInput)
    }

    if ($action -eq "provision") {
        $name = $null
        while (-not $name) {
            Write-Host "$YELLOW📋 Enter the user's name (type 'quit' to exit):$RESET`n"
            $name = Read-Host -Prompt "$YELLOW➡️ Name: "
            Write-Host ""
            if ($name -eq "quit") {
                Write-Host "$CYAN👋 Exiting script.$RESET`n"
                exit 0
            }
            if (-not $name) {
                Write-Host "$RED😕 Name cannot be empty. Please enter a valid name or type 'quit' to exit.$RESET`n"
                continue
            }
        }
    }

    # Process the manually entered users with multi-threading
    $jobs = [System.Collections.ArrayList]::new()
    $maxThreads = 3
    $userDetails = [System.Collections.Generic.List[PSObject]]::new()

    if ($action -in @("suspend", "reactivate", "delete")) {
        foreach ($identifier in $identifiers) {
            while (@($jobs | Where-Object { $_.State -eq 'Running' }).Count -ge $maxThreads) {
                Start-Sleep -Milliseconds 100
            }

            $job = Start-ThreadJob -ScriptBlock {
                param($identifier)

                function Invoke-OpCommand {
                    param (
                        [string[]]$Arguments
                    )

                    $processInfo = [System.Diagnostics.ProcessStartInfo]::new()
                    $processInfo.FileName = "op"
                    $processInfo.Arguments = $Arguments -join " "
                    $processInfo.RedirectStandardOutput = $true
                    $processInfo.RedirectStandardError = $true
                    $processInfo.UseShellExecute = $false
                    $processInfo.CreateNoWindow = $true

                    try {
                        $process = [System.Diagnostics.Process]::Start($processInfo)
                        $stdOut = $process.StandardOutput.ReadToEnd()
                        $stdErr = $process.StandardError.ReadToEnd()
                        $process.WaitForExit()
                        $exitCode = $process.ExitCode

                        if ($exitCode -ne 0 -or ($stdErr -and $stdErr -match "\[ERROR\]")) {
                            return $false, $stdErr
                        }

                        $resultMessage = $stdOut
                        return $true, $resultMessage
                    }
                    catch {
                        $errorMessage = if ($_.Exception.Message) { $_.Exception.Message } else { "Unknown error" }
                        if ($errorMessage -like "*not found*") {
                            return $false, "User not found"
                        }
                        return $false, $errorMessage
                    }
                    finally {
                        if ($process) { $process.Dispose() }
                        [System.GC]::Collect()
                    }
                }

                $opArgs = @("user", "get", $identifier)
                $opResult = Invoke-OpCommand -Arguments $opArgs
                $name = "Unknown"
                $email = $identifier
                if ($opResult[0] -eq $true) {
                    if ($opResult[1] -match "Name:\s*([^\n]+)") {
                        $name = $matches[1].Trim()
                    }
                    if ($opResult[1] -match "Email:\s*([^\n]+)") {
                        $email = $matches[1].Trim()
                    }
                }
                return [PSCustomObject]@{
                    Identifier = $identifier
                    Name       = $name
                    Email      = $email
                    Exists     = $opResult[0]
                    ErrorMessage = if (-not $opResult[0]) { $opResult[1] } else { $null }
                }
            } -ArgumentList $identifier

            $null = $jobs.Add($job)
        }

        foreach ($job in $jobs) {
            $result = $job | Receive-Job -Wait -AutoRemoveJob
            $userDetails.Add($result)
        }

        # Check if any users failed to process (e.g., not found)
        $failedUsers = $userDetails | Where-Object { -not $_.Exists }
        if ($failedUsers) {
            foreach ($failedUser in $failedUsers) {
                $results.Add([PSCustomObject]@{
                    Name        = $failedUser.Name
                    Email       = $failedUser.Identifier
                    Status      = "Failed"
                    Message     = $failedUser.ErrorMessage
                    FullMessage = $failedUser.ErrorMessage
                })
            }
            $timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
            $outputCsv = "${action}_${timestamp}.csv"
            $results | Select-Object Name, Email, Status, FullMessage | Export-Csv -Path $outputCsv -NoTypeInformation
            $fullOutputPath = (Get-Item $outputCsv).FullName
            Write-Host "`n"
            Show-Table -Data $results
            Write-Host "`n$CYAN📊 $action completed! Results saved to $fullOutputPath$RESET`n"
            Write-Host "$GREEN🎈 All done! Check the CSV for details.$RESET`n"
            exit 1
        }

        # Update the identifiers with the fetched email addresses
        $emails = @()
        foreach ($user in $userDetails) {
            $emails += $user.Email
        }
        $identifiers = $emails
    }
    else {
        $userDetails.Add([PSCustomObject]@{
            Identifier = $identifiers[0]
            Name       = $name
            Email      = $identifiers[0]
            Exists     = $true
            ErrorMessage = $null
        })
    }

    # Confirm before proceeding with destructive actions
    if ($action -in @("suspend", "reactivate", "delete")) {
        Write-Host "`n"
        $msg = switch ($action) {
            "suspend" { "Suspending user(s) '$($identifiers -join ", ")' will disable their account access!" }
            "reactivate" { "Reactivating user(s) '$($identifiers -join ", ")' will restore their account access!" }
            "delete" { "Deleting user(s) '$($identifiers -join ", ")' and their Private vaults is permanent!" }
        }
        Write-Host "$RED$BLINK⚠️ WARNING: $msg$RESET`n"
        Show-EmailList -Emails $identifiers -Action $action
        Write-Host "`n"
        $confirm = $null
        while (-not $confirm) {
            $confirm = Read-Host -Prompt "$YELLOW➡️ Type 'YES' to continue, or anything else to exit: "
            Write-Host ""
            if ($confirm -ne "YES") {
                Write-Host "$CYAN👋 Exiting script to prevent accidental $action.$RESET`n"
                exit 0
            }
            # No need for invalid input message here since any non-"YES" input exits
        }
    }

    Write-Host "$CYAN🔧 Processing user(s) for $action...$RESET`n"
    $jobs = [System.Collections.ArrayList]::new()
    $maxThreads = 3

    foreach ($user in $userDetails) {
        while (@($jobs | Where-Object { $_.State -eq 'Running' }).Count -ge $maxThreads) {
            Start-Sleep -Milliseconds 100
        }

        $job = Start-ThreadJob -ScriptBlock {
            param($name, $identifier, $action)

            function Invoke-OpCommand {
                param (
                    [string[]]$Arguments
                )

                $processInfo = [System.Diagnostics.ProcessStartInfo]::new()
                $processInfo.FileName = "op"
                $processInfo.Arguments = $Arguments -join " "
                $processInfo.RedirectStandardOutput = $true
                $processInfo.RedirectStandardError = $true
                $processInfo.UseShellExecute = $false
                $processInfo.CreateNoWindow = $true

                try {
                    $process = [System.Diagnostics.Process]::Start($processInfo)
                    $stdOut = $process.StandardOutput.ReadToEnd()
                    $stdErr = $process.StandardError.ReadToEnd()
                    $process.WaitForExit()
                    $exitCode = $process.ExitCode

                    if ($exitCode -ne 0 -or ($stdErr -and $stdErr -match "\[ERROR\]")) {
                        return $false, $stdErr
                    }

                    $resultMessage = switch ($Arguments[1]) {
                        "provision" { "Provisioned successfully" }
                        "suspend" { "Suspended successfully" }
                        "reactivate" { "Reactivated successfully" }
                        "delete" { "Deleted successfully" }
                        default { $stdOut }
                    }
                    return $true, $resultMessage
                }
                catch {
                    $errorMessage = if ($_.Exception.Message) { $_.Exception.Message } else { "Unknown error" }
                    switch -Wildcard ($errorMessage) {
                        "*TRANSFER_PENDING*" {
                            if ($Arguments[1] -eq "provision") { return $true, "Provisioned successfully (transfer in progress)" }
                            return $false, "User transfer in progress"
                        }
                        "*TRANSFER_STARTED*" {
                            if ($Arguments[1] -eq "provision") { return $true, "Provisioned successfully (transfer in progress)" }
                            return $false, "User transfer in progress"
                        }
                        "*already a member*" { return $false, "User already exists" }
                        "*not found*" { return $false, "User not found" }
                        "*Resource Invalid*" { return $false, "Invalid domain" }
                        "*expected at most 0 arguments*" { return $false, "Invalid command syntax" }
                        default { return $false, $errorMessage }
                    }
                }
                finally {
                    if ($process) { $process.Dispose() }
                    [System.GC]::Collect()
                }
            }

            $status = "Success"
            $message = ""
            $fullMessage = ""

            $opArgs = switch ($action) {
                "provision" { @("user", "provision", "--name", "`"$name`"", "--email", $identifier) }
                "suspend" { @("user", "suspend", $identifier, "--deauthorize-devices-after", "5m") }
                "reactivate" { @("user", "reactivate", $identifier) }
                "delete" { @("user", "delete", $identifier) }
            }
            $message = switch ($action) {
                "provision" { "Provisioned successfully" }
                "suspend" { "Suspended successfully" }
                "reactivate" { "Reactivated successfully" }
                "delete" { "Deleted successfully" }
            }
            $opResult = Invoke-OpCommand -Arguments $opArgs
            if ($opResult[0] -eq $false) {
                $status = "Failed"
                $message = $opResult[1]
                $fullMessage = $message
            }
            else {
                $status = "Success"
                $message = $opResult[1]
                $fullMessage = $message
            }

            return [PSCustomObject]@{
                Name        = $name
                Email       = $identifier
                Status      = $status
                Message     = $message
                FullMessage = $fullMessage
            }
        } -ArgumentList $user.Name, $user.Identifier, $action

        $null = $jobs.Add($job)
    }

    foreach ($job in $jobs) {
        $result = $job | Receive-Job -Wait -AutoRemoveJob
        $results.Add($result)
    }
}

# Save the results to a CSV file and display them in a table
$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$outputCsv = "${action}_${timestamp}.csv"
$results | Select-Object Name, Email, Status, FullMessage | Export-Csv -Path $outputCsv -NoTypeInformation
$fullOutputPath = (Get-Item $outputCsv).FullName

Show-Table -Data $results
Write-Host "`n$CYAN📊 $action completed! Results saved to $fullOutputPath$RESET`n"
Write-Host "$GREEN🎈 All done! Check the CSV for details.$RESET`n"

# Clean up memory
[System.GC]::Collect()