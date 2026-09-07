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

# Run container
docker run -d `
    --name $ContainerName `
    -p "${Port}:8000" `
    -v farmflow-data:/app/db `
    --env-file .env `
    $ImageName

Write-Host "울퉁불퉁 농장 AI running at http://localhost:$Port"
Start-Process "http://localhost:$Port"
