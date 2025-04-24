# Script to update website fields for all items in a 1Password vault.
# Allows selecting a vault, setting a new URL, retrying if needed, or reverting changes.

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

    # Calculate maximum length for each column.
    $itemIdMaxLength = [math]::Max(($Data | ForEach-Object { $_.ItemID.Length } | Measure-Object -Maximum).Maximum, $itemIdHeader.Length)
    $itemTitleMaxLength = [math]::Max(($Data | ForEach-Object { $_.ItemTitle.Length } | Measure-Object -Maximum).Maximum, $itemTitleHeader.Length)
    $oldWebsiteMaxLength = [math]::Max(($Data | ForEach-Object { $_.OldWebsite.Length } | Measure-Object -Maximum).Maximum, $oldWebsiteHeader.Length)
    $newWebsiteMaxLength = [math]::Max(($Data | ForEach-Object { $_.NewWebsite.Length } | Measure-Object -Maximum).Maximum, $newWebsiteHeader.Length)

    # Add padding for readability.
    $itemIdMaxLength += 2
    $itemTitleMaxLength += 2
    $oldWebsiteMaxLength += 2
    $newWebsiteMaxLength += 2

    # Build the box borders.
    $topBorder = "┌" + ("─" * $itemIdMaxLength) + "┬" + ("─" * $itemTitleMaxLength) + "┬" + ("─" * $oldWebsiteMaxLength) + "┬" + ("─" * $newWebsiteMaxLength) + "┐"
    $headerRow = "│ " + $itemIdHeader.PadRight($itemIdMaxLength - 2) + " │ " + $itemTitleHeader.PadRight($itemTitleMaxLength - 2) + " │ " + $oldWebsiteHeader.PadRight($oldWebsiteMaxLength - 2) + " │ " + $newWebsiteHeader.PadRight($newWebsiteMaxLength - 2) + " │"
    $midBorder = "├" + ("─" * $itemIdMaxLength) + "┼" + ("─" * $itemTitleMaxLength) + "┼" + ("─" * $oldWebsiteMaxLength) + "┼" + ("─" * $newWebsiteMaxLength) + "┤"
    $bottomBorder = "└" + ("─" * $itemIdMaxLength) + "┴" + ("─" * $itemTitleMaxLength) + "┴" + ("─" * $oldWebsiteMaxLength) + "┴" + ("─" * $newWebsiteMaxLength) + "┘"

    # Output the box.
    Write-Host $topBorder -ForegroundColor Cyan
    Write-Host $headerRow -ForegroundColor Cyan
    Write-Host $midBorder -ForegroundColor Cyan
    foreach ($item in $Data) {
        $itemId = $item.ItemID.PadRight($itemIdMaxLength - 2)
        $itemTitle = $item.ItemTitle.PadRight($itemTitleMaxLength - 2)
        $oldWebsite = $item.OldWebsite.PadRight($oldWebsiteMaxLength - 2)
        $newWebsite = $item.NewWebsite.PadRight($newWebsiteMaxLength - 2)
        Write-Host "│ $itemId │ $itemTitle │ $oldWebsite │ $newWebsite │" -ForegroundColor White
    }
    Write-Host $bottomBorder -ForegroundColor Cyan
}

# Prompt the user to select a vault.
Write-Host "`n🚀 Starting website field update process..." -ForegroundColor Cyan
$vault = $null
$showListPrompt = $true
while (-not $vault) {
    Write-Host ""
    if ($showListPrompt) {
        Write-Host "Type the name or UUID of the vault, or press Enter to list all vaults:"
    } else {
        Write-Host "Type the name or UUID of the vault:"
    }
    Write-Host -NoNewline "➡️ Enter your choice: " -ForegroundColor Yellow
    $vaultInput = Read-Host

    # Exit if the user types 'quit' or 'exit'.
    if ($vaultInput.ToLower() -eq 'quit' -or $vaultInput.ToLower() -eq 'exit') {
        Write-Host "`n🚫 Exiting the script." -ForegroundColor Yellow
        Write-Host ""
        exit
    }

    # Display the list of vaults if the user presses Enter or types 'list'.
    if (-not $vaultInput -or $vaultInput.ToLower() -eq 'list') {
        Write-Host "`n📋 Available vaults:" -ForegroundColor Cyan
        $vaults = op vault list --format=json | ConvertFrom-Json
        $vaults | ForEach-Object { Write-Host "  - $($_.name) (ID: $($_.id))" }
        $showListPrompt = $false
        continue
    }

    # Check if the input matches a vault name or UUID.
    $vault = op vault list --format=json | ConvertFrom-Json | Where-Object { $_.name -eq $vaultInput -or $_.id -eq $vaultInput }
    if (-not $vault) {
        Write-Host "`n😕 Couldn't find a vault with name or UUID '$vaultInput'. Try again or press Enter to list all vaults!" -ForegroundColor Red
        $showListPrompt = $false
    }
}

