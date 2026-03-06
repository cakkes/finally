docker stop finally-app 2>$null
docker rm finally-app 2>$null
Write-Host "FinAlly stopped. Data preserved."
