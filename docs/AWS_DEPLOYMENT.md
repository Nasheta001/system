# AWS production deployment

> **Status: prepared, not deployed.** Everything in this guide has been written and checked *locally*:
> the Docker images build and pass the full test suite against PostgreSQL 17, the production-like
> Docker stack passes the end-to-end smoke test, the S3 storage code was exercised against an S3
> emulator (moto), and both CloudFormation templates pass `cfn-lint`. **None of it has been run in a
> real AWS account yet.** Expect to fix small issues on the first deployment. Rehearse in a separate
> staging account before deploying for the client.

## 1. Architecture

```
                 ┌────────────── AWS WAF (us-east-1): rate limits, managed rules, optional bot control
Browser ──HTTPS──► CloudFront (www.example.co.ke, ACM cert, security headers, HTTP→HTTPS)
                    │  /            → S3 "frontend" bucket (private, Origin Access Control)  Angular build
                    │  /media/*     → S3 "media" bucket (private, OAC)                       public property photos
                    │  /api/*, /django-admin/*, /static/*
                    ▼     + secret X-Origin-Verify header
                 ALB (HTTPS 443, only CloudFront IPs allowed) ──► ECS Fargate "web" (gunicorn, 2+ tasks, private subnets)
                                                                  ECS Fargate "worker" (1 task: reminders, charges, expiry, retries)
                                                                        │            │
                                         RDS PostgreSQL 17 (private, encrypted, TLS forced, Multi-AZ, PITR)
                                         S3 "private files" bucket (documents, signed copies; never public)
                                         Secrets Manager (app secrets, RDS-managed password, callback token)
                                         CloudWatch Logs + alarms → SNS email
Outbound (M-Pesa Daraja, Africa's Talking, SES, Cloudflare Turnstile) leaves via the NAT gateway.
```

| Concern | AWS service | Defined in |
|---|---|---|
| Frontend hosting | S3 + CloudFront (OAC, SPA rewrite function) | `deploy/aws/app-stack.yaml` |
| API & worker | ECS Fargate behind an Application Load Balancer | same |
| Database | RDS for PostgreSQL 17 | same |
| Files | S3 (public-media bucket via CloudFront; private bucket streamed by Django) | same |
| Secrets | AWS Secrets Manager → injected into containers at start | same |
| Edge protection | AWS WAF (CloudFront scope) | `deploy/aws/waf-us-east-1.yaml` |
| Email | Amazon SES (SMTP interface) | configured manually (section 6) |
| Logs & alarms | CloudWatch Logs (JSON), Container Insights, alarms → SNS | `app-stack.yaml` |
| Image registry | Amazon ECR (scan on push, immutable tags) | created once with the CLI |

