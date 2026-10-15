@echo off
powershell -NoProfile -Command "$file = Join-Path ([Environment]::GetFolderPath('Startup')) 'ZanDop Workspace.lnk'; if (Test-Path -LiteralPath $file) { Remove-Item -LiteralPath $file }"
echo ZanDop auto-start shortcut removed. A running workspace is not stopped.
pause
