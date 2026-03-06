$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectDir = Split-Path -Parent $ScriptDir
Set-Location $ProjectDir

if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
    Write-Host "Created .env from .env.example - please add your OPENROUTER_API_KEY"
}

if ($args[0] -eq "--build" -or -not (docker image inspect finally:latest 2>$null)) {
    Write-Host "Building FinAlly Docker image..."
    docker build -t finally:latest .
}

docker rm -f finally-app 2>$null
docker run -d `
    --name finally-app `
    -v finally-data:/app/db `
    -p 8000:8000 `
    --env-file .env `
    finally:latest

Write-Host ""
Write-Host "FinAlly is running at http://localhost:8000"
Start-Process "http://localhost:8000"
