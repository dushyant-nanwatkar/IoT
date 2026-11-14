<#
.SYNOPSIS
    Sentinel AI - Autonomous Edge Doorbell Host Server Launcher

.DESCRIPTION
    Boots the Sentinel Core system (Port 9000 SBMP server, ADB tunnel healer,
    RTX 5060 AI pipeline, and FastAPI Web Dashboard on Port 8000).
    Also supports running the Android mock phone client or both simultaneously.

.PARAMETER Mock
    Runs only the mock phone simulator (test_mock_phone.py).

.PARAMETER Both
    Launches Sentinel Core in this window and spawns the Mock Phone simulator
    in a secondary terminal window for an immediate end-to-end demo.

.PARAMETER NoBrowser
    Prevents automatically opening http://localhost:8000 in your default web browser.

.PARAMETER Install
    Installs/updates Python dependencies from requirements.txt before launching.

.PARAMETER KillPort
    Forces termination of any stale processes occupying ports 8000 or 9000.

.PARAMETER Help
    Displays usage instructions and options.

.EXAMPLE
    .\start.ps1
    Starts Sentinel Core and opens the Homeowner Dashboard in your browser.

.EXAMPLE
    .\start.ps1 -Both
    Starts Sentinel Core and launches the Mock Phone simulator in another window.

.EXAMPLE
    .\start.ps1 -Mock
    Runs the mock Android doorbell phone simulator.
#>

param(
    [switch]$Mock,
    [switch]$Both,
    [switch]$NoBrowser,
    [switch]$Install,
    [switch]$KillPort,
    [switch]$Help
)

$ErrorActionPreference = "Stop"

# Show Help if requested
if ($Help) {
    Write-Host ""
    Write-Host "======================================================================" -ForegroundColor Cyan
    Write-Host "   SENTINEL AI - Autonomous Edge Doorbell System Launcher" -ForegroundColor White
    Write-Host "======================================================================" -ForegroundColor Cyan
    Write-Host "Usage:" -ForegroundColor Yellow
    Write-Host "  .\start.ps1              Start Sentinel Core & open web dashboard"
    Write-Host "  .\start.ps1 -Both        Start Sentinel Core + Mock Phone Simulator"
    Write-Host "  .\start.ps1 -Mock        Run only the Mock Phone client"
    Write-Host "  .\start.ps1 -NoBrowser   Start Sentinel Core without opening browser"
    Write-Host "  .\start.ps1 -Install     Install requirements.txt in virtualenv"
    Write-Host "  .\start.ps1 -KillPort    Cleanly terminate stale processes on 8000/9000"
    Write-Host "  .\start.ps1 -Help        Show this help screen"
    Write-Host ""
    exit 0
}

# 1. Resolve Project Paths
$ScriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Definition
if (-not $ScriptRoot) {
    $ScriptRoot = $PSScriptRoot
}
if (-not $ScriptRoot) {
    $ScriptRoot = (Get-Location).Path
}

$ProjectRoot = $ScriptRoot
$CoreDir = Join-Path $ProjectRoot "sentinel-laptop-core"

# Check if script is executed from inside sentinel-laptop-core directory
if (-not (Test-Path $CoreDir) -and (Test-Path (Join-Path $ProjectRoot "run_sentinel.py"))) {
    $CoreDir = $ProjectRoot
    $ProjectRoot = Split-Path -Parent $CoreDir
}

if (-not (Test-Path $CoreDir)) {
    Write-Host "[ERROR] Could not locate 'sentinel-laptop-core' directory at: $CoreDir" -ForegroundColor Red
    exit 1
}

# 2. Locate Python Virtual Environment or System Python
$VenvPythonCandidates = @(
    (Join-Path $CoreDir ".venv\Scripts\python.exe"),
    (Join-Path $ProjectRoot ".venv\Scripts\python.exe")
)

$PythonExe = $null
foreach ($candidate in $VenvPythonCandidates) {
    if (Test-Path $candidate) {
        $PythonExe = (Resolve-Path $candidate).Path
        break
    }
}

if (-not $PythonExe) {
    $sysPython = (Get-Command python -ErrorAction SilentlyContinue).Source
    if ($sysPython) {
        $PythonExe = $sysPython
    } else {
        $pyLauncher = (Get-Command py -ErrorAction SilentlyContinue).Source
        if ($pyLauncher) {
            $PythonExe = $pyLauncher
        }
    }
}

if (-not $PythonExe) {
    Write-Host ""
    Write-Host "[ERROR] Python interpreter not found!" -ForegroundColor Red
    Write-Host "Please install Python 3.10+ or set up the virtual environment:" -ForegroundColor Yellow
    Write-Host "  cd '$CoreDir'" -ForegroundColor Gray
    Write-Host "  python -m venv .venv" -ForegroundColor Gray
    Write-Host "  .\.venv\Scripts\pip install -r requirements.txt" -ForegroundColor Gray
    Write-Host ""
    exit 1
}

# Get Python Version
$PyVer = & $PythonExe --version 2>&1

