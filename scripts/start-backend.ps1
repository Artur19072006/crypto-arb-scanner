$ProjectRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
$BackendDir = Join-Path $ProjectRoot "backend"
$PythonPath = Join-Path $BackendDir ".venv\Scripts\python.exe"
$EnvPath = Join-Path $ProjectRoot ".env"

function Import-LocalEnv {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path
    )

    if (-not (Test-Path -LiteralPath $Path)) {
        return
    }

    foreach ($RawLine in Get-Content -LiteralPath $Path) {
        $Line = $RawLine.Trim()

        if ($Line.Length -eq 0 -or $Line.StartsWith("#")) {
            continue
        }

        if ($Line.StartsWith("export ")) {
            $Line = $Line.Substring(7).Trim()
        }

        $SeparatorIndex = $Line.IndexOf("=")
        if ($SeparatorIndex -le 0) {
            continue
        }

        $Name = $Line.Substring(0, $SeparatorIndex).Trim()
        if ($Name -notmatch "^[A-Za-z_][A-Za-z0-9_]*$") {
            continue
        }

        $Value = $Line.Substring($SeparatorIndex + 1).Trim()
        if (
            ($Value.StartsWith('"') -and $Value.EndsWith('"')) -or
            ($Value.StartsWith("'") -and $Value.EndsWith("'"))
        ) {
            $Value = $Value.Substring(1, $Value.Length - 2)
        }

        Set-Item -Path "Env:$Name" -Value $Value
    }
}

if (-not (Test-Path -LiteralPath $PythonPath)) {
    Write-Error "Backend virtualenv Python was not found at backend\.venv\Scripts\python.exe. Create it and install backend requirements first."
    exit 1
}

Import-LocalEnv -Path $EnvPath

Set-Location -LiteralPath $BackendDir
& $PythonPath -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
