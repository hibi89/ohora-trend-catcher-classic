# LEGACY balanced-mode foreground loop. For daily-first use daily_scheduler.py.
# Does NOT install a Windows scheduled task.
param(
  [Parameter(Mandatory=$true)][string]$Source,
  [Parameter(Mandatory=$true)][string]$EnvFile,
  [string]$OutputDir = (Join-Path $env:LOCALAPPDATA 'OHORA_RAW_v2'),
  [ValidateRange(1,30)][int]$Cycles = 10,
  [ValidateRange(1,60)][int]$MaxBatches = 30,
  [ValidateRange(1,10)][int]$BatchSize = 5
)
$ErrorActionPreference = 'Stop'
if (-not (Test-Path $Source)) { throw 'Official source not found' }
if (-not (Test-Path $EnvFile)) { throw 'Local Meta env file not found' }
$py = Join-Path $PSScriptRoot 'collector.py'
for ($i = 1; $i -le $Cycles; $i++) {
  Write-Warning 'Legacy balanced collector: for KST daily-first use raw_v2/daily_scheduler.py.'
  $slotStart = Get-Date
  Write-Host "OHORA RAW v2 slot $i of $Cycles start $($slotStart.ToString('s'))"
  & python $py --source $Source --env-file $EnvFile --output-dir $OutputDir `
    --mode balanced --limit 4 --window-days 7 --history-days 365 `
    --batch-size $BatchSize --max-batches $MaxBatches --stop-usage 85 --live
  $code = $LASTEXITCODE
  if ($code -notin @(0,2)) { throw "Collector failed with exit code $code. Loop stopped." }
  if ($i -eq $Cycles) { break }
  # Use the same persisted DB state and wait function as the engine/scheduler.
  $waitScript = @'
import math, sqlite3, sys
from pathlib import Path
from datetime import datetime, timezone
from contextlib import closing
sys.path.insert(0, sys.argv[1])
import collector
target = Path(sys.argv[2]).resolve() / 'collection.sqlite'
with closing(sqlite3.connect(target.as_uri() + '?mode=ro', uri=True)) as db:
    db.row_factory = sqlite3.Row
    slot = db.execute('SELECT * FROM slots ORDER BY slot_id DESC LIMIT 1').fetchone()
    ready = collector.slot_ready_at(slot)
    print(max(0, math.ceil((ready - datetime.now(timezone.utc)).total_seconds())) if ready else 0)
'@
  $waitSeconds = & python -c $waitScript $PSScriptRoot $OutputDir
  if ($LASTEXITCODE -ne 0) { throw 'Could not read shared cooldown state. Loop stopped.' }
  Write-Host "Cooldown from SQLite: $waitSeconds seconds; Ctrl+C to stop."
  if ([int]$waitSeconds -gt 0) { Start-Sleep -Seconds ([int]$waitSeconds) }
}
