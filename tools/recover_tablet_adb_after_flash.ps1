param(
    [string]$TabletHost = "192.168.68.62",
    [string]$Adb = "C:\Users\helve\platform-tools\adb.exe",
    [string]$Apk = "C:\Users\helve\detect.gridfront.io\android\app\build\outputs\apk\debug\app-debug.apk",
    [int]$ScoutPort = 8080,
    [int]$WaitSeconds = 180
)

if (-not (Test-Path -LiteralPath $Adb)) {
    throw "adb not found at $Adb"
}
if (-not (Test-Path -LiteralPath $Apk)) {
    throw "APK not found at $Apk. Build it first with android\gradlew.bat assembleDebug."
}

function Wait-AdbDevice {
    param([int]$Seconds)

    $deadline = (Get-Date).AddSeconds($Seconds)
    do {
        & $Adb connect "$TabletHost`:5555" | Out-Host
        $devices = & $Adb devices
        $line = $devices | Where-Object { $_ -match "^($TabletHost`:5555|RT3Pro000014458)\s+device\b" } | Select-Object -First 1
        if ($line) {
            return $true
        }
        Start-Sleep -Seconds 3
    } while ((Get-Date) -lt $deadline)

    return $false
}

function Wait-ScoutEndpoint {
    param([int]$Seconds)

    $deadline = (Get-Date).AddSeconds($Seconds)
    $uri = "http://$TabletHost`:$ScoutPort/api/debug/adb-key"
    do {
        try {
            $response = Invoke-WebRequest -UseBasicParsing -Method Post -Uri $uri -ContentType "text/plain" -Body "probe" -TimeoutSec 4
            if ($response.StatusCode -ne 503) {
                return $true
            }
        } catch {
            if ($_.Exception.Response -and [int]$_.Exception.Response.StatusCode -ne 503) {
                return $true
            }
        }
        Start-Sleep -Seconds 3
    } while ((Get-Date) -lt $deadline)

    return $false
}

Write-Host "Waiting for insecure ADB on $TabletHost`:5555..."
if (-not (Wait-AdbDevice -Seconds $WaitSeconds)) {
    throw "ADB did not become available as an authenticated device."
}

Write-Host "Installing $Apk"
& $Adb install -r -d -g $Apk
if ($LASTEXITCODE -ne 0) {
    throw "adb install failed with exit code $LASTEXITCODE"
}

Write-Host "Rebooting tablet so BootReceiver and the new local server come up cleanly..."
& $Adb reboot
Start-Sleep -Seconds 8

Write-Host "Waiting for tablet to return..."
if (-not (Wait-AdbDevice -Seconds $WaitSeconds)) {
    throw "Tablet did not return on ADB after APK install reboot."
}

Write-Host "Waiting for new Scout /api/debug/adb-key endpoint..."
if (-not (Wait-ScoutEndpoint -Seconds $WaitSeconds)) {
    throw "Scout endpoint did not become available."
}

& "$PSScriptRoot\authorize_tablet_adb.ps1" -TabletHost $TabletHost -ScoutPort $ScoutPort -Adb $Adb
