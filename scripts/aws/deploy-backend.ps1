# Builds the backend image, pushes it to ECR, runs migrations as a one-off ECS
# task, then rolls the web and worker services onto the new image.
# Requires: AWS CLI v2 (configured credentials), Docker running.
# STATUS: written for docs/AWS_DEPLOYMENT.md - not yet executed against a real AWS account.
#
# Usage:
#   powershell -ExecutionPolicy Bypass -File scripts\aws\deploy-backend.ps1 -Region af-south-1 -StackName propman `
#       -RepositoryUri 123456789012.dkr.ecr.af-south-1.amazonaws.com/propman-backend
param(
    [Parameter(Mandatory = $true)][string]$Region,
    [Parameter(Mandatory = $true)][string]$StackName,
    # ECR repository created once with the AWS CLI (see docs/AWS_DEPLOYMENT.md)
    [Parameter(Mandatory = $true)][string]$RepositoryUri,
    [string]$Tag = (Get-Date -Format "yyyyMMdd-HHmmss")
)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)

function Out-Stack($key) {
    aws cloudformation describe-stacks --region $Region --stack-name $StackName `
        --query "Stacks[0].Outputs[?OutputKey=='$key'].OutputValue" --output text
}

$repo = $RepositoryUri
$cluster = Out-Stack "ClusterName"
$subnets = Out-Stack "PrivateSubnets"
$sg = Out-Stack "AppSecurityGroup"
$image = "${repo}:$Tag"
$registry = $repo.Split("/")[0]

Write-Host "== Build & push $image" -ForegroundColor Cyan
aws ecr get-login-password --region $Region | docker login --username AWS --password-stdin $registry
if ($LASTEXITCODE -ne 0) { throw "ECR login failed" }
docker build --platform linux/amd64 -t $image (Join-Path $root "backend")
if ($LASTEXITCODE -ne 0) { throw "docker build failed" }
docker push $image
if ($LASTEXITCODE -ne 0) { throw "docker push failed" }

$template = Join-Path $root "deploy/aws/app-stack.yaml"
function Deploy-Stack([string[]]$overrides) {
    # Parameters not listed keep their previous values on an existing stack.
    aws cloudformation deploy --region $Region --stack-name $StackName --template-file $template `
        --capabilities CAPABILITY_IAM --no-fail-on-empty-changeset --parameter-overrides $overrides
    if ($LASTEXITCODE -ne 0) { throw "CloudFormation update failed" }
}

Write-Host "== Phase 1: point only the migration task at the new image" -ForegroundColor Cyan
Deploy-Stack @("MigrateImageUri=$image")

Write-Host "== Run database migrations with the new image" -ForegroundColor Cyan
$taskDef = Out-Stack "MigrateTaskDefinition"
$net = "awsvpcConfiguration={subnets=[$subnets],securityGroups=[$sg],assignPublicIp=DISABLED}"
$taskArn = aws ecs run-task --region $Region --cluster $cluster --launch-type FARGATE `
    --task-definition $taskDef --network-configuration $net --query "tasks[0].taskArn" --output text
aws ecs wait tasks-stopped --region $Region --cluster $cluster --tasks $taskArn
$exit = aws ecs describe-tasks --region $Region --cluster $cluster --tasks $taskArn --query "tasks[0].containers[0].exitCode" --output text
if ($exit -ne "0") { throw "Migration task failed (exit $exit). Check log group /propman/backend (prefix 'migrate'). Web and worker were NOT updated." }

Write-Host "== Phase 2: roll web and worker services onto the new image" -ForegroundColor Cyan
Deploy-Stack @("ImageUri=$image", "MigrateImageUri=")

Write-Host "== Wait for services to stabilise" -ForegroundColor Cyan
$services = aws ecs list-services --region $Region --cluster $cluster --query "serviceArns" --output text
aws ecs wait services-stable --region $Region --cluster $cluster --services $services.Split()
Write-Host "Backend deployed: $image" -ForegroundColor Green
