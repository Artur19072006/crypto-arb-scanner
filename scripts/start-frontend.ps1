$ProjectRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
$FrontendDir = Join-Path $ProjectRoot "frontend"

if (-not (Test-Path -LiteralPath $FrontendDir)) {
    Write-Error "Frontend directory was not found."
    exit 1
}

Set-Location -LiteralPath $FrontendDir
& npm.cmd run dev