Fixed monthly costs come mainly from the NAT gateway, the ALB, RDS (Multi-AZ roughly doubles the instance
price) and the Fargate tasks. Estimate them with the [AWS Pricing Calculator](https://calculator.aws/) for
your region before committing. For a small portfolio, `DBMultiAZ=false` and `WebDesiredCount=1` halve
several costs, at the price of availability.

**Region:** `af-south-1` (Cape Town) is the closest AWS region to Kenya. It is an *opt-in* region:
enable it under Account → AWS Regions first. `eu-west-1` (Ireland) is an alternative. CloudFront
certificates and the CloudFront WAF must always be in **us-east-1**, whatever region you choose.

## 2. Prerequisites

- An AWS account with an administrator user/role for the deployment, MFA enabled. Use a separate
  account (or at least a separate stack) for staging.
- AWS CLI v2 configured (`aws configure sso` or access keys of a deployment role), Docker Desktop, Node 22.
- A domain you control, e.g. `www.example.co.ke` (registrar DNS or Route 53).
- Credentials you will add later: Safaricom Daraja (production), SES SMTP, Africa's Talking, optionally
  Meta WhatsApp and Cloudflare Turnstile.

## 3. First deployment, step by step

All commands are PowerShell. Replace `af-south-1`, `propman`, the domain and the account id.

### 3.1 Certificates (ACM)
```powershell
# CloudFront certificate - MUST be us-east-1
aws acm request-certificate --region us-east-1 --domain-name www.example.co.ke --validation-method DNS
# ALB certificate - in your application region (CloudFront forwards the Host header, so the ALB must present this name)
aws acm request-certificate --region af-south-1 --domain-name www.example.co.ke --validation-method DNS
```
Add the DNS validation CNAME records shown by `aws acm describe-certificate` and wait for status `ISSUED`.

### 3.2 WAF (us-east-1)
```powershell
aws cloudformation deploy --region us-east-1 --stack-name propman-waf `
  --template-file deploy\aws\waf-us-east-1.yaml --parameter-overrides EnableBotControl=false
aws cloudformation describe-stacks --region us-east-1 --stack-name propman-waf --query "Stacks[0].Outputs"
```

### 3.3 Container registry and first image
```powershell
aws ecr create-repository --region af-south-1 --repository-name propman-backend `
  --image-scanning-configuration scanOnPush=true --image-tag-mutability IMMUTABLE --encryption-configuration encryptionType=AES256
$repo = "123456789012.dkr.ecr.af-south-1.amazonaws.com/propman-backend"
aws ecr get-login-password --region af-south-1 | docker login --username AWS --password-stdin $repo.Split("/")[0]
docker build --platform linux/amd64 -t "${repo}:v1" .\backend
docker push "${repo}:v1"
```

### 3.4 Look up the CloudFront prefix list (lets only CloudFront reach the ALB)
```powershell
aws ec2 describe-managed-prefix-lists --region af-south-1 `
  --filters Name=prefix-list-name,Values=com.amazonaws.global.cloudfront.origin-facing --query "PrefixLists[0].PrefixListId"
```

### 3.5 Create the application stack (with zero containers)
```powershell
aws cloudformation deploy --region af-south-1 --stack-name propman --template-file deploy\aws\app-stack.yaml `
  --capabilities CAPABILITY_IAM --parameter-overrides `
    DomainName=www.example.co.ke `
    CloudFrontCertificateArn=arn:aws:acm:us-east-1:123456789012:certificate/... `
    AlbCertificateArn=arn:aws:acm:af-south-1:123456789012:certificate/... `
    WebAclArn=arn:aws:wafv2:us-east-1:123456789012:global/webacl/propman-cloudfront/... `
    CloudFrontPrefixListId=pl-xxxxxxxx `
    ImageUri="${repo}:v1" `
    AlertEmail=ops@example.co.ke `
    WebDesiredCount=0 WorkerDesiredCount=0 MpesaMode=disabled
```
This takes 20–40 minutes (RDS and CloudFront). Confirm the SNS email subscription you receive.

### 3.6 Fill in the secrets
`propman/app` is created with a generated `DJANGO_SECRET_KEY` and placeholders. Containers **refuse to
start** while `FIELD_ENCRYPTION_KEYS` is not a valid key, which protects against running without encryption.
```powershell
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"   # keep a copy offline!
```
In the Secrets Manager console, edit `propman/app` and set `FIELD_ENCRYPTION_KEYS`. Add SES and other
provider credentials whenever you have them. **Losing the encryption key makes encrypted ID numbers
unrecoverable**, so store a copy in the company's password manager or vault.

### 3.7 Migrate the database and create the first administrator
```powershell
$out = aws cloudformation describe-stacks --region af-south-1 --stack-name propman --query "Stacks[0].Outputs" | ConvertFrom-Json
$o = @{}; $out | ForEach-Object { $o[$_.OutputKey] = $_.OutputValue }
$net = "awsvpcConfiguration={subnets=[$($o.PrivateSubnets)],securityGroups=[$($o.AppSecurityGroup)],assignPublicIp=DISABLED}"
aws ecs run-task --region af-south-1 --cluster $o.ClusterName --launch-type FARGATE `
  --task-definition $o.MigrateTaskDefinition --network-configuration $net
# wait for it to stop with exit code 0 (CloudWatch log group /propman/backend, prefix "migrate")

# start the services
aws cloudformation deploy --region af-south-1 --stack-name propman --template-file deploy\aws\app-stack.yaml `
  --capabilities CAPABILITY_IAM --parameter-overrides WebDesiredCount=2 WorkerDesiredCount=1

# create the first administrator interactively (requires the Session Manager plugin for the AWS CLI)
$task = aws ecs list-tasks --region af-south-1 --cluster $o.ClusterName --service-name $o.WebServiceName --query "taskArns[0]" --output text
aws ecs execute-command --region af-south-1 --cluster $o.ClusterName --task $task --container app --interactive `
  --command "python manage.py createsuperuser"
```
Never run `seed_demo` in production. There is no public registration: after the first administrator,
everyone joins by invitation (*Staff & access → Invite staff member*; tenants from their tenant page once they
have a current tenancy). Invitations are sent by email, so configure SES (section on email) **before**
inviting people. With `DEBUG=false` the invite link is never shown on screen. Leave `SETUP_TOKEN` unset in
production, which disables the website setup page; `createsuperuser` above is the intended path.

### 3.8 Frontend and DNS
```powershell
powershell -ExecutionPolicy Bypass -File scripts\aws\deploy-frontend.ps1 -Region af-south-1 -StackName propman
```
Create a CNAME (or Route 53 alias) from `www.example.co.ke` to the `CloudFrontDomain` output.

### 3.9 Verify
- `https://www.example.co.ke/api/health/` → `{"status":"ok"}`
- `https://www.example.co.ke/api/health/ready/` → database `ok`, migrations `ok`, cache `ok`, worker `ok`
  (about 5 minutes after the worker starts).
- Calling the ALB DNS name directly returns **403** (the origin-verify header is missing).
- `http://` redirects to `https://`. Security headers are present (check securityheaders.com).
- Sign in as the administrator, create a property, upload a photo (S3 media) and a document
  (S3 private), and record a payment and download the receipt.
- Settings → Channels shows which integrations are live.

## 4. Subsequent releases
```powershell
cd backend; .\.venv\Scripts\python.exe manage.py test tests; cd ..
powershell -ExecutionPolicy Bypass -File scripts\security-scan.ps1
powershell -ExecutionPolicy Bypass -File scripts\aws\deploy-backend.ps1 -Region af-south-1 -StackName propman -RepositoryUri $repo
powershell -ExecutionPolicy Bypass -File scripts\aws\deploy-frontend.ps1 -Region af-south-1 -StackName propman
```
`deploy-backend.ps1` builds and pushes an immutable tag, then:
1. points only the migration task at the new image and runs migrations;
2. stops if migrations fail, so the web and worker services keep running the old image;
3. otherwise rolls web and worker onto the new image. ECS uses rolling deployments with
   circuit-breaker rollback, so unhealthy releases revert automatically.

Write migrations that are backwards-compatible with the previous release ("expand, then contract"), because
old containers keep serving traffic while the migration runs. Take a manual RDS snapshot before risky
migrations: `aws rds create-db-snapshot --db-instance-identifier <id> --db-snapshot-identifier pre-release-<date>`.

## 5. Configuration reference

| Setting | Where it comes from in AWS |
|---|---|
| `DJANGO_DEBUG=false`, `SECURE_HTTPS=true`, `DJANGO_ALLOWED_HOSTS`, `CSRF_TRUSTED_ORIGINS`, `FRONTEND_URL` | Task definition (from `DomainName`) |
| `DB_HOST/PORT/NAME/USER`, `DB_SSL_REQUIRE=true` | Task definition (RDS endpoint) |
| `DB_PASSWORD` | RDS-managed secret (rotatable by RDS) |
| `DJANGO_SECRET_KEY`, `FIELD_ENCRYPTION_KEYS`, provider keys | `propman/app` secret |
| `ORIGIN_VERIFY_SECRET` | `propman/origin-verify` (also sent by CloudFront) |
| `MPESA_CALLBACK_TOKEN` | `propman/mpesa-callback-token` |
| `STORAGE_BACKEND=s3`, bucket names, `AWS_S3_CUSTOM_DOMAIN` | Task definition |
| `CACHE_BACKEND=db` | Task definition (`createcachetable` runs in the migrate task) |
| `NUM_PROXIES=2` | Task definition (CloudFront + ALB) |
| `LOG_FORMAT=json` | Image default |
| AWS credentials | **None.** The ECS task role grants S3/SES access; no access keys exist anywhere |

Secrets are read when a container starts. After changing a secret, force a new deployment:
`aws ecs update-service --cluster <c> --service <s> --force-new-deployment`.

## 6. PostgreSQL, static files, media, CORS, HTTPS, hosts

**PostgreSQL (RDS):** version 17 (`DBEngineVersion` parameter), gp3 storage with autoscaling to 500 GB,
encryption at rest (KMS), `rds.force_ssl=1` with Django connecting `sslmode=require`, private subnets
only, reachable only from the app security group, Multi-AZ, deletion protection, Performance Insights,
and slow-query logging (more than 1 s) to CloudWatch. Django keeps connections open for 60 s
(`DB_CONN_MAX_AGE`) with health checks. Three web tasks × 3 gunicorn workers fit easily within a
`db.t4g.small` connection limit. Add RDS Proxy if you scale far beyond that.

**Migrations:** always through the `migrate` task (section 3.7 / `deploy-backend.ps1`). That task runs
`migrate`, `createcachetable` and `setup_defaults`, and is safe to run repeatedly.

**Static files** (Django admin and API-docs assets) are collected into the image at build time, served by
WhiteNoise with hashed names, and cached by CloudFront under `/static/*`.

**Uploaded media:** property photos go to the media bucket under `media/` and are served at
`https://<domain>/media/...` through CloudFront (Origin Access Control: the bucket itself is private).
Documents, signed copies and attachments go to the private bucket under `private/`, encrypted at rest;
Django streams them only after permission checks. The private bucket is versioned (deleted or overwritten
files are recoverable for 90 days) and rejects non-TLS access. The ECS task role can only touch those two
prefixes.

**CORS:** not needed and not enabled. The browser talks to a single origin (CloudFront serves both the app
and `/api`). Leave `CORS_ALLOWED_ORIGINS` empty unless you deliberately host the frontend on another domain.

**HTTPS:** TLS 1.2+ at CloudFront (ACM, `TLSv1.2_2021`), CloudFront → ALB over HTTPS
(`ELBSecurityPolicy-TLS13-1-2-2021-06`), and HTTP → HTTPS redirect. Django sets HSTS (1 year), secure
`__Host-` session cookies, a secure CSRF cookie and `SECURE_SSL_REDIRECT`. Health checks are exempt from
the redirect. HSTS preload is opt-in (`SECURE_HSTS_PRELOAD=true`) because it is hard to undo.

**Allowed hosts:** only `DomainName`. ALB and container health probes (which use IP addresses as Host) are
answered by a middleware before host validation, so no wildcard is needed.

## 7. M-Pesa in production

1. Complete Safaricom's go-live process for your paybill/till and obtain the **production** consumer
   key/secret, passkey and shortcode.
2. Put the key, secret and passkey in `propman/app`. Update the stack with `MpesaMode=production`,
   `MpesaShortcode=<your paybill/till>` and, for a till, `MpesaTransactionType=CustomerBuyGoodsOnline`.
3. The callback URL sent with every STK request is
   `https://<domain>/api/payments/mpesa/callback/<propman/mpesa-callback-token>/`. It needs a public,
   valid HTTPS certificate, which CloudFront provides.
4. Ask Safaricom for their current callback source IP ranges and set `MpesaAllowedCallbackIps`. Django
   reads the real client IP through the two trusted proxies (`NUM_PROXIES=2`), so a spoofed
   `X-Forwarded-For` cannot bypass the allow-list.
5. Defence in depth already in place: secret path token (constant-time compare), optional IP allow-list,
   CheckoutRequestID must match a request we created, **STK Query confirmation before crediting**, amount
   check, unique receipt numbers, row locks and idempotent processing. Late successes are still credited.
   The WAF bot rule excludes the callback path.
6. If you enable CloudFront or ALB access logs, the callback token appears in them. Treat those logs as
   sensitive. To rotate the token, change the secret and redeploy; pending STK requests made with the old
   URL will then fail and be reconciled by the worker's STK query.
7. **Test before go-live:** run the stack with `MpesaMode=sandbox` and Daraja sandbox credentials first,
   make test payments, and confirm the payment, receipt and notification flow end to end.

## 8. Background jobs and scheduled reminders

The `worker` ECS service runs exactly one container: `python manage.py run_worker`, every 5 minutes. Each
run creates monthly charges, expires reservations, publishes scheduled notices, sends due rent reminders
(once per tenancy, due date and step; they stop when paid), reconciles pending M-Pesa transactions and
retries failed notifications. Every step is idempotent, so an extra or missed run is harmless. Each run
writes a heartbeat that `/api/health/ready/` reports as `worker: ok|stale`.

Alternative for very low cost: set `WorkerDesiredCount=0` and create an **EventBridge Scheduler** rule that
runs the migrate task definition with command override `["jobs-once"]` every 5–15 minutes.

## 9. Logging and monitoring

- All containers log JSON lines to CloudWatch log group `/propman/backend` (`web/`, `worker/`, `migrate/`
  streams), kept for 90 days (`LogRetentionDays`). Gunicorn access logs are included.
- Useful Logs Insights queries:
  ```
  fields @timestamp, level, logger, message | filter level = "ERROR" | sort @timestamp desc | limit 50
  fields @timestamp, message | filter logger = "billing.mpesa" | sort @timestamp desc
  fields @timestamp, message | filter message like /Jobs complete/ | sort @timestamp desc | limit 20
  ```
- Alarms (email via SNS): ALB 5xx ≥ 10 in 5 min, no healthy API tasks, RDS CPU > 80 %, RDS free storage
  < 5 GB, and application errors ≥ 5 in 5 min (metric filter on `level = ERROR`).
- In-app: the audit log (who changed what), the notification log (delivery failures) and
  Settings → Channels.

## 10. Backups and recovery

| What | How | Recovery point |
|---|---|---|
| Database | RDS automated backups, `DBBackupRetentionDays` (default 14), point-in-time recovery | ~5 minutes |
| Database before releases | Manual snapshot (section 4) | at snapshot |
| Database, deleted stack | `DeletionPolicy: Snapshot` takes a final snapshot | at deletion |
| Private files and photos | S3 versioning (previous versions kept 90 days in the private bucket); buckets retained if the stack is deleted | any version |
| Disaster in a region (optional) | Copy snapshots cross-region (`aws rds copy-db-snapshot`) and enable S3 cross-region replication | depends |

**Restore runbook: point-in-time** (rehearse in staging before go-live):
1. `aws rds restore-db-instance-to-point-in-time --source-db-instance-identifier <id> --target-db-instance-identifier propman-restore --restore-time 2026-10-12T08:00:00Z --db-subnet-group-name <subnet group> --vpc-security-group-ids <db sg>`
2. Inspect the restored data (connect from an ECS Exec session with `psql`, or run `manage shell`).
3. To switch the application to it, either copy the needed rows back, or replace the stack's database: take a
   snapshot of the restored instance and update `app-stack.yaml` with
   `DBSnapshotIdentifier: <snapshot>` on `Database`. CloudFormation then replaces the instance; the
   `DB_HOST` environment variable follows automatically. Scale the services to 0 while you do this.
4. Run the migrate task, scale back up, and check `/api/health/ready/`.

**Files:** restore a previous object version in the S3 console, or with
`aws s3api list-object-versions` and `copy-object`.

Also keep the `FIELD_ENCRYPTION_KEYS` value backed up outside AWS. A restored database is useless without it.

## 11. Health checks

| Endpoint | Purpose | Used by |
|---|---|---|
| `GET /api/health/` | Liveness: the process is up. No database access, no host check | ALB target group, container `HEALTHCHECK`, ECS |
| `GET /api/health/ready/` | Readiness: database reachable, no pending migrations, cache works (+ worker heartbeat, informational). Returns 503 if a dependency is down; only coarse statuses, no versions or hosts | Release verification, uptime monitor (e.g. Route 53 health check) |

## 12. What is still needed before going live

- An AWS account, domain, ACM certificates and a first real deployment (staging first). **Not done.**
- Daraja production credentials and Safaricom go-live approval; testing with sandbox on AWS. **Not done.**
- SES: verify the sending domain (DKIM/SPF/DMARC), request production access (leave the SES sandbox),
  create SMTP credentials and store them in `propman/app`, then set `NotifyEmailEnabled=true`. **Not done.**
- Africa's Talking / WhatsApp production credentials (and Meta-approved templates). **Not done.**
- Optional Turnstile keys. The server-side check was verified against Cloudflare's official test keys.
- A restore rehearsal, a load test at expected traffic, and a review of the costs.
