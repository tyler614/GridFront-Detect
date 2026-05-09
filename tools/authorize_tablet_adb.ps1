param(
    [string]$TabletHost = "192.168.68.62",
    [int]$ScoutPort = 8080,
    [string]$Adb = "C:\Users\helve\platform-tools\adb.exe",
    [string]$Pubkey = "C:\Users\helve\.android\adbkey.pub"
)

if (-not (Test-Path -LiteralPath $Pubkey)) {
    throw "ADB public key not found at $Pubkey"
}
if (-not (Test-Path -LiteralPath $Adb)) {
    throw "adb not found at $Adb"
}

$key = (Get-Content -LiteralPath $Pubkey -Raw).Trim()
$uri = "http://$TabletHost`:$ScoutPort/api/debug/adb-key"
$body = @{ pubkey = $key } | ConvertTo-Json -Compress

Write-Host "Posting ADB public key to $uri"
$response = Invoke-RestMethod -Method Post -Uri $uri -ContentType "application/json" -Body $body -TimeoutSec 10
$response | ConvertTo-Json -Compress

Start-Sleep -Seconds 2
& $Adb connect "$TabletHost`:5555"
& $Adb devices -l
