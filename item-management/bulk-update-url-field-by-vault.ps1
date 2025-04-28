# Script to update website fields for all items in a 1Password vault.
# Allows selecting a vault, setting a new URL, retrying if needed, or reverting changes.

# Define ANSI color codes as global variables (for compatibility).
$global:Cyan = "`e[96m"
$global:Yellow = "`e[93m"
$global:Red = "`e[91m"
$global:Green = "`e[92m"
$global:Reset = "`e[0m"

# Displays a table in a styled ASCII box with column separators.
function Show-TableInBox {
    param (
        [Parameter(Mandatory=$true)]
        [PSObject[]]$Data
    )

    # Define column headers.
    $itemIdHeader = "ItemID"
    $itemTitleHeader = "ItemTitle"
    $oldWebsiteHeader = "OldWebsite"
    $newWebsiteHeader = "NewWebsite"
    $errorHeader = "Error"

    # Truncate long strings to ensure alignment.
    $maxDisplayLengths = @{
        "ItemID" = 26
        "ItemTitle" = 20
        "OldWebsite" = 30
        "NewWebsite" = 30
        "Error" = 50  # Truncate long error messages
    }

    # Calculate maximum length for each column, respecting maxDisplayLengths.
    $itemIdMaxLength = [math]::Min([math]::Max(($Data | ForEach-Object { ($_.ItemID ?? "").Length } | Measure-Object -Maximum).Maximum, $itemIdHeader.Length), $maxDisplayLengths["ItemID"])
    $itemTitleMaxLength = [math]::Min([math]::Max(($Data | ForEach-Object { ($_.ItemTitle ?? "").Length } | Measure-Object -Maximum).Maximum, $itemTitleHeader.Length), $maxDisplayLengths["ItemTitle"])
    $oldWebsiteMaxLength = [math]::Min([math]::Max(($Data | ForEach-Object { ($_.OldWebsite ?? "").Length } | Measure-Object -Maximum).Maximum, $oldWebsiteHeader.Length), $maxDisplayLengths["OldWebsite"])
    $newWebsiteMaxLength = [math]::Min([math]::Max(($Data | ForEach-Object { ($_.NewWebsite ?? "").Length } | Measure-Object -Maximum).Maximum, $newWebsiteHeader.Length), $maxDisplayLengths["NewWebsite"])
    $errorMaxLength = [math]::Min([math]::Max(($Data | ForEach-Object { (($_.Error ?? "").ToString().Substring(0, [math]::Min(($_.Error ?? "").ToString().Length, $maxDisplayLengths["Error"]))) } | Measure-Object -Maximum).Maximum, $errorHeader.Length), $maxDisplayLengths["Error"])

    # Add padding for readability and ensure minimum widths.
    $itemIdMaxLength = [math]::Max($itemIdMaxLength + 2, $itemIdHeader.Length + 2)
    $itemTitleMaxLength = [math]::Max($itemTitleMaxLength + 2, $itemTitleHeader.Length + 2)
    $oldWebsiteMaxLength = [math]::Max($oldWebsiteMaxLength + 2, $oldWebsiteHeader.Length + 2)
    $newWebsiteMaxLength = [math]::Max($newWebsiteMaxLength + 2, $newWebsiteHeader.Length + 2)
    $errorMaxLength = [math]::Max($errorMaxLength + 2, $errorHeader.Length + 2)

    # Build the box borders.
    $topBorder = "┌" + ("─" * $itemIdMaxLength) + "┬" + ("─" * $itemTitleMaxLength) + "┬" + ("─" * $oldWebsiteMaxLength) + "┬" + ("─" * $newWebsiteMaxLength) + "┬" + ("─" * $errorMaxLength) + "┐"
    $headerRow = "│ " + $itemIdHeader.PadRight($itemIdMaxLength - 2) + " │ " + $itemTitleHeader.PadRight($itemTitleMaxLength - 2) + " │ " + $oldWebsiteHeader.PadRight($oldWebsiteMaxLength - 2) + " │ " + $newWebsiteHeader.PadRight($newWebsiteMaxLength - 2) + " │ " + $errorHeader.PadRight($errorMaxLength - 2) + " │"
    $midBorder = "├" + ("─" * $itemIdMaxLength) + "┼" + ("─" * $itemTitleMaxLength) + "┼" + ("─" * $oldWebsiteMaxLength) + "┼" + ("─" * $newWebsiteMaxLength) + "┼" + ("─" * $errorMaxLength) + "┤"
    $bottomBorder = "└" + ("─" * $itemIdMaxLength) + "┴" + ("─" * $itemTitleMaxLength) + "┴" + ("─" * $oldWebsiteMaxLength) + "┴" + ("─" * $newWebsiteMaxLength) + "┴" + ("─" * $errorMaxLength) + "┘"

    # Output the box.
    Write-Host $topBorder -ForegroundColor Cyan
    Write-Host $headerRow -ForegroundColor Cyan
    Write-Host $midBorder -ForegroundColor Cyan
    foreach ($item in $Data) {
        $itemId = ($item.ItemID ?? "").Substring(0, [math]::Min(($item.ItemID ?? "").Length, $maxDisplayLengths["ItemID"])).PadRight($itemIdMaxLength - 2)
        $itemTitle = ($item.ItemTitle ?? "").Substring(0, [math]::Min(($item.ItemTitle ?? "").Length, $maxDisplayLengths["ItemTitle"])).PadRight($itemTitleMaxLength - 2)
        $oldWebsite = ($item.OldWebsite ?? "").Substring(0, [math]::Min(($item.OldWebsite ?? "").Length, $maxDisplayLengths["OldWebsite"])).PadRight($oldWebsiteMaxLength - 2)
        $newWebsite = ($item.NewWebsite ?? "").Substring(0, [math]::Min(($item.NewWebsite ?? "").Length, $maxDisplayLengths["NewWebsite"])).PadRight($newWebsiteMaxLength - 2)
        $error = ($item.Error ?? "").ToString().Substring(0, [math]::Min(($item.Error ?? "").ToString().Length, $maxDisplayLengths["Error"])).PadRight($errorMaxLength - 2)
        Write-Host "│ $itemId │ $itemTitle │ $oldWebsite │ $newWebsite │ $error │" -ForegroundColor White
    }
    Write-Host $bottomBorder -ForegroundColor Cyan
}

