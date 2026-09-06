param(
    [string]$BackupDirectory = 'C:\Users\serha\Documents\Trade1-Backup',
    [string]$Python = ''
)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
if (-not $Python) { $Python = Join-Path $projectRoot '.venv\Scripts\pythonw.exe' }
$pythonPath = (Resolve-Path -LiteralPath $Python).Path
$verifierPath = (Resolve-Path -LiteralPath (Join-Path $projectRoot 'backup_verify.py')).Path
$backupPath = (Resolve-Path -LiteralPath $BackupDirectory).Path
$statusPath = Join-Path $projectRoot '.pc_backup_status.json'
# No credentials, network port, service account, or background visible window.
$arguments = '-B "{0}" "{1}" --status-file "{2}"' -f $verifierPath, $backupPath, $statusPath
$action = New-ScheduledTaskAction -Execute $pythonPath -Argument $arguments -WorkingDirectory $projectRoot
$trigger = New-ScheduledTaskTrigger -Daily -At '12:45'
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew
Register-ScheduledTask -TaskName 'Trade1 PC Backup Verify' -Action $action -Trigger $trigger -Settings $settings -Description 'Daily local backup receipt, SHA-256, JSON and disk checks. Does not start trading or modify backups.' -Force | Select-Object TaskName, State
Start-ScheduledTask -TaskName 'Trade1 PC Backup Verify'
