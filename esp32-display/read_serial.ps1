param([string]$PortName = "COM9", [int]$Seconds = 10)
$port = New-Object System.IO.Ports.SerialPort $PortName,115200,None,8,one
$port.ReadTimeout = 500
$port.DtrEnable = $false
$port.RtsEnable = $false
try {
    $port.Open()
    # Pulse DTR/RTS to reset ESP32-S3 native USB CDC and capture from boot.
    $port.DtrEnable = $true
    $port.RtsEnable = $true
    Start-Sleep -Milliseconds 100
    $port.DtrEnable = $false
    Start-Sleep -Milliseconds 50
    $port.RtsEnable = $false
    Start-Sleep -Milliseconds 500
    $buf = ""
    $end = (Get-Date).AddSeconds($Seconds)
    while ((Get-Date) -lt $end) {
        try { $buf += $port.ReadExisting() } catch {}
        Start-Sleep -Milliseconds 150
    }
    Write-Host "=== SERIAL OUTPUT ($($buf.Length) bytes) ==="
    Write-Host $buf
    Write-Host "=== END ==="
} catch {
    Write-Host ("ERR: " + $_.Exception.Message)
} finally {
    if ($port.IsOpen) { $port.Close() }
}
