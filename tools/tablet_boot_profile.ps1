param(
    [string]$Adb = "C:\Users\helve\platform-tools\adb.exe",
    [string]$Serial = "192.168.68.62:5555",
    [int]$Seconds = 120,
    [string]$Out = ""
)

if (-not (Test-Path -LiteralPath $Adb)) {
    throw "adb not found at $Adb"
}

if (-not $Out) {
    $stamp = Get-Date -Format "yyyyMMdd-HHmmss"
    $Out = Join-Path $PSScriptRoot "..\temp\tablet-boot-$stamp.csv"
}

$outDir = Split-Path -Parent $Out
New-Item -ItemType Directory -Force $outDir | Out-Null

"host_time,elapsed_s,adb_state,sys_boot_completed,dev_bootcomplete,init_svc_bootanim,init_svc_adbd,activity_top" |
    Set-Content -LiteralPath $Out -Encoding ascii

$start = Get-Date
Write-Host "Writing $Out"

while (((Get-Date) - $start).TotalSeconds -lt $Seconds) {
    $now = Get-Date
    $elapsed = [math]::Round(($now - $start).TotalSeconds, 1)
    $hostTime = $now.ToString("o")

    $devices = & $Adb devices 2>$null
    $line = ($devices | Select-String ([regex]::Escape($Serial))).Line
    if (-not $line -and $Serial -match "^\d+\.\d+\.\d+\.\d+:") {
        $line = ($devices | Select-String "RT3Pro").Line
    }

    $adbState = "missing"
    if ($line -match "\sunauthorized\b") { $adbState = "unauthorized" }
    elseif ($line -match "\soffline\b") { $adbState = "offline" }
    elseif ($line -match "\sdevice\b") { $adbState = "device" }

    $sysBoot = ""
    $devBoot = ""
    $bootanim = ""
    $adbd = ""
    $top = ""

    if ($adbState -eq "device") {
        $sysBoot = (& $Adb -s $Serial shell getprop sys.boot_completed 2>$null).Trim()
        $devBoot = (& $Adb -s $Serial shell getprop dev.bootcomplete 2>$null).Trim()
        $bootanim = (& $Adb -s $Serial shell getprop init.svc.bootanim 2>$null).Trim()
        $adbd = (& $Adb -s $Serial shell getprop init.svc.adbd 2>$null).Trim()
        $top = (& $Adb -s $Serial shell dumpsys activity activities 2>$null |
            Select-String "mResumedActivity|topResumedActivity" |
            Select-Object -First 1).Line
        if ($top) { $top = $top.Trim().Replace(",", ";") }
    }

    "$hostTime,$elapsed,$adbState,$sysBoot,$devBoot,$bootanim,$adbd,""$top""" |
        Add-Content -LiteralPath $Out -Encoding ascii

    Write-Host ("{0,6}s {1,-12} boot={2} anim={3} top={4}" -f $elapsed, $adbState, $sysBoot, $bootanim, $top)
    Start-Sleep -Seconds 1
}

Write-Host "Done: $Out"
