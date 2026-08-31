$scriptDir  = Split-Path -Parent $MyInvocation.MyCommand.Path
$target     = Join-Path $scriptDir "run.bat"
$shortcut   = Join-Path ([Environment]::GetFolderPath("Desktop")) "Nasdaq-Mood-Dashboard.lnk"

$ws = New-Object -ComObject WScript.Shell
$s  = $ws.CreateShortcut($shortcut)
$s.TargetPath       = $target
$s.WorkingDirectory = $scriptDir
$s.WindowStyle      = 1
$s.IconLocation     = "shell32.dll,13"
$s.Description      = "Nasdaq 100 Mood Dashboard"
$s.Save()

Write-Host "桌面快捷方式已创建: $shortcut" -ForegroundColor Green
Write-Host "Desktop shortcut created: $shortcut"
