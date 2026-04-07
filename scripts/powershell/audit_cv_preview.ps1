param(
  [string]$BaseUrl = "http://127.0.0.1:8102",
  [int]$PageSize = 200,
  [string]$ConstraintMode = "medium",
  [int]$PostedWithinDays = 15,
  [switch]$Fix,
  [string]$OutDir = "artifacts/audits",
  [string]$LogDir = "artifacts/audits/logs",
  [int]$MinIntervalMs = 250,
  [int]$FixCooldownSec = 2,
  [int]$MaxFixPerMinute = 20,
  [string]$RunId = ""
)

$ErrorActionPreference = "Stop"

function Get-JobRows {
  param([object]$resp)
  if ($null -ne $resp.rows) { return $resp.rows }
  if ($null -ne $resp.items) { return $resp.items }
  if ($null -ne $resp.data) { return $resp.data }
  return @()
}

function Get-JobId {
  param([object]$row)
  if ($null -ne $row.id) { return [int]$row.id }
  if ($null -ne $row.job_post_id) { return [int]$row.job_post_id }
  return 0
}

function Is-Blank {
  param([object]$value)
  if ($null -eq $value) { return $true }
  $s = [string]$value
  return [string]::IsNullOrWhiteSpace($s)
}

function Format-LogValue {
  param([object]$value)
  if ($null -eq $value) { return "-" }
  $text = [string]$value
  if ($text -match '\s') { return '"' + ($text -replace '"', "'") + '"' }
  return $text
}

function Write-Log {
  param(
    [string]$Level,
    [string]$Event,
    [string]$Message,
    [hashtable]$Fields
  )
  $ts = (Get-Date).ToString("yyyy-MM-ddTHH:mm:ssK")
  $jobId = "-"
  if ($Fields.ContainsKey("job_id")) { $jobId = $Fields["job_id"] }
  $line = "ts=$ts level=$Level component=Audit.CVPreview event=$Event run_id=$script:runId trace_id=- job_id=$jobId message=$(Format-LogValue $Message)"
  foreach ($key in $Fields.Keys) {
    if ($key -eq "job_id") { continue }
    $line += " $key=$(Format-LogValue $Fields[$key])"
  }
  $line | Tee-Object -FilePath $script:logFile -Append | Write-Host
}

$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\\..")).Path
$outRoot = Join-Path $projectRoot $OutDir
$logRoot = Join-Path $projectRoot $LogDir
New-Item -ItemType Directory -Path $outRoot -Force | Out-Null
New-Item -ItemType Directory -Path $logRoot -Force | Out-Null

$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$script:runId = if ([string]::IsNullOrWhiteSpace($RunId)) { $stamp } else { $RunId }
$auditJson = Join-Path $outRoot "cv_preview_audit_$stamp.json"
$auditCsv = Join-Path $outRoot "cv_preview_audit_$stamp.csv"
$script:logFile = Join-Path $logRoot "cv_preview_audit_$stamp.log"

$targetEnd = [datetime]::Today.AddHours(15)
Write-Log "INFO" "start" "Audit run started" @{
  base_url = $BaseUrl
  page_size = $PageSize
  constraint_mode = $ConstraintMode
  posted_within_days = $PostedWithinDays
  fix = $Fix.IsPresent
  min_interval_ms = $MinIntervalMs
  fix_cooldown_sec = $FixCooldownSec
  max_fix_per_min = $MaxFixPerMinute
  target_end = $targetEnd.ToString("yyyy-MM-ddTHH:mm:ssK")
}

$offset = 0
$all = @()
$failures = @()
$processed = 0
$total = $null
$runStart = Get-Date
$lastFixAt = $null
$minFixInterval = if ($MaxFixPerMinute -gt 0) { 60.0 / [double]$MaxFixPerMinute } else { 0 }