# 3. Banner
Write-Host ""
Write-Host "================================================================================" -ForegroundColor Cyan
Write-Host "   SENTINEL AI - Autonomous Edge Doorbell System" -ForegroundColor White
Write-Host "================================================================================" -ForegroundColor Cyan
Write-Host " [Workspace Root] $ProjectRoot" -ForegroundColor DarkGray
Write-Host " [Core Directory] $CoreDir" -ForegroundColor DarkGray
Write-Host " [Python Engine]  $PythonExe ($PyVer)" -ForegroundColor DarkGray
Write-Host " [FastAPI Server] http://localhost:8000" -ForegroundColor Green
Write-Host " [SBMP Protocol]  TCP Port 9000 (Demuxer & H.264)" -ForegroundColor Green
Write-Host "================================================================================" -ForegroundColor Cyan
Write-Host ""

# 4. Optional: Install Dependencies
if ($Install) {
    $ReqFile = Join-Path $CoreDir "requirements.txt"
    if (Test-Path $ReqFile) {
        Write-Host "[SETUP] Installing Python dependencies from requirements.txt..." -ForegroundColor Cyan
        & $PythonExe -m pip install -r $ReqFile
        if ($LASTEXITCODE -ne 0) {
            Write-Host "[WARNING] pip install completed with warnings or errors." -ForegroundColor Yellow
        } else {
            Write-Host "[SETUP] Dependencies successfully verified." -ForegroundColor Green
        }
        Write-Host ""
    }
}

# 5. Check and Clear Ports 8000 and 9000
function Test-PortListening([int]$Port) {
    $res = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
    return ($null -ne $res)
}

function Clear-PortOccupants([int]$Port) {
    $connections = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
    foreach ($conn in $connections) {
        $pidToKill = $conn.OwningProcess
        if ($pidToKill -and $pidToKill -ne $PID) {
            $pName = (Get-Process -Id $pidToKill -ErrorAction SilentlyContinue).ProcessName
            Write-Host "  -> Clearing stale listener on port $Port (PID $($pidToKill): $pName)..." -ForegroundColor Yellow
            Stop-Process -Id $pidToKill -Force -ErrorAction SilentlyContinue
        }
    }
}

if ($KillPort) {
    Write-Host "[CLEANUP] Checking and freeing ports 8000 and 9000..." -ForegroundColor Cyan
    Clear-PortOccupants 8000
    Clear-PortOccupants 9000
    Write-Host "[CLEANUP] Ports 8000 and 9000 are clear." -ForegroundColor Green
    if (-not $Mock -and -not $Both) {
        exit 0
    }
}

if (-not $Mock) {
    $port8000Busy = Test-PortListening 8000
    $port9000Busy = Test-PortListening 9000

    if ($port8000Busy -or $port9000Busy) {
        Write-Host "[INFO] Detected existing process holding port 8000 or 9000." -ForegroundColor Cyan
        if ($port8000Busy) { Clear-PortOccupants 8000 }
        if ($port9000Busy) { Clear-PortOccupants 9000 }
        Start-Sleep -Milliseconds 600
    }
}

# 6. Mode Execution

# Mode A: Mock phone simulator only
if ($Mock) {
    Write-Host "[START] Launching Mock Android Doorbell Phone Simulator..." -ForegroundColor Cyan
    Write-Host "        Connecting to SBMP server on localhost:9000..." -ForegroundColor DarkGray
    Write-Host "        (Press Ctrl+C to terminate)" -ForegroundColor DarkGray
    Write-Host ""
    Set-Location $CoreDir
    & $PythonExe test_mock_phone.py
    exit $LASTEXITCODE
}

# Mode B: Both Sentinel Core and Mock Phone Simulator
if ($Both) {
    Write-Host "[START] Launching Mock Phone Simulator in a secondary terminal window..." -ForegroundColor Cyan
    
    # Formulate command for secondary window with delayed start (gives core 3 seconds to boot)
    $MockScript = Join-Path $CoreDir "test_mock_phone.py"
    $MockCmd = @"
`$host.UI.RawUI.WindowTitle = 'Sentinel - Mock Android Doorbell Phone'
Write-Host '=============================================================' -ForegroundColor Cyan
Write-Host '   SENTINEL AI - Simulated Android Doorbell Phone' -ForegroundColor White
Write-Host '=============================================================' -ForegroundColor Cyan
Write-Host 'Waiting 3 seconds for Sentinel Core server to initialize...' -ForegroundColor DarkGray
Start-Sleep -Seconds 3
Set-Location '$CoreDir'
& '$PythonExe' '$MockScript'
Write-Host ''
Write-Host 'Mock phone simulator has ended. Press Enter to close window.' -ForegroundColor Gray
Read-Host
"@
    $EncodedCmd = [Convert]::ToBase64String([System.Text.Encoding]::Unicode.GetBytes($MockCmd))
    Start-Process powershell.exe -ArgumentList "-NoProfile", "-EncodedCommand", $EncodedCmd
}

# Mode C: Sentinel Core Host Server (Default)
if (-not $NoBrowser) {
    # Launch browser after a brief delay so the server has bound port 8000
    Start-Process powershell.exe -WindowStyle Hidden -ArgumentList "-NoProfile", "-Command", "Start-Sleep -Milliseconds 2200; Start-Process 'http://localhost:8000'"
}

Write-Host "[START] Launching Sentinel Laptop Core Host Server..." -ForegroundColor Green
Write-Host "        Web Dashboard: http://localhost:8000/" -ForegroundColor Cyan
Write-Host "        Swagger Docs:  http://localhost:8000/docs" -ForegroundColor Cyan
Write-Host "        Press Ctrl+C to stop the server" -ForegroundColor DarkGray
Write-Host ""

Set-Location $CoreDir
& $PythonExe run_sentinel.py
