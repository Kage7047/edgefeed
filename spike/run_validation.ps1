# Validation runner for Windows Task Scheduler.
# Appends one scan of the curated pairs to the ledger. $0 cost.
#
# Register (every 10 min) -- run once in PowerShell, adjust the path:
#   $act = New-ScheduledTaskAction -Execute "powershell.exe" `
#     -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$PWD\spike\run_validation.ps1`""
#   $trg = New-ScheduledTaskTrigger -Once -At (Get-Date) `
#     -RepetitionInterval (New-TimeSpan -Minutes 10)
#   Register-ScheduledTask -TaskName "EdgeFeedValidation" -Action $act -Trigger $trg
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")   # repo root
$py    = if ($env:PYTHON) { $env:PYTHON } else { "python" }
$pairs = if ($env:PAIRS)  { $env:PAIRS }  else { "spike\curated_pairs.example.json" }
$db    = if ($env:DB)     { $env:DB }     else { "spike\ledger.sqlite" }

& $py spike\arb_spike.py `
  --pairs $pairs `
  --log-db $db `
  --min-net 0.5 `
  --quiet `
  --kalshi-limit 1500 --poly-limit 800
