# Inspect GitLab project + Package Registry. Does not print token values.
#   $env:GITLAB_TOKEN = "<read or write token>"
#   powershell -File scripts/check_gitlab_pypi.ps1

param(
    [string]$ProjectPath = "datagroup%2Fbrowser-auto-ops",
    [string]$GitLabHost = "git.shinebed.com.cn",
    [string]$Token = $(if ($env:GITLAB_TOKEN) { $env:GITLAB_TOKEN } else { $env:UV_PUBLISH_PASSWORD })
)

$ErrorActionPreference = "Stop"
if (-not $Token) {
    throw "Set GITLAB_TOKEN or UV_PUBLISH_PASSWORD to a GitLab token with read_api / read_package_registry."
}

$headers = @{ "PRIVATE-TOKEN" = $Token }
$projectUrl = "https://$GitLabHost/api/v4/projects/$ProjectPath"
$project = Invoke-RestMethod -Headers $headers -Uri $projectUrl
Write-Host "project_id=$($project.id)"
Write-Host "path=$($project.path_with_namespace)"
Write-Host "packages_enabled=$($project.packages_enabled)"
Write-Host "visibility=$($project.visibility)"
Write-Host "pypi_simple=https://$GitLabHost/api/v4/projects/$($project.id)/packages/pypi/simple"
Write-Host "pypi_path_simple=https://$GitLabHost/api/v4/projects/$ProjectPath/packages/pypi/simple"

$packagesUrl = "https://$GitLabHost/api/v4/projects/$($project.id)/packages?package_type=pypi"
$packages = Invoke-RestMethod -Headers $headers -Uri $packagesUrl
Write-Host "pypi_package_count=$($packages.Count)"
$packages | ForEach-Object { Write-Host ("package {0} {1}" -f $_.name, $_.version) }
