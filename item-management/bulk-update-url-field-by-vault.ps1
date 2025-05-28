# Updates website fields for all items in a 1Password vault.
# Features: vault selection, URL updating, multithreaded processing, revert option, CSV output.

# Suppress verbose output to prevent stray output like -True.
$VerbosePreference = "SilentlyContinue"

# ANSI color codes for console output.
$global:Cyan = "`e[96m"
$global:Yellow = "`e[93m"
$global:Red = "`e[91m"
$global:Green = "`e[92m"
$global:Reset = "`e[0m"

# Helper function to word-wrap text within a specified width.
function Wrap-Text {
    param ([string]$Text, [int]$MaxWidth)

    if (-not $Text) { return @("") }
    $lines = [System.Collections.ArrayList]::new()
    $currentLine = ""
    $words = $Text -split "\s+"

    foreach ($word in $words) {
        $potentialLine = if ($currentLine) { "$currentLine $word" } else { $word }
        if ($potentialLine.Length -le $MaxWidth) {
            $currentLine = $potentialLine
        } else {
            if ($currentLine) { $null = $lines.Add($currentLine) }
            $currentLine = $word
        }
    }
    if ($currentLine) { $null = $lines.Add($currentLine) }
    return $lines
}

# Displays a table with results in a styled ASCII box.
function Show-TableInBox {
    param ([Parameter(Mandatory=$true)] [PSObject[]]$Data)

    $headers = "ItemID", "ItemTitle", "OldWebsite", "NewWebsite", "Error"
    $maxWidths = @{ ItemID = 30; ItemTitle = 30; OldWebsite = 30; NewWebsite = 30; Error = 80 }
    $minWidths = @{ ItemID = 28; ItemTitle = 20; OldWebsite = 20; NewWebsite = 20; Error = 50 }

    # Calculate maximum content length for each column.
    $lengths = @{}
    $wrappedErrors = @{}
    foreach ($header in $headers) {
        if ($header -eq "Error") {
            # For Error column, use fixed width and wrap text.
            $lengths[$header] = [math]::Min([math]::Max(50, $minWidths[$header]), $maxWidths[$header])
            $wrappedErrors = $Data | ForEach-Object {
                $errorText = ($($_.$header ?? "").ToString())
                $itemID = ($_.ItemID ?? "").ToString()
                [PSCustomObject]@{
                    ItemID = $itemID
                    Lines = (Wrap-Text -Text $errorText -MaxWidth ($lengths[$header] - 4))
                }
            }
        } else {
            # For other columns, use dynamic width based on content, no truncation.
            $maxDataLength = ($Data | ForEach-Object { ($($_.$header ?? "").ToString()).Length } | Measure-Object -Maximum).Maximum
            $headerLength = $header.Length
            $lengths[$header] = [math]::Min([math]::Max([math]::Max($maxDataLength, $headerLength), $minWidths[$header]) + 4, $maxWidths[$header])
        }
    }

    # Build table borders.
    $top = "┌" + ($headers | ForEach-Object { "─" * $lengths[$_] } | Join-String -Separator "┬") + "┐"
    $mid = "├" + ($headers | ForEach-Object { "─" * $lengths[$_] } | Join-String -Separator "┼") + "┤"
    $bottom = "└" + ($headers | ForEach-Object { "─" * $lengths[$_] } | Join-String -Separator "┴") + "┘"
    $headerRow = "│" + ($headers | ForEach-Object { " " + $_.PadRight($lengths[$_] - 2) + " " } | Join-String -Separator "│") + "│"

    # Output table.
    Write-Host $top -ForegroundColor Cyan
    Write-Host $headerRow -ForegroundColor Cyan
    Write-Host $mid -ForegroundColor Cyan
    foreach ($item in $Data) {
        $itemID = ($item.ItemID ?? "").ToString()
        $errorLines = ($wrappedErrors | Where-Object { $_.ItemID -eq $itemID } | Select-Object -First 1).Lines ?? @("")
        $maxLines = [math]::Max(1, $errorLines.Count)
        for ($i = 0; $i -lt $maxLines; $i++) {
            $row = "│" + ($headers | ForEach-Object {
                $value = if ($_ -eq "Error") {
                    if ($i -lt $errorLines.Count) { $errorLines[$i] } else { "" }
                } else {
                    if ($i -eq 0) { ($item.$_ ?? "").ToString() } else { "" }
                }
                " " + ($value ?? "").PadRight($lengths[$_] - 2) + " "
            } | Join-String -Separator "│") + "│"
            Write-Host $row -ForegroundColor White
        }
        if ($item -ne $Data[-1]) { Write-Host $mid -ForegroundColor Cyan }
    }
    Write-Host $bottom -ForegroundColor Cyan
}

