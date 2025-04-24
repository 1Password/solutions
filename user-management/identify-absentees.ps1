# Quick little script to track down 1Password users who haven’t logged in for a while.
# Spits out UUID, Name, Email, and Last_Login_Date to the console and a user_list.csv file.

# Handy spinner function for visual feedback (not used right now, but keeping it around)
function Show-Spinner {
    param (
        [string]$Message,
        [scriptblock]$Action
    )
    $spinner = @('|', '/', '-', '\\')
    $i = 0
    $job = Start-Job -ScriptBlock $Action
    try {
        while ($job.State -eq 'Running') {
            Write-Host -NoNewline "`r$Message $($spinner[$i % 4])" -ForegroundColor Yellow
            $i++
            Start-Sleep -Milliseconds 100
        }
        Write-Host -NoNewline "`r$(' ' * ($Message.Length + 2))`r"
        $result = Receive-Job -Job $job -Wait
        return $result
    }
    finally {
        try {
            if ($job.State -ne 'Completed') {
                Stop-Job -Job $job -ErrorAction SilentlyContinue
            }
            Remove-Job -Job $job -ErrorAction SilentlyContinue
        }
        catch {
            Write-Debug "Job cleanup skipped: $_"
        }
    }
}

# Toss in a blank line for a cleaner look
Write-Host ""

$days = Read-Host "How many days since last login makes someone idle?"

# Another blank line before the info box
Write-Host ""

# Set up the top box with some basic stats
$initHeader = "Initializing User Activity Check..."
$daysLine = "Days Threshold: $days"
$totalUsersLine = "Total Users Found: (pending)"
$activeUsersLine = "Active Users: (pending)"

# Grab the list of users from 1Password
try {
    $userListOutput = op user list
    $users = @()
    $lines = $userListOutput -split "`n" | Where-Object { $_ -match '^\S' }
    $header = $lines[0] -split '\s{2,}'
    $idIndex = $header.IndexOf('ID')
    $stateIndex = $header.IndexOf('STATE')
    foreach ($line in $lines | Select-Object -Skip 1) {
        $fields = $line -split '\s{2,}'
        if ($fields.Count -ge [math]::Max($idIndex, $stateIndex)) {
            $users += [PSCustomObject]@{
                id = $fields[$idIndex].Trim()
                state = $fields[$stateIndex].Trim()
            }
        }
    }
    $totalUsersLine = "Total Users Found: $($users.Count)"
} catch {
    $totalUsersLine = "Error: ‘op user list’ failed: $_"
}

# Count up the active users
$active_users = New-Object System.Collections.Concurrent.ConcurrentBag[object]
$totalUsers = ($users | Where-Object { $_.state -eq 'ACTIVE' }).Count
$activeUsersLine = "Active Users: $totalUsers"

# Figure out how wide the info box needs to be
$lines = @($initHeader, $daysLine, $totalUsersLine, $activeUsersLine)
$maxContentLength = ($lines | ForEach-Object { $_.Length } | Measure-Object -Maximum).Maximum
$paddingWidth = $maxContentLength
$totalWidth = $paddingWidth + 2

# Build the box borders
$topBorder = "┌" + ("─" * $totalWidth) + "┐"
$midBorder = "├" + ("─" * $totalWidth) + "┤"
$bottomBorder = "└" + ("─" * $totalWidth) + "┘"

# Format the box content
$headerRow = "│ " + $initHeader.PadRight($paddingWidth) + " │"
$daysRow = "│ " + $daysLine.PadRight($paddingWidth) + " │"
$totalUsersRow = "│ " + $totalUsersLine.PadRight($paddingWidth) + " │"
$activeUsersRow = "│ " + $activeUsersLine.PadRight($paddingWidth) + " │"

# Show the info box
Write-Host $topBorder -ForegroundColor Cyan
Write-Host $headerRow -ForegroundColor Cyan
Write-Host $midBorder -ForegroundColor Cyan
Write-Host $daysRow -ForegroundColor Cyan
if ($totalUsersLine.StartsWith("Error")) {
    Write-Host $totalUsersRow -ForegroundColor Red
} else {
    Write-Host $totalUsersRow -ForegroundColor Cyan
}
Write-Host $activeUsersRow -ForegroundColor Cyan
Write-Host $bottomBorder -ForegroundColor Cyan

# Let the user know we’re digging into the details
Write-Host "`nChecking user activity..." -ForegroundColor Cyan

