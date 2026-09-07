$ErrorActionPreference = "Stop"

$ContainerName = "farmflow"
$ImageName = "farmflow"
$Port = 8000

Set-Location "$PSScriptRoot\.."

# Build if image doesn't exist or -Build flag passed
$needsBuild = $args -contains "--build"
if (-not $needsBuild) {
    docker image inspect $ImageName 2>$null | Out-Null
    if ($LASTEXITCODE -ne 0) { $needsBuild = $true }
}

if ($needsBuild) {
    Write-Host "Building image..."
    docker build -t $ImageName .
}

# Stop existing container if running (idempotent)
docker rm -f $ContainerName 2>$null | Out-Null

# .env is optional: a clean clone has only .env.example, and the image already
# defaults to the same values. Passing --env-file for a missing file is a hard
# `docker run` error, so only add it when the file is actually there.
$EnvArgs = @()
if (Test-Path .env) { $EnvArgs = @("--env-file", ".env") }

# Run container
docker run -d `
    --name $ContainerName `
    -p "${Port}:8000" `
    -v farmflow-data:/app/db `
    @EnvArgs `
    $ImageName

Write-Host "울퉁불퉁 농장 AI running at http://localhost:$Port"
Start-Process "http://localhost:$Port"
