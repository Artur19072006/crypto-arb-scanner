[CmdletBinding()]
param(
    [int[]]$Ports = @(8000, 5173, 5174)
)

foreach ($Port in $Ports) {
    if ($Port -lt 1 -or $Port -gt 65535) {
        Write-Warning "Skipping invalid port $Port"
        continue
    }

    try {
        $Connections = @(Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue)
    }
    catch {
        Write-Warning "Could not inspect port $Port`: $($_.Exception.Message)"
        continue
    }

    $ProcessIds = @(
        $Connections |
            Where-Object { $_.OwningProcess -and $_.OwningProcess -ne 0 } |
            Select-Object -ExpandProperty OwningProcess -Unique
    )

    if ($ProcessIds.Count -eq 0) {
        Write-Output "No process found on port $Port"
        continue
    }

    foreach ($ProcessId in $ProcessIds) {
        try {
            Get-Process -Id $ProcessId -ErrorAction Stop | Out-Null
            Stop-Process -Id $ProcessId -ErrorAction Stop
            Write-Output "Stopped process $ProcessId on port $Port"
        }
        catch {
            Write-Warning "Failed to stop process $ProcessId on port $Port`: $($_.Exception.Message)"
        }
    }
}