# Executes a 1Password CLI command and returns the output and error.
function Invoke-OpCommand {
    param (
        [Parameter(Mandatory=$true)]
        [string[]]$Arguments
    )
    try {
        $result = op $Arguments 2>&1 | Out-String
        if ($LASTEXITCODE -ne 0) {
            throw $result
        }
        return $result, $null
    } catch {
        return $null, $_.ToString()
    }
}

# Check if user is signed into 1Password CLI and attempt sign-in if not.
function Check-OpAuth {
    $stdout, $stderr = Invoke-OpCommand -Arguments @("user", "list")
    if ($stdout) {
        Write-Host "`n$($global:Green)✅ Already authenticated with 1Password CLI.$($global:Reset)" -ForegroundColor Green
        return $true
    }
    Write-Host "`n$($global:Yellow)🔐 Looks like we need to authenticate with 1Password CLI.$($global:Reset)" -ForegroundColor Yellow
    Write-Host -NoNewline "$($global:Yellow)➡️ Account shorthand (e.g., 'myaccount' for 'myaccount.1password.com'): $($global:Reset)" -ForegroundColor Yellow
    $accountShorthand = Read-Host
    Write-Host ""
    if (-not $accountShorthand) {
        Write-Host "$($global:Red)😕 Account shorthand cannot be empty. Exiting.$($global:Reset)" -ForegroundColor Red
        return $false
    }
    try {
        $stdout, $stderr = Invoke-OpCommand -Arguments @("signin", "--account", $accountShorthand, "--raw")
        if ($stderr) {
            throw $stderr
        }
        $sessionToken = $stdout.Trim()
        [System.Environment]::SetEnvironmentVariable("OP_SESSION_$accountShorthand", $sessionToken, [System.EnvironmentVariableTarget]::Process)
        Write-Host "`n$($global:Green)✅ Successfully authenticated with 1Password CLI.$($global:Reset)" -ForegroundColor Green
        return $true
    } catch {
        Write-Host "$($global:Red)😕 Failed to authenticate with 1Password CLI: $_$($global:Reset)" -ForegroundColor Red
        return $false
    }
}