# Kick off the user processing with three threads, showing a progress bar and spinner
$completedUsers = 0
$spinnerChars = @('|', '/', '-', '\\')
$spinnerIndex = 0
$usersToProcess = $users | Where-Object { $_.state -eq 'ACTIVE' }
$usersToProcess | ForEach-Object -Parallel {
    $user = $_
    $bag = $using:active_users
    try {
        $rawDetails = op user get $user.id --format=json
        $details = $rawDetails | ConvertFrom-Json -AsHashtable
        $bag.Add($details)
    } catch {
        Write-Host "Couldn’t grab info for user $($user.id). Skipping. Error: $_" -ForegroundColor Red
    }
} -ThrottleLimit 3 -AsJob | Out-Null

# Keep the user updated with progress and a spinner
while ($completedUsers -lt $totalUsers) {
    if ($active_users.Count -gt $completedUsers) {
        $completedUsers = $active_users.Count
        $percentComplete = ($completedUsers / $totalUsers) * 100
        Write-Progress -Activity "Processing active users" -Status "User $completedUsers of $totalUsers" -PercentComplete $percentComplete
    }
    Write-Host -NoNewline "`rWorking... $($spinnerChars[$spinnerIndex % 4])" -ForegroundColor Yellow
    $spinnerIndex++
    Start-Sleep -Milliseconds 100
}

# Clear the spinner and progress bar
Write-Host -NoNewline "`r$(' ' * "Working... |".Length)`r"
Write-Progress -Activity "Processing active users" -Completed

# Set up the time threshold for idle users
$threshold = $days * 86400
$now = [DateTime]::UtcNow

# Patterns to check date formats
$iso8601Pattern = '^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$'
$usDatePattern = '^\d{2}/\d{2}/\d{4}\s+\d{2}:\d{2}:\d{2}$'

# Find those idle users
$idle_users = New-Object System.Collections.ArrayList

# Space things out a bit
Write-Host ""

# Sort users by how long it’s been since they logged in
$active_users = $active_users | Sort-Object -Property {
    $last_auth_at = $_.last_auth_at
    if (-not $last_auth_at) { return 0 }
    if ($last_auth_at -eq "0001-01-01T00:00:00Z" -or $last_auth_at -eq "01/01/0001 00:00:00") {
        return [double]::MaxValue
    }
    try {
        $last_login = $null
        if ($last_auth_at -match $iso8601Pattern) {
            $last_login = [DateTime]::ParseExact(
                $last_auth_at,
                "yyyy-MM-ddTHH:mm:ssZ",
                [System.Globalization.CultureInfo]::InvariantCulture,
                [System.Globalization.DateTimeStyles]::AssumeUniversal -bor [System.Globalization.DateTimeStyles]::AdjustToUniversal
            )
        }
        elseif ($last_auth_at -match $usDatePattern) {
            $last_login = [DateTime]::ParseExact(
                $last_auth_at,
                "MM/dd/yyyy HH:mm:ss",
                [System.Globalization.CultureInfo]::InvariantCulture,
                [System.Globalization.DateTimeStyles]::AssumeUniversal -bor [System.Globalization.DateTimeStyles]::AdjustToUniversal
            )
        }
        if ($last_login) {
            return ($now - $last_login).TotalDays
        }
        return 0
    } catch {
        return 0
    }
} -Descending

# Check each user’s last login and flag the idle ones
foreach ($user in $active_users) {
    $last_auth_at = $user.last_auth_at
    if (-not $last_auth_at) {
        Write-Host "  $($user.email.PadRight(50)) No login date, skipping." -ForegroundColor Yellow
        continue
    }
    if ($last_auth_at -eq "0001-01-01T00:00:00Z" -or $last_auth_at -eq "01/01/0001 00:00:00") {
        Write-Host "  $($user.email.PadRight(50)) Never logged in" -ForegroundColor Red
        $user | Add-Member -MemberType NoteProperty -Name "DaysIdle" -Value "Never logged in" -Force
        $user | Add-Member -MemberType NoteProperty -Name "LastAuthAtString" -Value ([string]$last_auth_at) -Force
        $null = $idle_users.Add($user)
        continue
    }
    try {
        $last_login = $null
        if ($last_auth_at -match $iso8601Pattern) {
            $last_login = [DateTime]::ParseExact(
                $last_auth_at,
                "yyyy-MM-ddTHH:mm:ssZ",
                [System.Globalization.CultureInfo]::InvariantCulture,
                [System.Globalization.DateTimeStyles]::AssumeUniversal -bor [System.Globalization.DateTimeStyles]::AdjustToUniversal
            )
        }
        elseif ($last_auth_at -match $usDatePattern) {
            $last_login = [DateTime]::ParseExact(
                $last_auth_at,
                "MM/dd/yyyy HH:mm:ss",
                [System.Globalization.CultureInfo]::InvariantCulture,
                [System.Globalization.DateTimeStyles]::AssumeUniversal -bor [System.Globalization.DateTimeStyles]::AdjustToUniversal
            )
        }
        else {
            Write-Host "  $($user.email.PadRight(50)) Invalid date format ('$last_auth_at'), skipping." -ForegroundColor Yellow
            continue
        }
        $diff_seconds = ($now - $last_login).TotalSeconds
        $diff_days = [math]::Round($diff_seconds / 86400, 1)
        $color = if ($diff_days -gt $days) { "Red" } else { "Green" }
        Write-Host "  $($user.email.PadRight(50)) $diff_days days since login" -ForegroundColor $color
        if ($diff_days -gt $days) {
            $user | Add-Member -MemberType NoteProperty -Name "DaysIdle" -Value $diff_days -Force
            $user | Add-Member -MemberType NoteProperty -Name "LastAuthAtString" -Value ([string]$last_auth_at) -Force
            $null = $idle_users.Add($user)
        }
    } catch {
        Write-Host "  $($user.email.PadRight(50)) Failed to parse date ('$last_auth_at'). Error: $_" -ForegroundColor Yellow
        continue
    }
}

