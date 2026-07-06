<#
GridFront Radius runner — Windows install.

Registers a Task Scheduler task that starts runner.py at logon AND at boot,
restarts it if it dies, and disables sleep/hibernate on AC (training runs
for days). Run from an ELEVATED PowerShell.

Usage:
    .\install_runner.ps1                       # venv python auto-detected
    .\install_runner.ps1 -PythonExe C:\path\to\python.exe
    .\install_runner.ps1 -Uninstall
#>
param(
    [string]$PythonExe = "",
    [string]$TaskName = "GridFront Radius Runner",
    [switch]$Uninstall
)
$ErrorActionPreference = "Stop"
$RunnerDir = Split-Path -Parent $MyInvocation.MyCommand.Path

$IsAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()
    ).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $IsAdmin) {
    Write-Host "Run this from an elevated PowerShell (Task Scheduler registration needs it)." -ForegroundColor Red
    exit 1
}

if ($Uninstall) {
    Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Host "Removed scheduled task '$TaskName'. (Kill any running python runner.py manually.)"
    exit 0
}

# ── python: default to the training venv one directory up ────────────────
if (-not $PythonExe) {
    $venvPy = Join-Path (Split-Path -Parent $RunnerDir) ".venv\Scripts\python.exe"
    if (Test-Path $venvPy) {
        $PythonExe = $venvPy
    } else {
        Write-Host "No venv at $venvPy - do the HANDOVER.md Setup block first, or pass -PythonExe." -ForegroundColor Red
        exit 1
    }
}
Write-Host "Python: $PythonExe"
& $PythonExe --version

# ── config ───────────────────────────────────────────────────────────────
$ConfigPath = Join-Path $RunnerDir "runner.toml"
if (-not (Test-Path $ConfigPath)) {
    Copy-Item (Join-Path $RunnerDir "runner.toml.example") $ConfigPath
    Write-Host "Created runner.toml from the example." -ForegroundColor Yellow
    Write-Host "EDIT IT (platform_url, token, runner_id), then re-run this script." -ForegroundColor Yellow
    exit 1
}
& $PythonExe (Join-Path $RunnerDir "runner.py") --check-config
if ($LASTEXITCODE -ne 0) {
    Write-Host "runner.toml failed validation - fix it and re-run." -ForegroundColor Red
    exit 1
}

# ── never sleep on AC: a 40h training run must not be interrupted ────────
powercfg /change standby-timeout-ac 0
powercfg /change hibernate-timeout-ac 0
Write-Host "Power: standby + hibernate on AC disabled."

# ── scheduled task: at logon + at boot, restart on failure ───────────────
$action = New-ScheduledTaskAction -Execute $PythonExe `
    -Argument ('"{0}"' -f (Join-Path $RunnerDir "runner.py")) `
    -WorkingDirectory $RunnerDir
$triggers = @((New-ScheduledTaskTrigger -AtLogOn), (New-ScheduledTaskTrigger -AtStartup))
$settings = New-ScheduledTaskSettingsSet `
    -RestartCount 9999 -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType S4U -RunLevel Limited

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $triggers `
    -Settings $settings -Principal $principal -Force | Out-Null
Start-ScheduledTask -TaskName $TaskName
Write-Host ""
Write-Host "Installed + started scheduled task '$TaskName'." -ForegroundColor Green
Write-Host ""
Write-Host "Operate it:"
Write-Host "  watch the daemon:   Get-Content -Wait '$RunnerDir\logs\runner.log'"
Write-Host "  watch a job:        Get-Content -Wait '$RunnerDir\logs\<job_id>.log'"
Write-Host "  stop:               Stop-ScheduledTask -TaskName '$TaskName'"
Write-Host "  start:              Start-ScheduledTask -TaskName '$TaskName'"
Write-Host "  status:             Get-ScheduledTask -TaskName '$TaskName' | Get-ScheduledTaskInfo"
Write-Host "  uninstall:          .\install_runner.ps1 -Uninstall"
Write-Host "  debug (foreground): & '$PythonExe' '$RunnerDir\runner.py' --once"
Write-Host ""
Write-Host "Jobs are queued FROM THE PLATFORM (platform.gridfront.io). The manual"
Write-Host "downloads in ..\HANDOVER.md Step 1 are still required before the first job."
