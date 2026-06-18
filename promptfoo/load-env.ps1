param(
  [string]$Path = (Join-Path $PSScriptRoot ".env")
)

if (-not (Test-Path -LiteralPath $Path)) {
  throw "Env file not found: $Path"
}

Get-Content -LiteralPath $Path | ForEach-Object {
  $line = $_.Trim()

  if (-not $line -or $line.StartsWith("#")) {
    return
  }

  $name, $value = $line -split "=", 2
  if (-not $name) {
    return
  }

  if ($null -eq $value) {
    $value = ""
  } else {
    $value = $value.Trim().Trim('"').Trim("'")
  }

  Set-Item -Path "Env:$($name.Trim())" -Value $value
}

Write-Host "Loaded promptfoo environment from $Path"