# Save the idle users to a CSV file
$output = $idle_users | Select-Object @{Name='UUID';Expression={$_.id}},
                                     @{Name='Name';Expression={$_.name}},
                                     @{Name='E-mail';Expression={$_.email}},
                                     @{Name='Last_Login_Date';Expression={$_.last_auth_at}} |
                ConvertTo-Csv -NoTypeInformation
$output | Out-File -FilePath .\user_list.csv

# Grab the full path to the CSV
$csvPath = (Resolve-Path -Path .\user_list.csv).Path

# Show the results in a neat table
Write-Host "`n" -NoNewline
if ($idle_users.Count -gt 0) {
    Write-Host "Here’s who’s been slacking for over $days days:" -ForegroundColor Cyan
    Write-Host ""
    $idle_users = $idle_users | Sort-Object -Property {
        $daysIdle = $_.DaysIdle
        if ($daysIdle -eq "Never logged in") { return [double]::MaxValue }
        return [double]$daysIdle
    } -Descending
    $emailHeader = "E-mail"
    $daysHeader = "Days Idle"
    $loginHeader = "Last Login"
    $emailMaxLength = [math]::Max(($idle_users | ForEach-Object { $_.email.Length } | Measure-Object -Maximum).Maximum, $emailHeader.Length)
    $daysMaxLength = [math]::Max(($idle_users | ForEach-Object { $_.DaysIdle.ToString().Length } | Measure-Object -Maximum).Maximum, $daysHeader.Length)
    $loginMaxLength = [math]::Max(($idle_users | ForEach-Object { $_.LastAuthAtString.Length } | Measure-Object -Maximum).Maximum, $loginHeader.Length)
    $emailMaxLength += 2
    $daysMaxLength += 2
    $loginMaxLength += 2
    $topBorder = "┌" + ("─" * $emailMaxLength) + "┬" + ("─" * $daysMaxLength) + "┬" + ("─" * $loginMaxLength) + "┐"
    $headerRow = "│ " + $emailHeader.PadRight($emailMaxLength - 2) + " │ " + $daysHeader.PadRight($daysMaxLength - 2) + " │ " + $loginHeader.PadRight($loginMaxLength - 2) + " │"
    $midBorder = "├" + ("─" * $emailMaxLength) + "┼" + ("─" * $daysMaxLength) + "┼" + ("─" * $loginMaxLength) + "┤"
    $bottomBorder = "└" + ("─" * $emailMaxLength) + "┴" + ("─" * $daysMaxLength) + "┴" + ("─" * $loginMaxLength) + "┘"
    Write-Host $topBorder -ForegroundColor Cyan
    Write-Host $headerRow -ForegroundColor Cyan
    Write-Host $midBorder -ForegroundColor Cyan
    foreach ($user in $idle_users) {
        $email = $user.email.PadRight($emailMaxLength - 2)
        $days_str = $user.DaysIdle.ToString().PadRight($daysMaxLength - 2)
        $login_str = $user.LastAuthAtString.PadRight($loginMaxLength - 2)
        Write-Host "│ $email │ $days_str │ $login_str │" -ForegroundColor White
    }
    Write-Host $bottomBorder -ForegroundColor Cyan
    Write-Host "`nAll done! Check $csvPath for the full list." -ForegroundColor Green
    Write-Host ""
} else {
    Write-Host "Nobody’s been idle for $days days. Everyone’s keeping up with 1Password!" -ForegroundColor Green
    Write-Host "`nAll done! Check $csvPath for the full list." -ForegroundColor Green
    Write-Host ""
}