# Global variables for queue and background job control.
$editQueue = [System.Collections.Concurrent.ConcurrentQueue[PSObject]]::new()
$editJobRunning = $true
$editErrors = @{}
$editErrorsLock = New-Object System.Threading.Mutex

# Background job to process edit queue with 0.5-second gaps and up to 2 concurrent edits.
$editJob = Start-Job -ScriptBlock {
    param($queue, $errors, $errorsLock)
    $semaphore = 2  # Allow up to 2 concurrent edits
    $activeEdits = 0
    while ($global:editJobRunning -or $queue.Count -gt 0) {
        if ($activeEdits -lt $semaphore -and $queue.TryDequeue([ref]$item)) {
            $activeEdits++
            Start-Job -ScriptBlock {
                param($itemId, $url, $errors, $errorsLock)
                try {
                    $result = op item edit $itemId website=$url 2>&1 | Out-String
                    if ($LASTEXITCODE -ne 0) {
                        throw $result
                    }
                } catch {
                    $errorsLock.WaitOne()
                    $errors[$itemId] = $_
                    $errorsLock.ReleaseMutex()
                }
            } -ArgumentList $item.ItemID, $item.NewWebsite, $errors, $errorsLock | Out-Null
            Start-Sleep -Milliseconds 500  # 0.5-second gap
        } else {
            Start-Sleep -Milliseconds 100  # Wait briefly if queue is empty or semaphore is full
        }
        # Clean up completed jobs.
        Get-Job | Where-Object { $_.State -eq "Completed" } | ForEach-Object {
            Receive-Job -Job $_ -AutoRemoveJob
            $activeEdits--
        }
    }
} -ArgumentList $editQueue, $editErrors, $editErrorsLock

# Verify authentication before proceeding.
if (-not (Check-OpAuth)) {
    $global:editJobRunning = $false
    Stop-Job -Job $editJob
    Receive-Job -Job $editJob -AutoRemoveJob -Wait
    exit 1
}

# Prompt the user to select a vault.
Write-Host "`n$($global:Cyan)🚀 Starting website field update process...$($global:Reset)"
$vault = $null
$showListPrompt = $true
while (-not $vault) {
    Write-Host ""
    if ($showListPrompt) {
        Write-Host "Type the name or UUID of the vault, or press Enter to list all vaults:"
    } else {
        Write-Host "Type the name or UUID of the vault:"
    }
    Write-Host -NoNewline "$($global:Yellow)➡️ Enter your choice: $($global:Reset)"
    $vaultInput = Read-Host

    # Exit if the user types 'quit' or 'exit'.
    if ($vaultInput.ToLower() -eq 'quit' -or $vaultInput.ToLower() -eq 'exit') {
        Write-Host "`n$($global:Yellow)🚫 Exiting the script.$($global:Reset)"
        Write-Host ""
        $global:editJobRunning = $false
        Stop-Job -Job $editJob
        Receive-Job -Job $editJob -AutoRemoveJob -Wait
        exit
    }

    # Display the list of vaults if the user presses Enter or types 'list'.
    if (-not $vaultInput -or $vaultInput.ToLower() -eq 'list') {
        Write-Host "`n$($global:Cyan)📋 Available vaults:$($global:Reset)"
        try {
            $vaults = Invoke-OpCommand -Arguments @("vault", "list", "--format=json") | Select-Object -First 1 | ConvertFrom-Json
            $vaults | ForEach-Object { Write-Host "  - $($_.name) (ID: $($_.id))" }
        } catch {
            Write-Host "`n$($global:Red)😕 Failed to list vaults: $_$($global:Reset)" -ForegroundColor Red
        }
        $showListPrompt = $false
        continue
    }

    # Check if the input matches a vault name or UUID.
    try {
        $vault = (Invoke-OpCommand -Arguments @("vault", "list", "--format=json") | Select-Object -First 1 | ConvertFrom-Json) | Where-Object { $_.name -eq $vaultInput -or $_.id -eq $vaultInput }
        if (-not $vault) {
            Write-Host "`n$($global:Red)😕 Couldn't find a vault with name or UUID '$vaultInput'. Try again or press Enter to list all vaults!$($global:Reset)" -ForegroundColor Red
            $showListPrompt = $false
        }
    } catch {
        Write-Host "`n$($global:Red)😕 Failed to retrieve vaults: $_$($global:Reset)" -ForegroundColor Red
        $showListPrompt = $false
    }
}

