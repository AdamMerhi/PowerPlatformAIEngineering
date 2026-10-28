# Read-only connectivity check. Run from the repo root:  .\scripts\check-access.ps1
# Loads .env (if present) into this session, then tests each connection and prints PASS / FAIL.

$ErrorActionPreference = "Continue"
$env:Path = [Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [Environment]::GetEnvironmentVariable("Path","User")

if (Test-Path .env) {
  Get-Content .env | Where-Object { $_ -match '^\s*[^#\s][^=]*=' } | ForEach-Object {
    $k, $v = $_ -split '=', 2
    if ($v.Trim()) { Set-Item -Path "env:$($k.Trim())" -Value $v.Trim() }
  }
}

$results = [ordered]@{}
function Check($name, [scriptblock]$test, [switch]$IgnoreExitCode) {
  try {
    $out = & $test 2>&1 | Out-String
    if (-not $IgnoreExitCode -and $LASTEXITCODE -and $LASTEXITCODE -ne 0) { throw $out }
    $results[$name] = "PASS  " + ($out.Trim() -split "`n")[0]
  } catch {
    $msg = ($_.ToString().Trim() -split "`n")[0]
    $results[$name] = "FAIL  $msg"
  }
}

# az --version and pac help can return a non-zero exit code on success (update-nag warnings),
# so these two checks ignore exit code and just report the captured output.
Check "Azure CLI installed"     { az --version | Select-Object -First 1 } -IgnoreExitCode
Check "Azure login"             { az account show --query "[name, state]" -o tsv }
Check "Provider: CognitiveSvc"  { az provider show --namespace Microsoft.CognitiveServices --query registrationState -o tsv }
Check "OpenAI model gpt-4o-mini in australiaeast" {
  $m = az cognitiveservices model list --location australiaeast --query "[?model.name=='gpt-4o-mini'] | length(@)" -o tsv
  if ([int]$m -lt 1) { throw "not listed in australiaeast; try eastus2 or swedencentral" } else { "listed" }
}
Check "Resource group rg-claims-poc" { az group show --name rg-claims-poc --query name -o tsv }
Check "Power Platform CLI (pac)" { pac help | Select-Object -First 1 } -IgnoreExitCode
Check "Dataverse (pac org who)"  { pac org who }
Check "Python Snowflake package" { python -c "import snowflake.connector as s; print(s.__version__)" }
Check "Snowflake connection"     {
  if (-not $env:SNOWFLAKE_ACCOUNT) { throw "SNOWFLAKE_ACCOUNT not set (fill in .env)" }
  python scripts/check_snowflake.py
}
Check "Azure OpenAI (claims-llm)" {
  if (-not $env:AZURE_OPENAI_ENDPOINT) { throw "AZURE_OPENAI_ENDPOINT not set (fill in .env)" }
  python scripts/check_openai.py
}

""
"=== Connection check ==="
$results.GetEnumerator() | ForEach-Object { "{0,-45} {1}" -f $_.Key, $_.Value }
""
"Manual checks still needed:"
" - make.powerapps.com opens and shows a developer environment"
" - ai.azure.com lets you create a project and deploy gpt-4o-mini"
" - copilotstudio.microsoft.com lets you start a trial"