while ($true) {
  if ((Get-Date) -ge $targetEnd) {
    Write-Log "WARN" "time_budget_exhausted" "Stopping due to time budget" @{ processed = $processed; total = $total }
    break
  }

  $listUrl = "$BaseUrl/api/jobs?summary_only=1&limit=$PageSize&offset=$offset&posted_within_days=$PostedWithinDays"
  try {
    $resp = Invoke-RestMethod -Uri $listUrl -Method Get -TimeoutSec 120
  } catch {
    Write-Log "ERROR" "list_failed" $_.Exception.Message @{ url = $listUrl; offset = $offset }
    break
  }

  if ($null -eq $total -and $null -ne $resp.total) { $total = [int]$resp.total }
  $rows = Get-JobRows $resp
  if ($rows.Count -eq 0) { break }

  foreach ($row in $rows) {
    if ((Get-Date) -ge $targetEnd) {
      Write-Log "WARN" "time_budget_exhausted" "Stopping due to time budget" @{ processed = $processed; total = $total }
      break 2
    }
    $jobId = Get-JobId $row
    if ($jobId -le 0) { continue }

    $jobSw = [System.Diagnostics.Stopwatch]::StartNew()
    $previewUrl = "$BaseUrl/api/jobs/$jobId/cv-preview?constraint_mode=$ConstraintMode"
    $status = "ok"
    $missing = @()
    $errMsg = ""
    try {
      $preview = Invoke-RestMethod -Uri $previewUrl -Method Get -TimeoutSec 180
      if (Is-Blank $preview.cv_path -and Is-Blank $preview.docx_path -and Is-Blank $preview.pdf_path) { $missing += "cv" }
      if (Is-Blank $preview.cover_letter_path -and Is-Blank $preview.cover_letter_docx_path -and Is-Blank $preview.cover_letter_pdf_path) { $missing += "cover_letter" }
      if (Is-Blank $preview.portfolio_path) { $missing += "portfolio" }
      if ($missing.Count -gt 0) { $status = "missing" }
    } catch {
      $status = "error"
      $errMsg = $_.Exception.Message
    }

    $fixStatus = ""
    if ($Fix -and $status -ne "ok") {
      if ($minFixInterval -gt 0 -and $null -ne $lastFixAt) {
        $elapsed = (Get-Date) - $lastFixAt
        $sleepFor = $minFixInterval - $elapsed.TotalSeconds
        if ($sleepFor -gt 0) { Start-Sleep -Seconds $sleepFor }
      }
      try {
        $fixUrl = "$BaseUrl/api/cv/rewrite-render/from-job/$jobId"
        Invoke-RestMethod -Uri $fixUrl -Method Post -Body "{}" -ContentType "application/json" -TimeoutSec 600 | Out-Null
        $fixStatus = "ok"
      } catch {
        $fixStatus = "error"
        if (-not $errMsg) { $errMsg = $_.Exception.Message }
      }
      $lastFixAt = Get-Date
      if ($FixCooldownSec -gt 0) { Start-Sleep -Seconds $FixCooldownSec }
    }

    $jobSw.Stop()
    $processed += 1

    $record = [pscustomobject]@{
      job_id = $jobId
      status = $status
      missing = ($missing -join ",")
      error = $errMsg
      title = $row.title
      company = $row.company
    }
    $all += $record
    if ($status -ne "ok") { $failures += $record }

    Write-Log "INFO" "job_audit" "Job preview audited" @{
      job_id = $jobId
      status = $status
      missing = ($missing -join ",")
      fix = $Fix.IsPresent
      fix_status = $fixStatus
      duration_ms = $jobSw.ElapsedMilliseconds
    }

    if ($MinIntervalMs -gt 0) { Start-Sleep -Milliseconds $MinIntervalMs }

    if ($total -and ($processed % 25 -eq 0)) {
      $elapsedRun = (Get-Date) - $runStart
      $avgMs = if ($processed -gt 0) { [int](($elapsedRun.TotalMilliseconds) / $processed) } else { 0 }
      $remaining = $total - $processed
      $etaSec = if ($avgMs -gt 0) { [int](($avgMs * $remaining) / 1000) } else { 0 }
      $timeLeft = $targetEnd - (Get-Date)
      Write-Log "INFO" "pace" "Pace check" @{
        processed = $processed
        total = $total
        avg_ms_per_job = $avgMs
        eta_seconds = $etaSec
        time_left_seconds = [int]$timeLeft.TotalSeconds
      }
    }
  }

  if ($rows.Count -lt $PageSize) { break }
  $offset += $rows.Count
}

$all | ConvertTo-Json -Depth 5 | Set-Content -Path $auditJson -Encoding UTF8
$all | Export-Csv -Path $auditCsv -NoTypeInformation -Encoding UTF8

$summary = [pscustomobject]@{
  total = $all.Count
  failed = $failures.Count
  output_json = $auditJson
  output_csv = $auditCsv
  log_file = $script:logFile
}
$summary | ConvertTo-Json -Depth 3

Write-Log "INFO" "complete" "Audit run complete" @{
  total = $all.Count
  failed = $failures.Count
  output_json = $auditJson
  output_csv = $auditCsv
}
