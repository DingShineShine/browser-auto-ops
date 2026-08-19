# Publish a Windows wheel to this project's GitLab Package Registry (private PyPI).
# Create a Project Access Token with write_package_registry (and api if you need to inspect).
#   $env:UV_PUBLISH_PASSWORD = "<token>"
#   powershell -File scripts/publish_gitlab.ps1

param(
    [string]$ProjectPath = "datagroup%2Fbrowser-auto-ops",
    [string]$GitLabHost = "git.shinebed.com.cn",
    [string]$Token = $env:UV_PUBLISH_PASSWORD
)

$ErrorActionPreference = "Stop"

if (-not $Token) {
    throw "Set UV_PUBLISH_PASSWORD to a GitLab token with write_package_registry."
}

$publishUrl = "https://$GitLabHost/api/v4/projects/$ProjectPath/packages/pypi"
$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

$compiler = Join-Path $repoRoot ".venv-py312\Scripts\python.exe"
if (-not (Test-Path $compiler)) {
    $compiler = (Get-Command python -ErrorAction SilentlyContinue).Source
}
if ($compiler) {
    Write-Host "Compiling core modules with $compiler"
    & $compiler (Join-Path $repoRoot "hatch_build.py")
    if ($LASTEXITCODE -ne 0) {
        throw "hatch_build.py compile failed"
    }
}

uv build --wheel
if ($LASTEXITCODE -ne 0) {
    throw "uv build --wheel failed"
}

$env:UV_PUBLISH_USERNAME = "__token__"
$env:UV_PUBLISH_PASSWORD = $Token
uv publish --publish-url $publishUrl
if ($LASTEXITCODE -ne 0) {
    throw "uv publish failed. Confirm Package Registry is enabled and the token can write packages."
}

Write-Host "Published to $publishUrl"
Write-Host "Install with:"
Write-Host "  uv tool install browser-auto-ops --python 3.12 --index-url https://$GitLabHost/api/v4/projects/$ProjectPath/packages/pypi/simple"