# Executes a 1Password CLI command and returns output and error.
function Invoke-OpCommand {
    param ([Parameter(Mandatory=$true)] [string[]]$Arguments)

    $processInfo = [System.Diagnostics.ProcessStartInfo]::new()
    $processInfo.FileName = "op"
    $processInfo.Arguments = $Arguments -join " "
    $processInfo.RedirectStandardOutput = $true
    $processInfo.RedirectStandardError = $true
    $processInfo.UseShellExecute = $false
    $processInfo.CreateNoWindow = $true

    try {
        $process = [System.Diagnostics.Process]::Start($processInfo)
        $stdOut = $process.StandardOutput.ReadToEnd().Trim()
        $stdErr = $process.StandardError.ReadToEnd()
        $process.WaitForExit()
        if ($process.ExitCode -ne 0 -or ($stdErr -and $stdErr -match "\[ERROR\]")) {
            return $null, "Command failed: op $($Arguments -join ' ') - $stdErr"
        }
        return $stdOut, $null
    }
    catch {
        return $null, "Exception: op $($Arguments -join ' ') - $($_.Exception.Message)"
    }
    finally {
        if ($process) { $process.Dispose() }
    }
}

# Authenticates with 1Password CLI.
function Check-OpAuth {
    $authCheck = Invoke-OpCommand @("user", "list")
    if ($authCheck[0]) {
        Write-Host "`n$($global:Green)✅ Authenticated with 1Password CLI.$($global:Reset)"
        return $true
    }

    Write-Host "`n$($global:Yellow)🔐 Please authenticate with 1Password CLI.$($global:Reset)"
    for ($attempt = 1; $attempt -le 3; $attempt++) {
        Write-Host -NoNewline "$($global:Yellow)➡️ Account shorthand (e.g., 'myaccount') [Attempt $attempt/3]: $($global:Reset)"
        $accountShorthand = Read-Host
        Write-Host ""
        if (-not $accountShorthand -or $accountShorthand -notmatch '^[a-zA-Z0-9-]+$') {
            Write-Host "$($global:Red)😕 Invalid or empty shorthand. Use letters, numbers, hyphens.$($global:Reset)"
            continue
        }

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
            if ($process.ExitCode -ne 0 -or ($stdErr -and $stdErr -match "\[ERROR\]")) {
                Write-Host "$($global:Red)😕 Authentication failed: $stdErr$($global:Reset)"
                continue
            }
            [System.Environment]::SetEnvironmentVariable("OP_SESSION_$accountShorthand", $sessionToken, [System.EnvironmentVariableTarget]::Process)
            Write-Host "`n$($global:Green)✅ Authenticated with 1Password CLI.$($global:Reset)"
            return $true
        }
        catch {
            Write-Host "$($global:Red)😕 Authentication error: $($_.Exception.Message)$($global:Reset)"
        }
        finally {
            if ($process) { $process.Dispose() }
        }
    }
    Write-Host "$($global:Red)😕 Maximum attempts reached. Exiting.$($global:Reset)"
    return $false
}

# Main script logic.
if (-not (Check-OpAuth)) { exit 1 }

