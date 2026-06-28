param(
    [string]$Image = "C:\Users\helve\magisk_patched_boot_b_adb_insecure.img",
    [ValidateSet("boot_a", "boot_b")]
    [string]$Partition = "boot_b",
    [string]$MtkClientDir = "/home/helve/mtkclient",
    [string]$WslDistro = "Ubuntu-24.04",
    [string]$Watcher = "C:\Users\helve\brom_attach_only.ps1",
    [switch]$RestoreNormalBoot
)

if ($RestoreNormalBoot) {
    $Image = "C:\Users\helve\magisk_patched_boot_b.img"
}

if (-not (Test-Path -LiteralPath $Image)) {
    throw "Boot image not found: $Image"
}
if (-not (Test-Path -LiteralPath $Watcher)) {
    throw "BROM watcher not found: $Watcher"
}

$resolved = (Resolve-Path -LiteralPath $Image).Path
$linuxImage = $resolved -replace '^C:\\', '/mnt/c/' -replace '\\', '/'
$action = if ($RestoreNormalBoot) { "RESTORE normal Magisk boot image" } else { "FLASH temporary insecure-ADB boot image" }
$log = "C:\Users\helve\mtk_flash_boot_b_$(Get-Date -Format yyyyMMdd_HHmmss).log"

Write-Host "Action: $action"
Write-Host "Part:   $Partition"
Write-Host "Image:  $resolved"
Write-Host "Log:    $log"
Write-Host ""
Write-Host "When the two helper windows are open:"
Write-Host "  1. Power the tablet fully off."
Write-Host "  2. Hold Vol-Up + Vol-Down."
Write-Host "  3. Plug in USB-C and keep holding for at least 15 seconds."
Write-Host ""

$outLog = $log -replace "\.log$", ".out.log"
$errLog = $log -replace "\.log$", ".err.log"
$wslArgs = @(
    "-d", $WslDistro,
    "-u", "root",
    "--cd", $MtkClientDir,
    "--",
    "python3", "mtk.py", "w", $Partition, $linuxImage
)

Start-Process -FilePath "wsl.exe" -ArgumentList $wslArgs -RedirectStandardOutput $outLog -RedirectStandardError $errLog
Start-Sleep -Seconds 1
Start-Process -FilePath "powershell.exe" -ArgumentList @(
    "-NoExit",
    "-ExecutionPolicy", "Bypass",
    "-File", $Watcher
) -WindowStyle Normal

Write-Host "Started mtk.py writer and BROM attach watcher."
Write-Host "Output: $outLog"
Write-Host "Errors: $errLog"
Write-Host "This script is now done; the flash finishes in the helper windows."
