# Builds the Angular app and publishes it to the private S3 bucket behind CloudFront.
# Hashed assets are cached for a year; index.html is never cached, so new releases
# appear immediately after the invalidation.
# Requires: AWS CLI v2, Node.js. STATUS: not yet executed against a real AWS account.
#
# Usage:
#   powershell -ExecutionPolicy Bypass -File scripts\aws\deploy-frontend.ps1 -Region af-south-1 -StackName propman
param(
    [Parameter(Mandatory = $true)][string]$Region,
    [Parameter(Mandatory = $true)][string]$StackName
)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)

function Out-Stack($key) {
    aws cloudformation describe-stacks --region $Region --stack-name $StackName `
        --query "Stacks[0].Outputs[?OutputKey=='$key'].OutputValue" --output text
}
$bucket = Out-Stack "FrontendBucketName"
$distribution = Out-Stack "DistributionId"

Push-Location (Join-Path $root "frontend")
try {
    npm ci --no-audit --no-fund
    if ($LASTEXITCODE -ne 0) { throw "npm ci failed" }
    npx ng build --configuration production
    if ($LASTEXITCODE -ne 0) { throw "build failed" }
    $dist = "dist\frontend\browser"
    # 1) fingerprinted assets: long-lived cache
    aws s3 sync $dist "s3://$bucket" --region $Region --delete `
        --exclude "index.html" --cache-control "public, max-age=31536000, immutable"
    if ($LASTEXITCODE -ne 0) { throw "s3 sync failed" }
    # 2) index.html: always revalidate
    aws s3 cp "$dist\index.html" "s3://$bucket/index.html" --region $Region `
        --cache-control "no-cache" --content-type "text/html; charset=utf-8"
    if ($LASTEXITCODE -ne 0) { throw "index upload failed" }
    aws cloudfront create-invalidation --distribution-id $distribution --paths "/index.html" "/" | Out-Null
    Write-Host "Frontend published to s3://$bucket and CloudFront invalidated." -ForegroundColor Green
}
finally { Pop-Location }
