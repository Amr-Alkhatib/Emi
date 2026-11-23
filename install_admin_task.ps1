# Runs elevated (started by install_shortcuts.ps1). Registers scheduled tasks that start Emi with
# administrator rights without a UAC pop-up each time.
param([string]$User, [switch]$Startup)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$pyw  = Join-Path $root ".venv\Scripts\pythonw.exe"
$main = Join-Path $root "main.py"
$exe  = Join-Path $root "Emi.exe"
if (Test-Path $exe) { $prog = $exe; $pre = "" } else { $prog = $pyw; $pre = "`"$main`" " }
try {
    $principal = New-ScheduledTaskPrincipal -UserId $User -LogonType Interactive -RunLevel Highest
    $settings  = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
                 -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew
    $summon = New-ScheduledTaskAction -Execute $prog -Argument "${pre}--summon" -WorkingDirectory $root
    Register-ScheduledTask -TaskName "Emi" -Action $summon -Principal $principal -Settings $settings -Force | Out-Null
    Unregister-ScheduledTask -TaskName "Emi startup" -Confirm:$false -ErrorAction SilentlyContinue
    if ($Startup) {
        $bg = New-ScheduledTaskAction -Execute $prog -Argument "${pre}--background" -WorkingDirectory $root
        $trigger = New-ScheduledTaskTrigger -AtLogOn -User $User
        Register-ScheduledTask -TaskName "Emi startup" -Action $bg -Trigger $trigger -Principal $principal `
            -Settings $settings -Force | Out-Null
    }
    New-Item -ItemType Directory -Force -Path (Join-Path $root "data") | Out-Null
    Set-Content -Path (Join-Path $root "data\admin_task") -Value "1"
    exit 0
} catch {
    Write-Host $_
    Start-Sleep -Seconds 5
    exit 1
}
