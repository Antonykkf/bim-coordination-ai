# Connect this repo to GitHub so another laptop can clone it.
param(
    [Parameter(Mandatory = $true)]
    [string]$RemoteUrl
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $ProjectRoot

if (-not (Test-Path ".git")) {
    throw "This folder is not a git repository."
}

$branch = git branch --show-current
if (-not $branch) {
    git checkout -b main
    $branch = "main"
}

if ($branch -eq "master") {
    git branch -M main
    $branch = "main"
}

$remotes = @(git remote)
if ($remotes -contains "origin") {
    $existing = git remote get-url origin
    Write-Host "Updating origin from $existing to $RemoteUrl"
    git remote set-url origin $RemoteUrl
} else {
    Write-Host "Adding origin remote: $RemoteUrl"
    git remote add origin $RemoteUrl
}

Write-Host "Pushing $branch to origin..."
git push -u origin $branch

Write-Host ""
Write-Host "GitHub remote connected."
Write-Host "On your other laptop:"
Write-Host "  git clone $RemoteUrl"
Write-Host "  cd bim-coordination-ai"
Write-Host "  cursor ."
