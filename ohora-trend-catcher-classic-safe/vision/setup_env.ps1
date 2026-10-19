# One-time LOCAL setup. Never push .env.local or print your key.
$ErrorActionPreference = "Stop"
$Target = Join-Path $PSScriptRoot ".env.local"
if (Test-Path -LiteralPath $Target) {
    $answer = Read-Host "vision/.env.local exists. Replace it? (y/N)"
    if ($answer -ne "y") { Write-Host "Existing configuration preserved."; exit 0 }
}
Write-Host "OpenAI-compatible vision gateway configuration; no API requests will be made."
$base = Read-Host "Base URL ending in /v1 (enter your gateway URL)"
if (-not $base.StartsWith("https://")) { throw "HTTPS URL required." }
$model = Read-Host "Model ID as shown by provider (e.g. gemini-3.8-flash)"
if ([string]::IsNullOrWhiteSpace($model)) { throw "Model ID is required." }
$secure = Read-Host "API key (input is hidden)" -AsSecureString
$ptr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
try {
    $key = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($ptr)
    if ([string]::IsNullOrWhiteSpace($key)) { throw "API key is required." }
    if ($key.Contains("`n") -or $key.Contains("`r")) { throw "Invalid API key." }
    $text = @(
        "VISION_BASE_URL=$($base.Trim())"
        "VISION_MODEL=$($model.Trim())"
        "VISION_API_KEY=$key"
    ) -join "`n"
    [System.IO.File]::WriteAllText($Target, $text + "`n", (New-Object System.Text.UTF8Encoding($false)))
    Write-Host "Saved locally to vision/.env.local (Git ignored). Key was not printed."
} finally {
    [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ptr)
    Remove-Variable key -ErrorAction SilentlyContinue
}