# Select vault.
Write-Host "`n$($global:Cyan)🚀 Starting website field update...$($global:Reset)"
$vault = $null
$showListPrompt = $true
while (-not $vault) {
    Write-Host ""
    Write-Host ($showListPrompt ? "Enter vault name/UUID or press Enter to list vaults:" : "Enter vault name/UUID:")
    Write-Host -NoNewline "$($global:Yellow)➡️ Choice: $($global:Reset)"
    $vaultInput = Read-Host

    if ($vaultInput.ToLower() -in 'quit', 'exit') {
        Write-Host "`n$($global:Yellow)🚫 Exiting.$($global:Reset)"
        exit 0
    }

    if (-not $vaultInput -or $vaultInput.ToLower() -eq 'list') {
        Write-Host "`n$($global:Cyan)📋 Available vaults:$($global:Reset)"
        $vaultsJson, $err = Invoke-OpCommand @("vault", "list", "--format=json")
        if ($vaultsJson) {
            $vaults = $vaultsJson | ConvertFrom-Json
            $vaults | ForEach-Object { Write-Host "  - $($_.name) (ID: $($_.id))" }
        } else {
            Write-Host "$($global:Red)😕 Failed to list vaults: $err$($global:Reset)"
        }
        $showListPrompt = $false
        continue
    }

    $vaultsJson, $err = Invoke-OpCommand @("vault", "list", "--format=json")
    if (-not $vaultsJson) {
        Write-Host "$($global:Red)😕 Failed to retrieve vaults: $err$($global:Reset)"
        $showListPrompt = $false
        continue
    }
    $vaults = $vaultsJson | ConvertFrom-Json
    $vault = $vaults | Where-Object { $_.name -eq $vaultInput -or $_.id -eq $vaultInput } | Select-Object -First 1
    if (-not $vault) {
        Write-Host "$($global:Red)😕 Vault '$vaultInput' not found. Try again or press Enter to list vaults.$($global:Reset)"
        $showListPrompt = $false
        continue
    }

    Write-Host ""
    Write-Host "Selected vault '$($vault.name)' (ID: $($vault.id)). Confirm? (Y/n)"
    Write-Host -NoNewline "$($global:Yellow)➡️ Choice: $($global:Reset)"
    $confirm = Read-Host
    if ($confirm.ToLower() -eq 'n') {
        $vault = $null
        $showListPrompt = $true
    } elseif ($confirm -and $confirm.ToLower() -ne 'y') {
        Write-Host "$($global:Red)😕 Enter 'y' or 'n'.$($global:Reset)"
        $vault = $null
    }
}

# Prompt for new URL.
$confirmed = $false
while (-not $confirmed) {
    $newURL = ""
    while (-not $newURL) {
        Write-Host ""
        Write-Host "🌐 Enter new website URL (e.g., https://example.com):"
        Write-Host -NoNewline "$($global:Yellow)➡️ URL: $($global:Reset)"
        $newURL = Read-Host
        if (-not $newURL) { Write-Host "$($global:Red)😕 URL required.$($global:Reset)" }
    }

    Write-Host ""
    Write-Host "Entered '$newURL'. Confirm? (Y/n)"
    Write-Host -NoNewline "$($global:Yellow)➡️ Choice: $($global:Reset)"
    $confirm = Read-Host
    if (-not $confirm) { $confirm = 'y' }
    if ($confirm.ToLower() -eq 'y') {
        $confirmed = $true
    } elseif ($confirm.ToLower() -ne 'n') {
        Write-Host "$($global:Red)😕 Enter 'y' or 'n'.$($global:Reset)"
    }
}

# Retrieve vault items.
Write-Host "$($global:Cyan)🔍 Retrieving items from vault '$($vault.name)'...$($global:Reset)"
$itemsJson, $err = Invoke-OpCommand @("item", "list", "--vault", $vault.id, "--format=json")
if (-not $itemsJson) {
    Write-Host "$($global:Yellow)😕 No items found: $($err ?? 'Unknown error').$($global:Reset)"
    exit 0
}
try {
    $items = $itemsJson | ConvertFrom-Json -ErrorAction Stop
} catch {
    Write-Host "$($global:Red)😕 Failed to parse items: $($_.Exception.Message)$($global:Reset)"
    exit 1
}
if (-not $items) {
    Write-Host "$($global:Yellow)😕 No items found in vault '$($vault.name)'. Nothing to update.$($global:Reset)"
    exit 0
}

