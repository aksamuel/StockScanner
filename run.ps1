param(
    [string[]]$Args
)

Set-Location $PSScriptRoot
if (-Not (Test-Path .venv\Scripts\Activate.ps1)) {
    Write-Error "Virtual environment .venv not found in $PWD. Run README_SETUP.md first."
    exit 1
}

Write-Host "Activating .venv and running stockscanner CLI..."
. .\.venv\Scripts\Activate.ps1
python -m stockscanner.cli @Args
