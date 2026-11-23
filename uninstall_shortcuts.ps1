# Removes Emi's shortcuts, startup entry and administrator tasks. Your files and settings stay.
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$hadAdmin = Test-Path (Join-Path $root "data\admin_task")
foreach ($p in @(
    (Join-Path ([Environment]::GetFolderPath("Programs")) "Emi.lnk"),
    (Join-Path ([Environment]::GetFolderPath("Desktop")) "Emi.lnk"),
    (Join-Path ([Environment]::GetFolderPath("Startup")) "Emi.lnk"),
    (Join-Path $root "data\admin_task"))) {
    if (Test-Path $p) { Remove-Item $p; Write-Host " - removed $p" }
}
if ($hadAdmin) {
    Write-Host " Windows will ask for permission to remove the administrator tasks..."
    try {
        Start-Process powershell -Verb RunAs -Wait -ArgumentList @("-NoProfile", "-Command",
            "Unregister-ScheduledTask -TaskName 'Emi' -Confirm:`$false -ErrorAction SilentlyContinue; " +
            "Unregister-ScheduledTask -TaskName 'Emi startup' -Confirm:`$false -ErrorAction SilentlyContinue")
    } catch { Write-Host " ! Cancelled - the administrator tasks are still there." }
}
Write-Host " Done."
