param(
  [string]$OutputPath = "artifacts/intro_video/job_ops_project_showcase_voice_2026-03-14.wav",
  [int]$Rate = 1,
  [string]$VoiceName = "Microsoft David Desktop",
  [string]$Text = "This is Job Ops Console, one of my portfolio projects. It combines job crawling, metadata normalization, fit evaluation, CV and cover letter generation, and apply tracking inside a single local first operator console. The dashboard shows geographic coverage and applied job trends. The jobs area supports filtering, fit review, and artifact actions. There are also views for applied jobs, repost analytics, learning and knowledge review, and automation schedules with run history. At a high level, the architecture uses Playwright and parsers for crawl and ETL, FastAPI with SQLite for the backend workflow, and React for the operator console. RAG and offline LLM steps are guarded by validators and deterministic fallbacks. The system was developed to stay practical on a weak local machine, using CPU only execution, limited memory, and lightweight persistence. This showcase video itself was assembled through browser automation and scripted media generation."
)

$resolvedOutput = [System.IO.Path]::GetFullPath($OutputPath)
$outputDir = Split-Path -Parent $resolvedOutput
if (-not (Test-Path $outputDir)) {
  New-Item -ItemType Directory -Path $outputDir | Out-Null
}

$synthesized = $false
try {
  Add-Type -AssemblyName System.Speech
  $speaker = New-Object System.Speech.Synthesis.SpeechSynthesizer
  try {
    $speaker.Rate = $Rate
  } catch {
    # Some Windows hosts reject non-default speech rates even though synthesis still works.
  }
  $installedVoices = $speaker.GetInstalledVoices() | ForEach-Object { $_.VoiceInfo }
  $targetVoice = $installedVoices | Where-Object { $_.Name -eq $VoiceName } | Select-Object -First 1
  if (-not $targetVoice) {
    $targetVoice = $installedVoices |
      Where-Object { $_.Gender -eq [System.Speech.Synthesis.VoiceGender]::Male -and $_.Culture.Name -like 'en-*' } |
      Select-Object -First 1
  }
  if (-not $targetVoice) {
    $targetVoice = $installedVoices | Select-Object -First 1
  }
  if ($targetVoice) {
    $speaker.SelectVoice($targetVoice.Name)
  }
  $speaker.SetOutputToWaveFile($resolvedOutput)
  $speaker.Speak($Text)
  $speaker.Dispose()
  $synthesized = $true
} catch {
  $synthesized = $false
}

if (-not $synthesized) {
  $ffmpeg = Get-Command ffmpeg -ErrorAction SilentlyContinue
  if (-not $ffmpeg) {
    throw "Speech synthesis failed and ffmpeg was not available for silent fallback."
  }
  & $ffmpeg.Source -y -loglevel error -f lavfi -i anullsrc=channel_layout=mono:sample_rate=44100 -t 1 -acodec pcm_s16le $resolvedOutput | Out-Null
}

Write-Output $resolvedOutput
