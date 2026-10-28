# Deploy (or update) the Claims PDS Agent API on Azure Container Apps. Run from the repo root:
#   .\scripts\deploy-agent.ps1
#   .\scripts\deploy-agent.ps1 -Image ghcr.io/adammerhi/claims-agent:<sha>      # a specific build
#
# Needs: az login (personal subscription), the image pushed by .github/workflows/agent-api.yml, and .env filled in.
# Scale to zero: no idle compute cost. Secrets live in Container Apps secrets, never in the image or the repo.
# If the GHCR package is private, pass -RegistryUser and -RegistryToken (a PAT with read:packages).
param(
  [string]$Image = "ghcr.io/adammerhi/claims-agent:latest",
  [string]$ResourceGroup = "rg-claims-poc",
  [string]$Location = "australiaeast",
  [string]$EnvName = "cae-claims",
  [string]$AppName = "claims-agent",
  [string]$RegistryUser = "",
  [string]$RegistryToken = ""
)
# "Continue", not "Stop": Windows PowerShell 5.1 turns any text az writes to stderr (such as the harmless
# "behavior altered by the containerapp extension" warning) into a terminating error. Real failures are
# caught by the explicit $LASTEXITCODE checks below.
$ErrorActionPreference = "Continue"
function Assert-Az([string]$what) { if ($LASTEXITCODE -ne 0) { throw "$what failed (az exit code $LASTEXITCODE)" } }
$env:Path = [Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [Environment]::GetEnvironmentVariable("Path","User")

# Load .env into this session
$envFile = ".env"
if (-not (Test-Path $envFile)) { throw ".env not found. Run from the repo root." }
Get-Content $envFile | Where-Object { $_ -match '^\s*[^#\s][^=]*=' } | ForEach-Object {
  $k, $v = $_ -split '=', 2
  if ($v.Trim()) { Set-Item -Path "env:$($k.Trim())" -Value $v.Trim() }
}
foreach ($name in "AZURE_OPENAI_ENDPOINT","AZURE_OPENAI_KEY","AZURE_TENANT_ID","AZURE_CLIENT_ID","AZURE_CLIENT_SECRET","DATAVERSE_URL") {
  if (-not (Get-Item "env:$name" -ErrorAction SilentlyContinue)) { throw "$name is empty in .env" }
}
$deployment = if ($env:AZURE_OPENAI_DEPLOYMENT) { $env:AZURE_OPENAI_DEPLOYMENT } else { "powerapps-pds" }

# The API key the Power Apps connector will send. Generated once and kept in .env (git-ignored); never printed.
if (-not $env:AGENT_API_KEY) {
  $bytes = New-Object byte[] 32
  [Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
  $env:AGENT_API_KEY = [Convert]::ToBase64String($bytes).TrimEnd('=').Replace('+','-').Replace('/','_')
  Add-Content -Path $envFile -Value "AGENT_API_KEY=$($env:AGENT_API_KEY)"
  Write-Host "Generated AGENT_API_KEY and saved it to .env"
}

az extension add --name containerapp --upgrade --only-show-errors | Out-Null

$envExists = az containerapp env show -n $EnvName -g $ResourceGroup --query name -o tsv 2>$null
if (-not $envExists) {
  Write-Host "Creating Container Apps environment $EnvName ..."
  az containerapp env create -n $EnvName -g $ResourceGroup -l $Location --only-show-errors | Out-Null
  Assert-Az "Creating the Container Apps environment"
}

$secrets = @(
  "openai-key=$($env:AZURE_OPENAI_KEY)",
  "agent-key=$($env:AGENT_API_KEY)",
  "dataverse-secret=$($env:AZURE_CLIENT_SECRET)"
)
$envVars = @(
  "AZURE_OPENAI_ENDPOINT=$($env:AZURE_OPENAI_ENDPOINT)",
  "AZURE_OPENAI_DEPLOYMENT=$deployment",
  "AZURE_OPENAI_KEY=secretref:openai-key",
  "AGENT_API_KEY=secretref:agent-key",
  "AZURE_TENANT_ID=$($env:AZURE_TENANT_ID)",
  "AZURE_CLIENT_ID=$($env:AZURE_CLIENT_ID)",
  "AZURE_CLIENT_SECRET=secretref:dataverse-secret",
  "DATAVERSE_URL=$($env:DATAVERSE_URL)"
)

$appExists = az containerapp show -n $AppName -g $ResourceGroup --query name -o tsv 2>$null
if ($appExists) {
  Write-Host "Updating $AppName to $Image ..."
  az containerapp secret set -n $AppName -g $ResourceGroup --secrets @secrets --only-show-errors | Out-Null
  Assert-Az "Setting secrets"
  az containerapp update -n $AppName -g $ResourceGroup --image $Image --set-env-vars @envVars --only-show-errors | Out-Null
  Assert-Az "Updating the container app"
} else {
  Write-Host "Creating $AppName from $Image ..."
  $create = @("-n", $AppName, "-g", $ResourceGroup, "--environment", $EnvName, "--image", $Image,
              "--target-port", "8080", "--ingress", "external", "--min-replicas", "0", "--max-replicas", "2",
              "--cpu", "1.0", "--memory", "2.0Gi", "--secrets") + $secrets + @("--env-vars") + $envVars
  if ($RegistryUser) { $create += @("--registry-server", "ghcr.io", "--registry-username", $RegistryUser, "--registry-password", $RegistryToken) }
  az containerapp create @create --only-show-errors | Out-Null
  Assert-Az "Creating the container app"
}

$fqdn = az containerapp show -n $AppName -g $ResourceGroup --query properties.configuration.ingress.fqdn -o tsv
Write-Host "Deployed: https://$fqdn   (health: https://$fqdn/health)"
Write-Host "Add AGENT_API_BASE_URL=https://$fqdn to .env for the connector setup."
