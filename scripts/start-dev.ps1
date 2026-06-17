$ProjectRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
$BackendScript = Join-Path $PSScriptRoot "start-backend.ps1"
$FrontendScript = Join-Path $PSScriptRoot "start-frontend.ps1"

$BackendArgs = "-NoExit -ExecutionPolicy Bypass -File `"$BackendScript`""
$FrontendArgs = "-NoExit -ExecutionPolicy Bypass -File `"$FrontendScript`""

Start-Process -FilePath "powershell.exe" -ArgumentList $BackendArgs -WorkingDirectory $ProjectRoot
Start-Process -FilePath "powershell.exe" -ArgumentList $FrontendArgs -WorkingDirectory $ProjectRoot
