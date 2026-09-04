param(
  [string]$ProfileName = "paper-atlas"
)

$ErrorActionPreference = "Stop"

if (-not (Get-Command aws -ErrorAction SilentlyContinue)) {
  throw "AWS CLI was not found. Install AWS CLI v2, then run this script again."
}

aws sts get-caller-identity --profile $ProfileName *> $null
if ($LASTEXITCODE -eq 0) {
  Write-Host "The cached AWS session for '$ProfileName' is still valid; no login is needed."
  exit 0
}

Write-Host "Starting AWS SSO login for profile '$ProfileName'."

$ssoStartUrl = aws configure get sso_start_url --profile $ProfileName 2>$null
if (-not $ssoStartUrl) {
  Write-Host "This profile is not configured yet. AWS CLI will ask for your SSO start URL, SSO region, account, and role."
  aws configure sso --profile $ProfileName
}

aws sso login --profile $ProfileName

Write-Host "AWS login completed. The session is cached locally by AWS CLI."
Write-Host "Set PAPER_ATLAS_AWS_PROFILE=$ProfileName in your ignored backend/.env file."