# Confirm the selected vault with the user.
$vaultConfirmed = $false
while (-not $vaultConfirmed) {
    Write-Host ""
    Write-Host "You picked the vault '$($vault.name)' (ID: $($vault.id)). Confirm? (Y/n)"
    Write-Host -NoNewline "$($global:Yellow)➡️ Enter your choice: $($global:Reset)"
    $confirmVault = Read-Host

    # Default to 'y' if Enter is pressed.
    if (-not $confirmVault) { $confirmVault = 'y' }

    if ($confirmVault.ToLower() -eq 'y') {
        $vaultConfirmed = $true
    } elseif ($confirmVault.ToLower() -eq 'n') {
        $vault = $null
        $showListPrompt = $true
        while (-not $vault) {
            Write-Host ""
            if ($showListPrompt) {
                Write-Host "Type the name or UUID of the vault, or press Enter to list all vaults:"
            } else {
                Write-Host "Type the name or UUID of the vault:"
            }
            Write-Host -NoNewline "$($global:Yellow)➡️ Enter your choice: $($global:Reset)"
            $vaultInput = Read-Host

            # Exit if the user types 'quit' or 'exit'.
            if ($vaultInput.ToLower() -eq 'quit' -or $vaultInput.ToLower() -eq 'exit') {
                Write-Host "`n$($global:Yellow)🚫 Exiting the script.$($global:Reset)"
                Write-Host ""
                $global:editJobRunning = $false
                Stop-Job -Job $editJob
                Receive-Job -Job $editJob -AutoRemoveJob -Wait
                exit
            }

            # Display the list of vaults if the user presses Enter or types 'list'.
            if (-not $vaultInput -or $vaultInput.ToLower() -eq 'list') {
                Write-Host "`n$($global:Cyan)📋 Available vaults:$($global:Reset)"
                try {
                    $vaults = Invoke-OpCommand -Arguments @("vault", "list", "--format=json") | Select-Object -First 1 | ConvertFrom-Json
                    $vaults | ForEach-Object { Write-Host "  - $($_.name) (ID: $($_.id))" }
                } catch {
                    Write-Host "`n$($global:Red)😕 Failed to list vaults: $_$($global:Reset)" -ForegroundColor Red
                }
                $showListPrompt = $false
                continue
            }

            # Check if the input matches a vault name or UUID.
            try {
                $vault = (Invoke-OpCommand -Arguments @("vault", "list", "--format=json") | Select-Object -First 1 | ConvertFrom-Json) | Where-Object { $_.name -eq $vaultInput -or $_.id -eq $vaultInput }
                if (-not $vault) {
                    Write-Host "`n$($global:Red)😕 Couldn't find a vault with name or UUID '$vaultInput'. Try again or press Enter to list all vaults!$($global:Reset)" -ForegroundColor Red
                    $showListPrompt = $false
                }
            } catch {
                Write-Host "`n$($global:Red)😕 Failed to retrieve vaults: $_$($global:Reset)" -ForegroundColor Red
                $showListPrompt = $false
            }
        }
    } else {
        Write-Host "`n$($global:Red)😕 Please enter 'y' or 'n'!$($global:Reset)" -ForegroundColor Red
    }
}

