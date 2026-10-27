# Connects this terminal to the PERSONAL account: Azure, Power Platform (pac) and a Microsoft Graph / Excel check.
# Run from the repo root:  .\scripts\connect-personal.ps1
# Optional: .\scripts\connect-personal.ps1 -SubscriptionId <id> -EnvironmentUrl https://<org>.crm.dynamics.com
param(
  [string]$SubscriptionId,
  [string]$EnvironmentUrl,
  [string]$ResourceGroup = "rg-claims-poc",
  [string]$Location = "australiaeast"
)

# pick up CLIs installed after this terminal opened
$env:Path = [Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [Environment]::GetEnvironmentVariable("Path","User")

function Step($text) { ""; "=== $text ===" }
# az prints nothing when called directly from PowerShell on this machine, so run it through cmd.
function Az([string]$cmdline) { cmd /c "az $cmdline" }

Step "1/5 Azure sign-in (sign in with the PERSONAL account in the browser)"
az config set core.enable_broker_on_windows=false 2>&1 | Out-Null
Az "login"
if (-not $SubscriptionId) {
  Az "account list -o table"
  $SubscriptionId = Read-Host "Paste the personal subscription id from the table above"
}
Az "account set --subscription $SubscriptionId"
Az "account show -o table"

Step "2/5 Register resource providers (idempotent, can take a few minutes)"
foreach ($ns in "Microsoft.CognitiveServices","Microsoft.App","Microsoft.OperationalInsights","Microsoft.KeyVault","Microsoft.Compute","Microsoft.Storage") {
  Az "provider register --namespace $ns --wait" | Out-Null
  "registered $ns"
}

Step "3/5 Resource group"
Az "group create --name $ResourceGroup --location $Location -o table"

Step "4/5 Power Platform sign-in (browser)"
if ($EnvironmentUrl) { pac auth create --name personal --environment $EnvironmentUrl }
else                 { pac auth create --name personal }
pac auth list
pac env list
if ($EnvironmentUrl) { pac org who }

Step "5/5 Excel / OneDrive access via Microsoft Graph"
Az "rest --method get --url https://graph.microsoft.com/v1.0/me/drive"
if ($LASTEXITCODE -ne 0) {
  "Graph access failed. That is normal for a personal Microsoft account."
  "Excel Online is connected inside Power Apps / Power Automate instead (Data > Add data > Excel Online)."
}

""
"Done. Next: pac auth create --environment <your URL> if you did not pass -EnvironmentUrl, then run .\scripts\check-access.ps1"
