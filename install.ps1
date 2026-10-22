# Transfer installer for Windows:  irm https://raw.githubusercontent.com/sharmashivesh6/transfer/main/install.ps1 | iex
# Downloading from PowerShell (not a browser) skips the SmartScreen prompt; the firewall rule skips the "Allow access" prompt.
$ErrorActionPreference = 'Stop'
$dir = "$env:LOCALAPPDATA\Programs\Transfer"
$exe = "$dir\Transfer.exe"

Write-Host "Downloading Transfer..."
New-Item -ItemType Directory -Force $dir | Out-Null
Get-Process Transfer -ErrorAction SilentlyContinue | Stop-Process -Force  # replace a running copy
$ProgressPreference = 'SilentlyContinue'  # the progress bar makes Invoke-WebRequest very slow
Invoke-WebRequest https://github.com/sharmashivesh6/transfer/releases/latest/download/Transfer.exe -OutFile $exe

$shell = New-Object -ComObject WScript.Shell
foreach ($lnk in "$env:APPDATA\Microsoft\Windows\Start Menu\Programs\Transfer.lnk", "$([Environment]::GetFolderPath('Desktop'))\Transfer.lnk") {
    $s = $shell.CreateShortcut($lnk); $s.TargetPath = $exe; $s.Save()
}

Write-Host "Allowing Transfer through the firewall (click Yes on the next prompt)..."
# Profile Any: Windows marks many home Wi-Fi networks "Public", and Transfer only listens while it's open
$quoted = $exe.Replace("'", "''")
$rule = "Remove-NetFirewallRule -DisplayName 'Transfer' -ErrorAction SilentlyContinue; " +
        "New-NetFirewallRule -DisplayName 'Transfer' -Direction Inbound -Program '$quoted' -Action Allow -Profile Any | Out-Null"
try { Start-Process powershell -Verb RunAs -Wait -WindowStyle Hidden -ArgumentList '-NoProfile', '-Command', $rule }
catch { Write-Warning "Skipped. Windows will ask you to allow Transfer the first time it opens." }

Start-Process $exe
Write-Host "Done. Transfer is open, and it's in your Start menu and on your desktop."
