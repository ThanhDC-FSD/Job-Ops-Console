param(
  [string]$OutputPath = "artifacts/intro_video/job_ops_project_showcase_voice_2026-03-14.wav",
  [int]$Rate = 1,
  [string]$Text = "This is Job Ops Console, one of my portfolio projects. It combines job crawling, metadata normalization, fit evaluation, CV and cover letter generation, and apply tracking inside a single local first operator console. The dashboard shows geographic coverage and applied job trends. The jobs area supports filtering, fit review, and artifact actions. There are also views for applied jobs, repost analytics, learning and knowledge review, and automation schedules with run history. At a high level, the architecture uses Playwright and parsers for crawl and ETL, FastAPI with SQLite for the backend workflow, and React for the operator console. RAG and offline LLM steps are guarded by validators and deterministic fallbacks. The system was developed to stay practical on a weak local machine, using CPU only execution, limited memory, and lightweight persistence. This showcase video itself was assembled through browser automation and scripted media generation."
)

$resolvedOutput = [System.IO.Path]::GetFullPath($OutputPath)
$outputDir = Split-Path -Parent $resolvedOutput
if (-not (Test-Path $outputDir)) {
  New-Item -ItemType Directory -Path $outputDir | Out-Null
}

Add-Type -AssemblyName System.Speech
$speaker = New-Object System.Speech.Synthesis.SpeechSynthesizer
$speaker.Rate = $Rate
$speaker.SetOutputToWaveFile($resolvedOutput)
$speaker.Speak($Text)
$speaker.Dispose()

Write-Output $resolvedOutput
