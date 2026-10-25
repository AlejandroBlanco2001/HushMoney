#Requires -Version 5.1
<#
.SYNOPSIS
    HushMoney — local development launcher (Windows / Docker).

.DESCRIPTION
    PowerShell port of scripts/dev.sh for a Docker Desktop environment.

.EXAMPLE
    .\scripts\dev.ps1                 # start with OpenShell sandbox (default)
.EXAMPLE
    .\scripts\dev.ps1 -NoOpenShell    # plain docker compose (no sandboxing)
.EXAMPLE
    .\scripts\dev.ps1 -Down           # stop and remove everything
.EXAMPLE
    .\scripts\dev.ps1 -Logs           # tail logs from the running stack

.NOTES
    Prerequisites:
      - Docker Desktop running.
      - .env filled in:  Copy-Item .env.example .env ; notepad .env
      - The external volumes used by docker-compose.yml must exist
        (untyped_hermes-data, untyped_forwarder-data, untyped_pattern-inbox).
      - OpenShell mode additionally needs the `openshell` CLI on PATH; without it,
        use -NoOpenShell.
#>
[CmdletBinding()]
param(
    [switch]$NoOpenShell,
    [switch]$Down,
    [switch]$Logs
)

$ErrorActionPreference = 'Stop'

$RepoRoot    = Split-Path -Parent $PSScriptRoot
$EnvFile     = Join-Path $RepoRoot '.env'
$SandboxName = 'hushmoney-1'

# Windows has no `id -u`; the compose file defaults these to 1000 when unset.
if (-not $env:HERMES_UID) { $env:HERMES_UID = '1000' }
if (-not $env:HERMES_GID) { $env:HERMES_GID = '1000' }

# ── Logging helpers ──────────────────────────────────────────────────────────

function Write-Info  { param([string]$Message) Write-Host "[dev]  $Message"  -ForegroundColor Green }
function Write-Warn  { param([string]$Message) Write-Host "[warn] $Message"  -ForegroundColor Yellow }
function Stop-WithError {
    param([string]$Message)
    Write-Host "[error] $Message" -ForegroundColor Red
    exit 1
}

# ── Helpers ──────────────────────────────────────────────────────────────────

function Test-CommandExists {
    param([string]$Name)
    [bool](Get-Command $Name -ErrorAction SilentlyContinue)
}

function Invoke-Compose {
    # Run `docker compose` from the repo root (so it finds docker-compose.yml + .env).
    param([string[]]$ComposeArgs)
    Push-Location $RepoRoot
    try {
        & docker compose @ComposeArgs
    } finally {
        Pop-Location
    }
}

function Import-DotEnv {
    if (-not (Test-Path $EnvFile)) {
        Stop-WithError ".env not found. Run: Copy-Item .env.example .env ; notepad .env"
    }
    # Load KEY=VALUE pairs into the process environment so this script (and the
    # child processes it spawns) can read them. docker compose also reads .env on
    # its own, so this is mainly for the session check and the gen_session call.
    foreach ($line in Get-Content $EnvFile) {
        $trimmed = $line.Trim()
        if (-not $trimmed -or $trimmed.StartsWith('#') -or ($trimmed -notmatch '=')) { continue }
        $key, $value = $trimmed -split '=', 2
        $key = $key.Trim()
        $value = $value.Trim().Trim('"').Trim("'")
        if ($key) { Set-Item -Path "Env:$key" -Value $value }
    }
}

function Test-SandboxExists {
    if (-not (Test-CommandExists 'openshell')) { return $false }
    $list = openshell sandbox list 2>$null
    return [bool]($list | Select-String -SimpleMatch $SandboxName -Quiet)
}

# ── Down ─────────────────────────────────────────────────────────────────────

if ($Down) {
    Write-Info 'Stopping forwarder...'
    try { Invoke-Compose @('down') } catch { }

    if (Test-SandboxExists) {
        Write-Info 'Stopping OpenShell sandbox...'
        try { openshell sandbox delete $SandboxName 2>$null } catch { }
    }

    Write-Info 'Done.'
    exit 0
}

# ── Logs ─────────────────────────────────────────────────────────────────────

