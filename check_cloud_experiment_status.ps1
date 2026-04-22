$ConfigPath = Join-Path $PSScriptRoot "yun_gpu_checker_config.json"
if (-not (Test-Path $ConfigPath)) {
    $ConfigPath = Join-Path $PSScriptRoot "yun_gpu_checker_config.example.json"
}

$PythonCandidates = @(
    "python",
    "py"
)

$PythonBin = $null
foreach ($candidate in $PythonCandidates) {
    try {
        $null = Get-Command $candidate -ErrorAction Stop
        $PythonBin = $candidate
        break
    }
    catch {
    }
}

if (-not $PythonBin) {
    Write-Error "No usable Python found. Please install Python first."
    exit 1
}

& $PythonBin (Join-Path $PSScriptRoot "check_cloud_experiment_status.py") --config $ConfigPath
