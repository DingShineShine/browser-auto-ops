# Publish a compiled Windows wheel to pypi.org. Never uploads an sdist.
#   1. Bump [project].version in pyproject.toml first. PyPI rejects reuse.
#   2. $env:UV_PUBLISH_TOKEN = "<pypi-api-token>"
#   3. powershell -File scripts/publish_pypi.ps1

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

if (-not $env:UV_PUBLISH_TOKEN) {
    throw "Set UV_PUBLISH_TOKEN to a pypi.org API token. Do not paste the token into chat."
}

$pyproject = Get-Content (Join-Path $repoRoot "pyproject.toml") -Raw
if ($pyproject -notmatch '(?m)^version\s*=\s*"([^"]+)"') {
    throw "Could not read [project].version from pyproject.toml"
}
$version = $Matches[1]
Write-Host "Publishing browser-auto-ops $version (wheel only)"

$compiler = Join-Path $repoRoot ".venv-py312\Scripts\python.exe"
if (-not (Test-Path $compiler)) {
    Write-Host "Creating Python 3.12 compile venv"
    uv venv --python 3.12 .venv-py312
    if ($LASTEXITCODE -ne 0) { throw "uv venv failed" }
    uv pip install --python .venv-py312 cython setuptools ziglang hatchling
    if ($LASTEXITCODE -ne 0) { throw "compile dependency install failed" }
    $compiler = Join-Path $repoRoot ".venv-py312\Scripts\python.exe"
}

Write-Host "Compiling core modules with $compiler"
& $compiler (Join-Path $repoRoot "hatch_build.py")
if ($LASTEXITCODE -ne 0) {
    throw "hatch_build.py compile failed"
}

if (Test-Path (Join-Path $repoRoot "dist")) {
    Remove-Item (Join-Path $repoRoot "dist") -Recurse -Force
}

uv build --wheel
if ($LASTEXITCODE -ne 0) {
    throw "uv build --wheel failed"
}

$sdists = Get-ChildItem (Join-Path $repoRoot "dist") -Filter "*.tar.gz" -ErrorAction SilentlyContinue
if ($sdists) {
    throw "Refusing to publish: sdist present in dist/. Only platform wheels may be uploaded."
}

$wheels = @(Get-ChildItem (Join-Path $repoRoot "dist") -Filter "*.whl")
if ($wheels.Count -eq 0) {
    throw "No wheel found in dist/"
}
$sourceWheels = @($wheels | Where-Object { $_.Name -match "py3-none-any" })
if ($sourceWheels.Count -gt 0) {
    throw "Refusing to publish a pure-Python wheel ($($sourceWheels[0].Name)). Compile must produce a platform wheel."
}

uv publish @($wheels.FullName)
if ($LASTEXITCODE -ne 0) {
    throw "uv publish failed. Confirm the token can upload browser-auto-ops and the version is new."
}

Write-Host "Published $($wheels.Name -join ', ')"
Write-Host "Others refresh with:"
Write-Host "  uv tool upgrade browser-auto-ops --python 3.12 || uv tool install browser-auto-ops --python 3.12"
