param(
    [string]$TaskName = "Interview_QA_Night",
    [string]$StartTime = "01:30"
)

$projectRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$runner = Join-Path $projectRoot "scripts\powershell\predict_night.ps1"

$command = "powershell.exe -ExecutionPolicy Bypass -File `"$runner`" -Force"
schtasks /create /tn $TaskName /sc DAILY /st $StartTime /rl HIGHEST /tr $command /f
