# Creates the "Emi" summon shortcut (works even when Emi isn't running), and optionally
# starts Emi with Windows and/or gives her administrator rights. Run via install_shortcuts.bat.
$ErrorActionPreference = "Stop"
$root   = Split-Path -Parent $MyInvocation.MyCommand.Path
$pyw    = Join-Path $root ".venv\Scripts\pythonw.exe"
$launch = Join-Path $root "launch.pyw"
$main   = Join-Path $root "main.py"
$icon   = Join-Path $root "emi.ico"
$exe    = Join-Path $root "Emi.exe"
if (Test-Path $exe) {            # packaged app (build_exe.bat)
    $target = $exe; $summonArgs = "--summon"; $bgArgs = "--background"
} elseif (Test-Path $pyw) {      # normal install (setup.bat)
    $target = $pyw; $summonArgs = "`"$launch`" summon"; $bgArgs = "`"$main`" --background"
} else {
    Write-Host " Emi isn't set up yet - run setup.bat first."; exit 1
}

Write-Host ""
Write-Host " Emi shortcuts"
Write-Host " -------------"
Write-Host " The summon shortcut starts Emi if she isn't running, or makes her listen if she is."
Write-Host " Use Ctrl+Alt+Shift or Ctrl+Shift plus a letter, number or F-key."
Write-Host " (Avoid Ctrl+Alt+E/Q/M/2/3/7/8/9/0 on German keyboards - those type symbols.)"
$hk = Read-Host " Summon shortcut [press Enter for Ctrl+Alt+Shift+E]"
if (-not $hk) { $hk = "Ctrl+Alt+Shift+E" }
$hk = $hk.Replace(" ", "")
if ($hk -notmatch '^((ctrl|alt|shift)\+){2,3}([a-z0-9]|f([1-9]|1[0-2]))$') {
    Write-Host " That doesn't look like a valid shortcut, using Ctrl+Alt+Shift+E."
    $hk = "Ctrl+Alt+Shift+E"
}
$startup = (Read-Host " Start Emi automatically when Windows starts? (y/N)") -match '^(y|yes|j|ja)$'
Write-Host ""
Write-Host " Administrator rights let Emi change system settings, install programs for all users and"
Write-Host " control admin windows - without UAC pop-ups. Only say yes if you trust what you ask her to do."
$admin = (Read-Host " Run Emi as administrator? (y/N)") -match '^(y|yes|j|ja)$'

$shell = New-Object -ComObject WScript.Shell
function New-Link([string]$path, [string]$arguments, [string]$hotkey) {
    $l = $shell.CreateShortcut($path)
    $l.TargetPath = $target
    $l.Arguments = $arguments
    $l.WorkingDirectory = $root
    if (Test-Path $icon) { $l.IconLocation = "$icon,0" }
    $l.Description = "Summon Emi"
    if ($hotkey) { $l.Hotkey = $hotkey }
    $l.Save()
}

# Start menu shortcut carries the hotkey (Windows only honours hotkeys on Start menu / Desktop shortcuts)
$programs = [Environment]::GetFolderPath("Programs")
New-Link (Join-Path $programs "Emi.lnk") $summonArgs $hk
New-Link (Join-Path ([Environment]::GetFolderPath("Desktop")) "Emi.lnk") $summonArgs ""
Write-Host " + Start menu and Desktop shortcut 'Emi' with hotkey $hk"

$startupLink = Join-Path ([Environment]::GetFolderPath("Startup")) "Emi.lnk"
if (Test-Path $startupLink) { Remove-Item $startupLink }

if ($admin) {
    $elevated = Join-Path $root "install_admin_task.ps1"
    $argList = @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", "`"$elevated`"", "-User", "`"$env:USERDOMAIN\$env:USERNAME`"")
    if ($startup) { $argList += "-Startup" }
    Write-Host " Windows will ask once for permission to set up the administrator task..."
    $ok = $false
    try {
        $p = Start-Process powershell -Verb RunAs -Wait -PassThru -ArgumentList $argList
        $ok = ($p.ExitCode -eq 0)
    } catch { $ok = $false }
    if ($ok) { Write-Host " + Emi will run as administrator" }
    else { Write-Host " ! Admin setup was cancelled or failed - Emi will run normally. Run this again to retry." }
} else {
    $marker = Join-Path $root "data\admin_task"
    if (Test-Path $marker) {
        Remove-Item $marker
        Write-Host " Removing the old administrator tasks (Windows will ask once)..."
        try {
            Start-Process powershell -Verb RunAs -Wait -ArgumentList @("-NoProfile", "-Command",
                "Unregister-ScheduledTask -TaskName 'Emi' -Confirm:`$false -ErrorAction SilentlyContinue; " +
                "Unregister-ScheduledTask -TaskName 'Emi startup' -Confirm:`$false -ErrorAction SilentlyContinue")
        } catch { Write-Host " ! Couldn't remove them - run uninstall_shortcuts.bat later." }
    }
    if ($startup) {
        $l = $shell.CreateShortcut($startupLink)
        $l.TargetPath = $target; $l.Arguments = $bgArgs; $l.WorkingDirectory = $root
        if (Test-Path $icon) { $l.IconLocation = "$icon,0" }
        $l.Save()
        Write-Host " + Emi starts with Windows"
    }
}
Write-Host ""
Write-Host " Done. Press $hk anytime to summon Emi. (The first press can take a few seconds while she starts.)"
Write-Host ""