if ($Logs) {
    $jobs = @()
    if (Test-SandboxExists) {
        Write-Info 'Hermes sandbox logs (ctrl-c to exit):'
        $jobs += Start-Job -Name hermes-logs -ScriptBlock {
            openshell logs $using:SandboxName --tail
        }
    } else {
        $jobs += Start-Job -Name hermes-logs -ScriptBlock {
            Set-Location $using:RepoRoot; docker compose logs -f hermes
        }
    }

    $jobs += Start-Job -Name forwarder-logs -ScriptBlock {
        Set-Location $using:RepoRoot; docker compose logs -f forwarder
    }

    try {
        while ($true) {
            $jobs | ForEach-Object { Receive-Job $_ }
            Start-Sleep -Milliseconds 500
        }
    } finally {
        # Reached on Ctrl-C.
        $jobs | Stop-Job -ErrorAction SilentlyContinue
        $jobs | Remove-Job -Force -ErrorAction SilentlyContinue
    }
    exit 0
}

# ── Up ───────────────────────────────────────────────────────────────────────

Import-DotEnv

# ── Telegram session ──────────────────────────────────────────────────────────

if (-not $env:TELEGRAM_SESSION_STRING) {
    Write-Info 'No TELEGRAM_SESSION_STRING found — generating one now.'
    Write-Info 'You will be prompted for your phone number and a Telegram OTP.'
    if (-not (Test-CommandExists 'uv')) {
        Stop-WithError "uv not found on PATH. Install it from https://docs.astral.sh/uv/ to generate the Telegram session."
    }
    uv run --python cpython-3.12 --with pyrogram --with python-dotenv `
        python (Join-Path $RepoRoot 'scripts\gen_session.py') $EnvFile
    if ($LASTEXITCODE -ne 0) { Stop-WithError 'Telegram session generation failed.' }
    Import-DotEnv
}

# ── Plain mode (-NoOpenShell) ──────────────────────────────────────────────────

if ($NoOpenShell) {
    Write-Info 'Starting stack without OpenShell sandbox...'
    Invoke-Compose @('up', '-d', '--build')
    if ($LASTEXITCODE -ne 0) { Stop-WithError 'docker compose up failed.' }
    Write-Info 'Stack running. Logs: .\scripts\dev.ps1 -Logs'
    exit 0
}

# ── OpenShell mode (default) ───────────────────────────────────────────────────

if (-not (Test-CommandExists 'openshell')) {
    Stop-WithError 'openshell CLI not found on PATH. Re-run with -NoOpenShell to use plain docker compose.'
}

# Connect to gateway if not already done
openshell sandbox list *> $null
if ($LASTEXITCODE -ne 0) {
    Write-Info 'Connecting to OpenShell gateway...'
    try { openshell gateway add https://127.0.0.1:8080 --local --gateway-insecure 2>$null } catch { }
    try { openshell gateway select openshell 2>$null } catch { }
}

# Create sandbox — reuse if already running
if (Test-SandboxExists) {
    Write-Info "Sandbox $SandboxName already exists — reusing it."
} else {
    Write-Info "Creating sandbox $SandboxName..."
    $policy = Join-Path $RepoRoot 'config\openshell\policy.yaml'
    Start-Process -FilePath 'openshell' -NoNewWindow -ArgumentList @(
        'sandbox', 'create',
        '--from', 'ghcr.io/alejandroblanco2001/untyped:latest',
        '--name', $SandboxName,
        '--policy', $policy,
        '--provider', 'nebius',
        '--', '/app/docker-entrypoint.sh'
    )
    Write-Info 'Hermes sandbox starting in background.'
}

# Start forwarder — Hermes runs in the OpenShell sandbox on port 8080
Write-Info 'Starting forwarder...'
Invoke-Compose @('up', '-d', '--no-deps', 'forwarder')
if ($LASTEXITCODE -ne 0) { Stop-WithError 'docker compose up (forwarder) failed.' }

# ── Done ───────────────────────────────────────────────────────────────────────

Write-Host ''
Write-Info 'Stack running.'
Write-Host ''
Write-Host '  Sandbox:  openshell sandbox list'
Write-Host '  Logs:     .\scripts\dev.ps1 -Logs'
Write-Host '  Stop:     .\scripts\dev.ps1 -Down'
Write-Host ''
Write-Host '  Test (PowerShell):'
Write-Host '    $headers = @{ Authorization = "Bearer $env:HERMES_GATEWAY_SECRET" }'
Write-Host '    $body = ''{"transaction_type":"debit","amount":45000,"currency":"COP","merchant":"RAPPI","channel":"email"}'''
Write-Host '    Invoke-RestMethod -Method Post -Uri http://localhost:8081/gateway -Headers $headers -ContentType ''application/json'' -Body $body'
Write-Host ''
