$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$frontendDir = Join-Path $repoRoot "frontend"
$venvPython = Join-Path $repoRoot "venv\Scripts\python.exe"

if (-not (Test-Path $venvPython)) {
    throw "Virtual environment Python was not found at $venvPython"
}

Push-Location $frontendDir
try {
    if (-not (Test-Path (Join-Path $frontendDir "node_modules"))) {
        npm install
    }

    npm run build
}
finally {
    Pop-Location
}

& $venvPython (Join-Path $repoRoot "app.py")