# Filter valid items.
$validItems = $items | Where-Object { $_.id -and $_.id -ne "" } | ForEach-Object { [PSCustomObject]@{ id = $_.id; title = $_.title ?? "" } }
$invalidItems = $items | Where-Object { -not ($_.id -and $_.id -ne "") }
if ($invalidItems) {
    Write-Host "$($global:Yellow)😕 Skipped $($invalidItems.Count) invalid items without IDs.$($global:Reset)"
}
if (-not $validItems) {
    Write-Host "$($global:Yellow)😕 No valid items found. Nothing to update.$($global:Reset)"
    exit 0
}

# Process items with multithreading.
Write-Host ""
Write-Host "$($global:Cyan)🔧 Updating website fields for $($validItems.Count) items...$($global:Reset)"
$completedItems = 0
$spinnerChars = @('|', '/', '-', '\')
$spinnerIndex = 0
$changes = New-Object System.Collections.Concurrent.ConcurrentBag[object]
$editQueue = New-Object System.Collections.Concurrent.ConcurrentQueue[PSObject]
$editErrors = New-Object 'System.Collections.Concurrent.ConcurrentDictionary`2[System.String,System.String]'
$timeoutSeconds = 60
$startTime = Get-Date
$jobs = @()

# Start queue job for serialized edits.
$editJobRunning = $true
$editJob = Start-ThreadJob -ScriptBlock {
    param($queue, $errors, $globalColors)
    function Invoke-OpCommand {
        param ([Parameter(Mandatory=$true)] [string[]]$Arguments)
        $processInfo = [System.Diagnostics.ProcessStartInfo]::new()
        $processInfo.FileName = "op"
        $processInfo.Arguments = $Arguments -join " "
        $processInfo.RedirectStandardOutput = $true
        $processInfo.RedirectStandardError = $true
        $processInfo.UseShellExecute = $false
        $processInfo.CreateNoWindow = $true
        try {
            $process = [System.Diagnostics.Process]::Start($processInfo)
            $stdOut = $process.StandardOutput.ReadToEnd().Trim()
            $stdErr = $process.StandardError.ReadToEnd()
            $process.WaitForExit()
            if ($process.ExitCode -ne 0 -or ($stdErr -and $stdErr -match "\[ERROR\]")) {
                return $null, "Command failed: op $($Arguments -join ' ') - $stdErr"
            }
            return $stdOut, $null
        }
        catch {
            return $null, "Exception: op $($Arguments -join ' ') - $($_.Exception.Message)"
        }
        finally {
            if ($process) { $process.Dispose() }
        }
    }

    $item = $null
    while ($using:editJobRunning -or $queue.Count -gt 0) {
        if ($queue.TryDequeue([ref]$item)) {
            if ($item.ItemID -and $item.NewWebsite) {
                try {
                    $editResult, $err = Invoke-OpCommand @("item", "edit", $item.ItemID, "website=$($item.NewWebsite)")
                    if ($err) {
                        $errors.TryAdd($item.ItemID, "Failed to update website: $err")
                        Write-Host "$($globalColors.Red)😕 Error updating item $($item.ItemID) ($($item.ItemTitle)): $err$($globalColors.Reset)"
                    }
                } catch {
                    $err = $_.Exception.Message
                    $errors.TryAdd($item.ItemID, "Failed to update website: $err")
                    Write-Host "$($globalColors.Red)😕 Exception updating item $($item.ItemID) ($($item.ItemTitle)): $err$($globalColors.Reset)"
                }
            } else {
                $errors.TryAdd($item.ItemID, "Invalid edit command: Missing ID or URL")
                Write-Host "$($globalColors.Red)😕 Invalid edit command for item $($item.ItemID) ($($item.ItemTitle))$($globalColors.Reset)"
            }
        } else {
            Start-Sleep -Milliseconds 5
        }
    }
} -ArgumentList $editQueue, $editErrors, @{ Cyan = $global:Cyan; Yellow = $global:Yellow; Red = $global:Red; Green = $global:Green; Reset = $global:Reset }

# Thread script for fetching item details in parallel.
$threadScriptBlock = {
    param($itemId, $itemTitle, $newURL, $globalColors)
    function Invoke-OpCommand {
        param ([Parameter(Mandatory=$true)] [string[]]$Arguments)
        $processInfo = [System.Diagnostics.ProcessStartInfo]::new()
        $processInfo.FileName = "op"
        $processInfo.Arguments = $Arguments -join " "
        $processInfo.RedirectStandardOutput = $true
        $processInfo.RedirectStandardError = $true
        $processInfo.UseShellExecute = $false
        $processInfo.CreateNoWindow = $true
        try {
            $process = [System.Diagnostics.Process]::Start($processInfo)
            $stdOut = $process.StandardOutput.ReadToEnd().Trim()
            $stdErr = $process.StandardError.ReadToEnd()
            $process.WaitForExit()
            if ($process.ExitCode -ne 0 -or ($stdErr -and $stdErr -match "\[ERROR\]")) {
                return $null, "Command failed: op $($Arguments -join ' ') - $stdErr"
            }
            return $stdOut, $null
        }
        catch {
            return $null, "Exception: op $($Arguments -join ' ') - $($_.Exception.Message)"
        }
        finally {
            if ($process) { $process.Dispose() }
        }
    }

    $errorMessage = ""
    $currentWebsite = ""
    if (-not $itemId) {
        $errorMessage = "Invalid or missing item ID"
        Write-Host "$($globalColors.Red)😕 Error retrieving item ($itemTitle): $errorMessage$($globalColors.Reset)"
    } else {
        try {
            $itemDetails, $err = Invoke-OpCommand @("item", "get", $itemId)
            if (-not $itemDetails) {
                $errorMessage = "Failed to retrieve item details: $($err ?? 'Unknown error')"
                Write-Host "$($globalColors.Red)😕 Error retrieving item $itemId ($itemTitle): $errorMessage$($globalColors.Reset)"
            } else {
                $inUrlsSection = $false
                foreach ($line in ($itemDetails -split "`n")) {
                    if ($line -match "^URLs:") { $inUrlsSection = $true; continue }
                    if ($inUrlsSection -and $line -match "^:.*\(primary\)") {
                        $currentWebsite = ($line -replace "^:\s*" -replace "\s*\(primary\)$").Trim()
                        break
                    }
                    if ($inUrlsSection -and $line -notmatch "^\s*:") { break }
                }
                ($using:editQueue).Enqueue([PSCustomObject]@{ ItemID = $itemId; ItemTitle = $itemTitle; NewWebsite = $newURL })
            }
        } catch {
            $errorMessage = "Exception retrieving item details: $($_.Exception.Message)"
            Write-Host "$($globalColors.Red)😕 Exception retrieving item $itemId ($itemTitle): $errorMessage$($globalColors.Reset)"
        }
    }

    [PSCustomObject]@{
        ItemID = $itemId
        ItemTitle = $itemTitle
        OldWebsite = $currentWebsite
        NewWebsite = if ($errorMessage) { "" } else { $newURL }
        Error = $errorMessage
    }
}

# Start parallel threads for fetching details.
foreach ($item in $validItems) {
    $jobs += Start-ThreadJob -ScriptBlock $threadScriptBlock -ArgumentList $item.id, $item.title, $newURL, @{
        Cyan = $global:Cyan
        Yellow = $global:Yellow
        Red = $global:Red
        Green = $global:Green
        Reset = $global:Reset
    } -ThrottleLimit 3
}

# Monitor thread progress.
while ($completedItems -lt $validItems.Count -and ((Get-Date) - $startTime).TotalSeconds -lt $timeoutSeconds) {
    $completedJobs = $jobs | Where-Object { $_.State -eq "Completed" }
    if ($completedJobs) {
        foreach ($job in $completedJobs) {
            $result = Receive-Job -Job $job
            if ($result) { $changes.Add($result) }
            $completedItems = $changes.Count
            $percentComplete = ($completedItems / $validItems.Count) * 100
            Write-Progress -Activity "Updating items in vault '$($vault.name)'" -Status "Item $completedItems of $($validItems.Count)" -PercentComplete $percentComplete
            Write-Host -NoNewline "`rProcessing items ($completedItems of $($validItems.Count)) $($spinnerChars[$spinnerIndex % 4]) " -ForegroundColor Yellow
            $spinnerIndex++
        }
    }
    $failedJobs = $jobs | Where-Object { $_.State -eq "Failed" }
    if ($failedJobs) {
        foreach ($job in $failedJobs) {
            $errInfo = Receive-Job -Job $job -Keep
            Write-Host "$($global:Red)😕 Thread job failed: $errInfo$($global:Reset)"
        }
    }
    Start-Sleep -Milliseconds 100
}

# Handle thread timeouts.
if ($completedItems -lt $validItems.Count) {
    Write-Host "`n$($global:Red)😕 Timed out after $timeoutSeconds seconds. $($validItems.Count - $completedItems) items not processed.$($global:Reset)"
    foreach ($job in $jobs) {
        if ($job.State -ne "Completed") {
            Stop-Job -Job $job
            $errInfo = Receive-Job -Job $job -Keep
            Write-Host "$($global:Red)😕 Thread job $($job.Name) failed or stopped: $errInfo$($global:Reset)"
        }
        Remove-Job -Job $job -Force
    }
    $editJobRunning = $false
    Stop-Job -Job $editJob
    Receive-Job -Job $editJob -AutoRemoveJob -Wait
    exit 1
}

# Clean up threads.
foreach ($job in $jobs) { Receive-Job -Job $job -AutoRemoveJob -Wait }

# Wait for queue to complete.
$queueTimeout = 90
$queueStartTime = Get-Date
while ($editQueue.Count -gt 0 -and ((Get-Date) - $queueStartTime).TotalSeconds -lt $queueTimeout) {
    Start-Sleep -Milliseconds 100
}

if ($editQueue.Count -gt 0) {
    Write-Host "$($global:Red)😕 Edit queue timed out after $queueTimeout seconds. $($editQueue.Count) items remain.$($global:Reset)"
    $editJobRunning = $false
    Stop-Job -Job $editJob
    Receive-Job -Job $editJob -AutoRemoveJob -Wait
    exit 1
}

# Stop queue job.
$editJobRunning = $false
Stop-Job -Job $editJob
Receive-Job -Job $editJob -AutoRemoveJob -Wait

# Update results with errors.
$changesArray = $changes.ToArray()
foreach ($change in $changesArray) {
    if ($editErrors.ContainsKey($change.ItemID)) {
        $change.Error = $editErrors[$change.ItemID]
        $change.NewWebsite = ""
    }
}

# Clear progress.
Write-Host -NoNewline "`r$(' ' * 50)`r"
Write-Progress -Activity "Updating items in vault '$($vault.name)'" -Completed

# Save results to CSV.
$timestamp = Get-Date -Format 'yyyyMMdd_HHmmss'
$csvPath = "website_changes_$($vault.name)_$timestamp.csv"
$changesArray | Export-Csv -Path $csvPath -NoTypeInformation
$fullCsvPath = (Resolve-Path -Path $csvPath).Path

# Confirm changes.
$changesConfirmed = $false
while (-not $changesConfirmed) {
    Write-Host ""
    Write-Host "$($global:Cyan)📊 Update complete!$($global:Reset)"
    if (-not $changesArray) {
        Write-Host "$($global:Yellow)😕 No items updated.$($global:Reset)"
    } else {
        Show-TableInBox -Data $changesArray
        Write-Host ""
        Write-Host "$($global:Cyan)Changes saved to $fullCsvPath$($global:Reset)"
        Write-Host ""
    }
    Write-Host "Confirm changes? (Y/n/revert)"
    Write-Host -NoNewline "$($global:Yellow)➡️ Choice: $($global:Reset)"
    $confirm = Read-Host
    if (-not $confirm) { $confirm = 'y' }

    if ($confirm.ToLower() -eq 'revert') {
        Write-Host ""
        Write-Host "$($global:Yellow)🔄 Reverting changes...$($global:Reset)"
        $completedItems = 0
        $revertChanges = New-Object System.Collections.Concurrent.ConcurrentBag[object]
        $revertQueue = New-Object System.Collections.Concurrent.ConcurrentQueue[PSObject]
        $revertErrors = New-Object 'System.Collections.Concurrent.ConcurrentDictionary`2[System.String,System.String]'
        $revertJobs = @()

        # Start queue job for revert.
        $revertJobRunning = $true
        $revertJob = Start-ThreadJob -ScriptBlock {
            param($queue, $errors, $globalColors)
            function Invoke-OpCommand {
                param ([Parameter(Mandatory=$true)] [string[]]$Arguments)
                $processInfo = [System.Diagnostics.ProcessStartInfo]::new()
                $processInfo.FileName = "op"
                $processInfo.Arguments = $Arguments -join " "
                $processInfo.RedirectStandardOutput = $true
                $processInfo.RedirectStandardError = $true
                $processInfo.UseShellExecute = $false
                $processInfo.CreateNoWindow = $true
                try {
                    $process = [System.Diagnostics.Process]::Start($processInfo)
                    $stdOut = $process.StandardOutput.ReadToEnd().Trim()
                    $stdErr = $process.StandardError.ReadToEnd()
                    $process.WaitForExit()
                    if ($process.ExitCode -ne 0 -or ($stdErr -and $stdErr -match "\[ERROR\]")) {
                        return $null, "Command failed: op $($Arguments -join ' ') - $stdErr"
                    }
                    return $stdOut, $null
                }
                catch {
                    return $null, "Exception: op $($Arguments -join ' ') - $($_.Exception.Message)"
                }
                finally {
                    if ($process) { $process.Dispose() }
                }
            }

            $item = $null
            while ($using:revertJobRunning -or $queue.Count -gt 0) {
                if ($queue.TryDequeue([ref]$item)) {
                    if ($item.ItemID -and $item.OldWebsite) {
                        try {
                            $revertResult, $err = Invoke-OpCommand @("item", "edit", $item.ItemID, "website=$($item.OldWebsite)")
                            if ($err) {
                                $errors.TryAdd($item.ItemID, "Failed to revert website: $err")
                                Write-Host "$($globalColors.Red)😕 Failed to revert item $($item.ItemID) ($($item.ItemTitle)): $err$($globalColors.Reset)"
                            }
                        } catch {
                            $err = $_.Exception.Message
                            $errors.TryAdd($item.ItemID, "Failed to revert website: $err")
                            Write-Host "$($globalColors.Red)😕 Exception reverting item $($item.ItemID) ($($item.ItemTitle)): $err$($globalColors.Reset)"
                        }
                    } else {
                        $errors.TryAdd($item.ItemID, "Skipped revert: Update failed or invalid ID")
                        Write-Host "$($globalColors.Yellow)😕 Skipped revert for item $($item.ItemID) ($($item.ItemTitle))$($globalColors.Reset)"
                    }
                } else {
                    Start-Sleep -Milliseconds 5
                }
            }
        } -ArgumentList $revertQueue, $revertErrors, @{ Cyan = $global:Cyan; Yellow = $global:Yellow; Red = $global:Red; Green = $global:Green; Reset = $global:Reset }

        # Queue revert tasks.
        foreach ($change in $changesArray) {
            $revertJobs += Start-ThreadJob -ScriptBlock {
                param($itemId, $itemTitle, $oldWebsite, $globalColors)
                $errorMessage = ""
                if ($itemId -and $oldWebsite) {
                    ($using:revertQueue).Enqueue([PSCustomObject]@{ ItemID = $itemId; ItemTitle = $itemTitle; OldWebsite = $oldWebsite })
                } else {
                    $errorMessage = "Skipped revert: Update failed or invalid ID"
                    Write-Host "$($globalColors.Yellow)😕 Skipped revert for item $itemId ($itemTitle)$($globalColors.Reset)"
                }
                [PSCustomObject]@{ ItemID = $itemId; ItemTitle = $itemTitle; OldWebsite = $oldWebsite; NewWebsite = ""; Error = $errorMessage }
            } -ArgumentList $change.ItemID, $change.ItemTitle, $change.OldWebsite, @{
                Cyan = $global:Cyan
                Yellow = $global:Yellow
                Red = $global:Red
                Green = $global:Green
                Reset = $global:Reset
            } -ThrottleLimit 3
        }

        # Monitor revert progress.
        while ($completedItems -lt $changesArray.Count -and ((Get-Date) - $startTime).TotalSeconds -lt $timeoutSeconds) {
            $completedJobs = $revertJobs | Where-Object { $_.State -eq "Completed" }
            if ($completedJobs) {
                foreach ($job in $completedJobs) {
                    $result = Receive-Job -Job $job
                    if ($result) { $revertChanges.Add($result) }
                    $completedItems = $revertChanges.Count
                    $percentComplete = ($completedItems / $changesArray.Count) * 100
                    Write-Progress -Activity "Reverting changes in vault '$($vault.name)'" -Status "Item $completedItems of $($changesArray.Count)" -PercentComplete $percentComplete
                    Write-Host -NoNewline "`rReverting items ($completedItems of $($changesArray.Count)) $($spinnerChars[$spinnerIndex % 4]) " -ForegroundColor Yellow
                    $spinnerIndex++
                }
            }
            $failedJobs = $revertJobs | Where-Object { $_.State -eq "Failed" }
            if ($failedJobs) {
                foreach ($job in $failedJobs) {
                    $errInfo = Receive-Job -Job $job -Keep
                    Write-Host "$($global:Red)😕 Thread job failed: $errInfo$($global:Reset)"
                }
            }
            Start-Sleep -Milliseconds 100
        }

        # Handle revert timeouts.
        if ($completedItems -lt $changesArray.Count) {
            Write-Host "`n$($global:Red)😕 Revert timed out after $timeoutSeconds seconds. $($changesArray.Count - $completedItems) items not processed.$($global:Reset)"
            foreach ($job in $revertJobs) {
                if ($job.State -ne "Completed") {
                    Stop-Job -Job $job
                    $errInfo = Receive-Job -Job $job -Keep
                    Write-Host "$($global:Red)😕 Thread job $($job.Name) failed or stopped: $errInfo$($global:Reset)"
                }
                Remove-Job -Job $job -Force
            }
            $revertJobRunning = $false
            Stop-Job -Job $revertJob
            Receive-Job -Job $revertJob -AutoRemoveJob -Wait
            exit 1
        }

        # Clean up revert threads.
        foreach ($job in $revertJobs) { Receive-Job -Job $job -AutoRemoveJob -Wait }

        # Wait for revert queue.
        while ($revertQueue.Count -gt 0 -and ((Get-Date) - $queueStartTime).TotalSeconds -lt $queueTimeout) {
            Start-Sleep -Milliseconds 100
        }

        if ($revertQueue.Count -gt 0) {
            Write-Host "$($global:Red)😕 Revert queue timed out after $queueTimeout seconds. $($revertQueue.Count) items remain.$($global:Reset)"
            $revertJobRunning = $false
            Stop-Job -Job $revertJob
            Receive-Job -Job $revertJob -AutoRemoveJob -Wait
            exit 1
        }

        # Stop revert queue job.
        $revertJobRunning = $false
        Stop-Job -Job $revertJob
        Receive-Job -Job $revertJob -AutoRemoveJob -Wait

        # Clear progress.
        Write-Host -NoNewline "`r$(' ' * 50)`r"
        Write-Progress -Activity "Reverting changes in vault '$($vault.name)'" -Completed
        Write-Host "`n$($global:Green)🎉 Changes reverted successfully!$($global:Reset)"
        exit 0
    } elseif ($confirm.ToLower() -eq 'y') {
        $changesConfirmed = $true
    } elseif ($confirm.ToLower() -ne 'n') {
        Write-Host "$($global:Red)😕 Enter 'y', 'n', or 'revert'.$($global:Reset)"
    }
}

# Confirm completion.
Write-Host ""
Write-Host "$($global:Green)🎈 Website fields updated successfully. CSV saved at $fullCsvPath.$($global:Reset)"
Write-Host ""