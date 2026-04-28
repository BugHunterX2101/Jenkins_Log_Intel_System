#!/usr/bin/env pwsh
# Quick-start script to launch ngrok with the project config
# Usage: .\start-ngrok.ps1

Write-Host "Jenkins Log Intelligence — ngrok tunnel launcher" -ForegroundColor Cyan
Write-Host ""

$configFile = Join-Path $PSScriptRoot "ngrok.yml"

if (-not (Test-Path $configFile)) {
    Write-Host "ERROR: ngrok.yml not found in project root" -ForegroundColor Red
    exit 1
}

$authToken = $env:NGROK_AUTH_TOKEN
if ($authToken) {
    Write-Host "Using NGROK_AUTH_TOKEN from environment" -ForegroundColor Green
}

Write-Host ""
Write-Host "Starting ngrok tunnels:" -ForegroundColor Cyan
Write-Host "  - api:     localhost:8000 → https://...ngrok-free.app"
Write-Host "  - jenkins: localhost:8080 → https://...ngrok-free.app"
Write-Host ""
Write-Host "Press Ctrl+C to stop the tunnels." -ForegroundColor Yellow
Write-Host ""

& ngrok start --config $configFile --all
