@echo off
setlocal
set "ZANDOP_LAUNCHER_PATH=%~dp0Start ZanDop Workspace.bat"
powershell -NoProfile -Command "$shell = New-Object -ComObject WScript.Shell; $folder = [Environment]::GetFolderPath('Startup'); $link = $shell.CreateShortcut((Join-Path $folder 'ZanDop Workspace.lnk')); $link.TargetPath = $env:ZANDOP_LAUNCHER_PATH; $link.WorkingDirectory = Split-Path $env:ZANDOP_LAUNCHER_PATH; $link.Save()"
if errorlevel 1 (
    echo Auto-start could not be enabled. Read the error above.
) else (
    echo ZanDop will open after you sign into Windows. Keep this folder in its current location.
    echo Your computer must stay awake and connected for replies to be sent.
)
pause
