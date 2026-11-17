function Import-AolEnv {
  param([string]$Path)
  if (-not (Test-Path $Path)) { throw ".env not found at $Path (copy .env.example)" }
  $h = @{}
  Get-Content $Path | Where-Object { $_ -match '^\s*[^#\s][^=]*=' } | ForEach-Object {
    $k, $v = $_ -split '=', 2
    $h[$k.Trim()] = $v.Trim()
  }
  return $h
}

function Assert-AolSubscription {
  param([string]$SubscriptionId)
  $acct = az account show -o json | ConvertFrom-Json
  Write-Host "Signed in as $($acct.user.name); active subscription: $($acct.name) ($($acct.id))"
  if ($acct.id -ne $SubscriptionId) {
    throw "Active subscription $($acct.id) is not the sandbox $SubscriptionId. Run: az account set --subscription $SubscriptionId"
  }
}