# Prompt for and update the website URL until confirmed.
$confirmed = $false
while (-not $confirmed) {
    # Get the new URL.
    $newURL = ""
    while (-not $newURL) {
        Write-Host ""
        Write-Host "🌐 What's the new website URL you want to set? (e.g., https://example.com)"
        Write-Host -NoNewline "$($global:Yellow)➡️ Enter the URL: $($global:Reset)"
        $newURL = Read-Host
        if (-not $newURL) {
            Write-Host "`n$($global:Red)😕 Please provide a URL to continue!$($global:Reset)" -ForegroundColor Red
        }
    }

    # Confirm the entered URL.
    $urlConfirmed = $false
    while (-not $urlConfirmed) {
        Write-Host ""
        Write-Host "You entered '$($newURL)'. Confirm? (Y/n)"
        Write-Host -NoNewline "$($global:Yellow)➡️ Enter your choice: $($global:Reset)"
        $confirmURL = Read-Host
        if (-not $confirmURL) { $confirmURL = 'y' }
        if ($confirmURL.ToLower() -eq 'y') {
            $urlConfirmed = $true
        } elseif ($confirmURL.ToLower() -eq 'n') {
            $newURL = ""
            while (-not $newURL) {
                Write-Host ""
                Write-Host "🌐 What's the new website URL you want to set? (e.g., https://example.com)"
                Write-Host -NoNewline "$($global:Yellow)➡️ Enter the URL: $($global:Reset)"
                $newURL = Read-Host
                if (-not $newURL) {
                    Write-Host "`n$($global:Red)😕 Please provide a URL to continue!$($global:Reset)" -ForegroundColor Red
                }
            }
        } else {
            Write-Host "`n$($global:Red)😕 Please enter 'y' or 'n'!$($global:Reset)" -ForegroundColor Red
        }
    }

    # Retrieve items from the selected vault.
    try {
        $items = Invoke-OpCommand -Arguments @("item", "list", "--vault", $vault.id, "--format=json") | Select-Object -First 1 | ConvertFrom-Json
        if (-not $items) {
            Write-Host "`n$($global:Yellow)😕 No items found in vault '$($vault.name)'. Nothing to update!$($global:Reset)" -ForegroundColor Yellow
            Write-Host ""
            $global:editJobRunning = $false
            Stop-Job -Job $editJob
            Receive-Job -Job $editJob -AutoRemoveJob -Wait
            exit
        }
    } catch {
        Write-Host "`n$($global:Red)😕 Failed to retrieve items: $_$($global:Reset)" -ForegroundColor Red
        $global:editJobRunning = $false
        Stop-Job -Job $editJob
        Receive-Job -Job $editJob -AutoRemoveJob -Wait
        exit
    }

    # Initialize a thread-safe collection for tracking changes.
    $changes = New-Object System.Collections.Concurrent.ConcurrentBag[object]

    # Define a hash table for color variables to pass to the parallel script block.
    $colorVars = @{
        Cyan = $global:Cyan
        Yellow = $global:Yellow
        Red = $global:Red
        Green = $global:Green
        Reset = $global:Reset
    }

    # Define the parallel processing script block.
    $parallelScriptBlock = {
        param($item)
        # Access variables from the parent scope using $using:
        $changesBag = $using:changes
        $newURL = $using:newURL
        $globalColors = $using:colorVars

        function Invoke-OpCommand {
            param (
                [Parameter(Mandatory=$true)]
                [string[]]$Arguments
            )
            try {
                $result = op $Arguments 2>&1 | Out-String
                if ($LASTEXITCODE -ne 0) {
                    throw $result
                }
                return $result, $null
            } catch {
                return $null, $_.ToString()
            }
        }

        $errorMessage = ""
        try {
            $itemDetails = Invoke-OpCommand -Arguments @("item", "get", $item.id) | Select-Object -First 1
            if (-not $itemDetails) {
                throw "No output from op item get"
            }

            # Parse the URLs section to extract the primary URL.
            $currentWebsite = ""
            $inUrlsSection = $false
            foreach ($line in ($itemDetails -split "`n")) {
                if ($line -match "^URLs:") {
                    $inUrlsSection = $true
                    continue
                }
                if ($inUrlsSection -and $line -match "^:.*\(primary\)") {
                    $currentWebsite = ($line -replace "^:\s*" -replace "\s*\(primary\)$").Trim()
                    break
                }
                if ($inUrlsSection -and $line -notmatch "^\s*:") {
                    break
                }
            }

            # Queue the edit command for processing.
            ($using:editQueue).Enqueue([PSCustomObject]@{
                ItemID = $item.id
                NewWebsite = $newURL
            })
        } catch {
            $errorMessage = "Failed to retrieve item details: $_"
            Write-Host "$($globalColors.Red)😕 Error retrieving item $($item.id) ($($item.title)): $_$($globalColors.Reset)" -ForegroundColor Red
        }

        # Add minimal delay to avoid overwhelming the queue.
        Start-Sleep -Milliseconds 500

        # Add the change to the thread-safe collection (updated later with edit errors).
        $changesBag.Add([PSCustomObject]@{
            ItemID = $item.id
            ItemTitle = $item.title
            OldWebsite = $currentWebsite
            NewWebsite = if ($errorMessage) { "" } else { $newURL }
            Error = $errorMessage
        })
    }

    # Update each item’s website field using multi-threading (3 threads).
    Write-Host ""
    Write-Host "$($global:Cyan)🔧 Updating website fields for $($items.Count) items...$($global:Reset)"
    $completedItems = 0
    $spinnerChars = @('|', '/', '-', '\')
    $spinnerIndex = 0
    $items | ForEach-Object -Parallel $parallelScriptBlock -ThrottleLimit 3

    # Display progress and spinner while threads complete.
    while ($completedItems -lt $items.Count) {
        if ($changes.Count -gt $completedItems) {
            $completedItems = $changes.Count
            $percentComplete = ($completedItems / $items.Count) * 100
            Write-Progress -Activity "Updating items in vault '$($using:vault.name)'" -Status "Item $completedItems of $($items.Count)" -PercentComplete $percentComplete
        }
        Write-Host -NoNewline "`rProcessing items ($completedItems of $($items.Count)) $($spinnerChars[$spinnerIndex % 4])" -ForegroundColor Yellow
        $spinnerIndex++
        Start-Sleep -Milliseconds 100
    }

    # Wait for the edit queue to be processed.
    while ($editQueue.Count -gt 0) {
        Start-Sleep -Milliseconds 100
    }

    # Stop the edit queue background job.
    $global:editJobRunning = $false
    Stop-Job -Job $editJob
    Receive-Job -Job $editJob -AutoRemoveJob -Wait

    # Update changes with edit errors.
    $changesArray = $changes.ToArray()
    foreach ($change in $changesArray) {
        if ($editErrors.ContainsKey($change.ItemID)) {
            $change.Error = $editErrors[$change.ItemID]
            $change.NewWebsite = ""
        }
    }

    # Clear the spinner and progress bar.
    Write-Host -NoNewline "`r$(' ' * "Processing items ($completedItems of $($items.Count)) |".Length)`r"
    Write-Progress -Activity "Updating items in vault '$($vault.name)'" -Completed

    # Save changes to a CSV file.
    $csvPath = "website_changes_$($vault.name)_$(Get-Date -Format 'yyyyMMdd_HHmmss').csv"
    $changesArray | Export-Csv -Path $csvPath -NoTypeInformation
    $fullCsvPath = (Resolve-Path -Path $csvPath).Path

    # Display changes and confirm with the user.
    $changesConfirmed = $false
    while (-not $changesConfirmed) {
        Write-Host ""
        Write-Host "$($global:Cyan)📊 Update complete!$($global:Reset)"
        if ($changesArray.Count -eq 0) {
            Write-Host "$($global:Yellow)😕 No items were updated in the vault.$($global:Reset)" -ForegroundColor Yellow
        } else {
            Show-TableInBox -Data $changesArray
            Write-Host ""
            Write-Host "$($global:Cyan)Here’s what we changed (saved to $fullCsvPath):$($global:Reset)"
            Write-Host ""
        }
        Write-Host "Review the output or CSV. Confirm changes? (Y/n/revert)"
        Write-Host ""
        Write-Host -NoNewline "$($global:Yellow)➡️ Enter your choice: $($global:Reset)"
        $confirmChanges = Read-Host

        # Default to 'y' if Enter is pressed.
        if (-not $confirmChanges) { $confirmChanges = 'y' }

        if ($confirmChanges.ToLower() -eq 'revert') {
            Write-Host ""
            Write-Host "$($global:Yellow)🔄 Reverting changes...$($global:Reset)" -ForegroundColor Yellow
            $completedItems = 0

            # Start a new edit queue background job for revert.
            $revertQueue = [System.Collections.Concurrent.ConcurrentQueue[PSObject]]::new()
            $revertErrors = @{}
            $revertErrorsLock = New-Object System.Threading.Mutex
            $revertJobRunning = $true
            $revertJob = Start-Job -ScriptBlock {
                param($queue, $errors, $errorsLock)
                $semaphore = 2
                $activeEdits = 0
                while ($global:revertJobRunning -or $queue.Count -gt 0) {
                    if ($activeEdits -lt $semaphore -and $queue.TryDequeue([ref]$item)) {
                        $activeEdits++
                        Start-Job -ScriptBlock {
                            param($itemId, $url, $errors, $errorsLock)
                            try {
                                $result = op item edit $itemId website=$url 2>&1 | Out-String
                                if ($LASTEXITCODE -ne 0) {
                                    throw $result
                                }
                            } catch {
                                $errorsLock.WaitOne()
                                $errors[$itemId] = $_
                                $errorsLock.ReleaseMutex()
                            }
                        } -ArgumentList $item.ItemID, $item.OldWebsite, $errors, $errorsLock | Out-Null
                        Start-Sleep -Milliseconds 500
                    } else {
                        Start-Sleep -Milliseconds 100
                    }
                    Get-Job | Where-Object { $_.State -eq "Completed" } | ForEach-Object {
                        Receive-Job -Job $_ -AutoRemoveJob
                        $activeEdits--
                    }
                }
            } -ArgumentList $revertQueue, $revertErrors, $revertErrorsLock

            # Queue revert commands.
            $changesArray | ForEach-Object -Parallel {
                $change = $_
                if ($change.NewWebsite) {
                    ($using:revertQueue).Enqueue([PSCustomObject]@{
                        ItemID = $change.ItemID
                        OldWebsite = if ($change.OldWebsite) { $change.OldWebsite } else { "" }
                    })
                } else {
                    Write-Host "$($using:global:Yellow)😕 Skipping revert for item $($change.ItemID): Update failed$($using:global:Reset)" -ForegroundColor Yellow
                }
                Start-Sleep -Milliseconds 500
            } -ThrottleLimit 3

            # Display progress and spinner for revert.
            while ($completedItems -lt $changesArray.Count) {
                $completedItems = $changesArray.Count
                $percentComplete = ($completedItems / $changesArray.Count) * 100
                Write-Progress -Activity "Reverting changes in vault '$($vault.name)'" -Status "Item $completedItems of $($changesArray.Count)" -PercentComplete $percentComplete
                Write-Host -NoNewline "`rReverting items ($completedItems of $($changesArray.Count)) $($spinnerChars[$spinnerIndex % 4])" -ForegroundColor Yellow
                $spinnerIndex++
                Start-Sleep -Milliseconds 100
            }

            # Wait for the revert queue to be processed.
            while ($revertQueue.Count -gt 0) {
                Start-Sleep -Milliseconds 100
            }

            # Stop the revert queue background job.
            $global:revertJobRunning = $false
            Stop-Job -Job $revertJob
            Receive-Job -Job $revertJob -AutoRemoveJob -Wait

            # Clear the spinner and progress bar.
            Write-Host -NoNewline "`r$(' ' * "Reverting items ($completedItems of $($changesArray.Count)) |".Length)`r"
            Write-Progress -Activity "Reverting changes in vault '$($vault.name)'" -Completed
            Write-Host "`n$($global:Green)🎉 Changes reverted successfully!$($global:Reset)" -ForegroundColor Green
            Write-Host ""
            exit
        } elseif ($confirmChanges.ToLower() -eq 'y') {
            $changesConfirmed = $true
            $confirmed = $true
        } elseif ($confirmChanges.ToLower() -eq 'n') {
            Write-Host ""
            Write-Host "$($global:Yellow)😕 Not satisfied? Let's try a different URL!$($global:Reset)" -ForegroundColor Yellow
            break
        } else {
            Write-Host "`n$($global:Red)😕 Please enter 'y', 'n', or 'revert'!$($global:Reset)" -ForegroundColor Red
        }
    }
}

# Confirm successful completion.
Write-Host ""
Write-Host "$($global:Green)🎈 Website fields updated successfully. CSV saved at $fullCsvPath.$($global:Reset)" -ForegroundColor Green
Write-Host ""