# Confirm the selected vault with the user.
$vaultConfirmed = $false
while (-not $vaultConfirmed) {
    Write-Host ""
    Write-Host "You picked the vault '$($vault.name)' (ID: $($vault.id)). Sound good? (y/n, Enter for y)"
    Write-Host -NoNewline "➡️ Enter your choice: " -ForegroundColor Yellow
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
            Write-Host -NoNewline "➡️ Enter your choice: " -ForegroundColor Yellow
            $vaultInput = Read-Host

            # Exit if the user types 'quit' or 'exit'.
            if ($vaultInput.ToLower() -eq 'quit' -or $vaultInput.ToLower() -eq 'exit') {
                Write-Host "`n🚫 Exiting the script." -ForegroundColor Yellow
                Write-Host ""
                exit
            }

            # Display the list of vaults if the user presses Enter or types 'list'.
            if (-not $vaultInput -or $vaultInput.ToLower() -eq 'list') {
                Write-Host "`n📋 Available vaults:" -ForegroundColor Cyan
                $vaults = op vault list --format=json | ConvertFrom-Json
                $vaults | ForEach-Object { Write-Host "  - $($_.name) (ID: $($_.id))" }
                $showListPrompt = $false
                continue
            }

            # Check if the input matches a vault name or UUID.
            $vault = op vault list --format=json | ConvertFrom-Json | Where-Object { $_.name -eq $vaultInput -or $_.id -eq $vaultInput }
            if (-not $vault) {
                Write-Host "`n😕 Couldn't find a vault with name or UUID '$vaultInput'. Try again or press Enter to list all vaults!" -ForegroundColor Red
                $showListPrompt = $false
            }
        }
    } else {
        Write-Host "`n😕 Please enter 'y', 'n', or press Enter for 'y'!" -ForegroundColor Red
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
        Write-Host -NoNewline "➡️ Enter the URL: " -ForegroundColor Yellow
        $newURL = Read-Host
        if (-not $newURL) {
            Write-Host "`n😕 Please provide a URL to continue!" -ForegroundColor Red
        }
    }

    # Confirm the entered URL.
    $urlConfirmed = $false
    while (-not $urlConfirmed) {
        Write-Host ""
        Write-Host "You entered '$newURL'. Is that right? (y/n, Enter for y)"
        Write-Host -NoNewline "➡️ Enter your choice: " -ForegroundColor Yellow
        $confirmURL = Read-Host
        if (-not $confirmURL) { $confirmURL = 'y' }
        if ($confirmURL.ToLower() -eq 'y') {
            $urlConfirmed = $true
        } elseif ($confirmURL.ToLower() -eq 'n') {
            $newURL = ""
            while (-not $newURL) {
                Write-Host ""
                Write-Host "🌐 What's the new website URL you want to set? (e.g., https://example.com)"
                Write-Host -NoNewline "➡️ Enter the URL: " -ForegroundColor Yellow
                $newURL = Read-Host
                if (-not $newURL) {
                    Write-Host "`n😕 Please provide a URL to continue!" -ForegroundColor Red
                }
            }
        } else {
            Write-Host "`n😕 Please enter 'y', 'n', or press Enter for 'y'!" -ForegroundColor Red
        }
    }

    # Retrieve items from the selected vault.
    $items = op item list --vault $vault.id --format=json | ConvertFrom-Json
    if (-not $items) {
        Write-Host "`n😕 No items found in vault '$($vault.name)'. Nothing to update!" -ForegroundColor Yellow
        Write-Host ""
        exit
    }

    # Initialize a thread-safe collection for tracking changes.
    $changes = New-Object System.Collections.Concurrent.ConcurrentBag[object]

    # Update each item’s website field using multi-threading (3 threads).
    Write-Host ""
    Write-Host "🔧 Updating website fields for $($items.Count) items..." -ForegroundColor Cyan
    $completedItems = 0
    $spinnerChars = @('|', '/', '-', '\')
    $spinnerIndex = 0
    $items | ForEach-Object -Parallel {
        $item = $_
        $changesBag = $using:changes
        $newURL = $using:newURL

        # Retrieve item details in plain text.
        $itemDetails = op item get $item.id | Out-String

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

        # Update the item’s website field.
        op item edit $item.id website=$newURL | Out-Null

        # Add the change to the thread-safe collection.
        $changesBag.Add([PSCustomObject]@{
            ItemID = $item.id
            ItemTitle = $item.title
            OldWebsite = $currentWebsite
            NewWebsite = $newURL
        })
    } -ThrottleLimit 3

    # Display progress and spinner while threads complete.
    while ($completedItems -lt $items.Count) {
        if ($changes.Count -gt $completedItems) {
            $completedItems = $changes.Count
            $percentComplete = ($completedItems / $items.Count) * 100
            Write-Progress -Activity "Updating items in vault '$($vault.name)'" -Status "Item $completedItems of $($items.Count)" -PercentComplete $percentComplete
        }
        Write-Host -NoNewline "`rProcessing items ($completedItems of $($items.Count)) $($spinnerChars[$spinnerIndex % 4])" -ForegroundColor Yellow
        $spinnerIndex++
        Start-Sleep -Milliseconds 100
    }

    # Clear the spinner and progress bar.
    Write-Host -NoNewline "`r$(' ' * "Processing items ($completedItems of $($items.Count)) |".Length)`r"
    Write-Progress -Activity "Updating items in vault '$($vault.name)'" -Completed

    # Convert ConcurrentBag to array for further processing.
    $changesArray = $changes.ToArray()

    # Save changes to a CSV file.
    $csvPath = "website_changes_$($vault.name)_$(Get-Date -Format 'yyyyMMdd_HHmmss').csv"
    $changesArray | Export-Csv -Path $csvPath -NoTypeInformation
    $fullCsvPath = (Resolve-Path -Path $csvPath).Path

    # Display changes and confirm with the user.
    $changesConfirmed = $false
    while (-not $changesConfirmed) {
        Write-Host ""
        Write-Host "📊 Update complete!" -ForegroundColor Cyan
        if ($changesArray.Count -eq 0) {
            Write-Host "😕 No items were updated in the vault." -ForegroundColor Yellow
        } else {
            Show-TableInBox -Data $changesArray
            Write-Host ""
            Write-Host "Here’s what we changed (saved to $fullCsvPath):" -ForegroundColor Cyan
            Write-Host ""
        }
        Write-Host "Review the output or CSV. Happy with the changes? (y/n/revert, Enter for y)"
        Write-Host ""
        Write-Host -NoNewline "➡️ Enter your choice: " -ForegroundColor Yellow
        $confirmChanges = Read-Host

        # Default to 'y' if Enter is pressed.
        if (-not $confirmChanges) { $confirmChanges = 'y' }

        if ($confirmChanges.ToLower() -eq 'revert') {
            Write-Host ""
            Write-Host "🔄 Reverting changes..." -ForegroundColor Yellow
            $completedItems = 0

            # Revert changes using multi-threading (3 threads).
            $changesArray | ForEach-Object -Parallel {
                $change = $_
                if ($change.OldWebsite) {
                    op item edit $change.ItemID website=$($change.OldWebsite) | Out-Null
                } else {
                    op item edit $change.ItemID website="" | Out-Null
                }
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

            # Clear the spinner and progress bar.
            Write-Host -NoNewline "`r$(' ' * "Reverting items ($completedItems of $($changesArray.Count)) |".Length)`r"
            Write-Progress -Activity "Reverting changes in vault '$($vault.name)'" -Completed
            Write-Host "`n🎉 Changes reverted successfully!" -ForegroundColor Green
            Write-Host ""
            exit
        } elseif ($confirmChanges.ToLower() -eq 'y') {
            $changesConfirmed = $true
            $confirmed = $true
        } elseif ($confirmChanges.ToLower() -eq 'n') {
            Write-Host ""
            Write-Host "😕 Not satisfied? Let's try a different URL!" -ForegroundColor Yellow
            break
        } else {
            Write-Host "`n😕 Please enter 'y', 'n', 'revert', or press Enter for 'y'!" -ForegroundColor Red
        }
    }
}

# Confirm successful completion.
Write-Host ""
Write-Host "🎈 Website fields updated successfully. CSV saved at $fullCsvPath." -ForegroundColor Green
Write-Host ""