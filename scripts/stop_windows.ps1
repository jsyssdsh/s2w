$ErrorActionPreference = "Stop"

$ContainerName = "farmflow"

# Stop and remove container, keep volume (idempotent)
docker rm -f $ContainerName 2>$null | Out-Null

Write-Host "울퉁불퉁 농장 AI stopped."
