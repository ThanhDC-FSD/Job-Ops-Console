param(
    [string]$CvPath = "input/full_doc_stlye.txt",
    [int]$Limit = 10,
    [int]$RecentDays = 14,
    [switch]$Force
)

$projectRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$pythonExe = Join-Path $projectRoot ".venv\Scripts\python.exe"
$scriptPath = Join-Path $projectRoot "scripts\python\predict_night.py"

if (-not (Test-Path $pythonExe)) {
    throw "Python virtual environment not found at $pythonExe"
}

$argsList = @($scriptPath, "--mode", "nightly", "--cv-path", $CvPath, "--limit", "$Limit", "--recent-days", "$RecentDays")
if ($Force) {
    $argsList += "--force"
}

& $pythonExe @argsList
exit $LASTEXITCODE
