# Secrets Detection System - Operations Runbook

## Table of Contents
1. [Architecture Overview](#architecture-overview)
2. [Signature Verification](#signature-verification)
3. [Incident Response Procedures](#incident-response-procedures)
4. [Manual Key Rotation](#manual-key-rotation)
5. [Troubleshooting](#troubleshooting)
6. [IAM Permissions](#iam-permissions)
7. [Emergency Contacts](#emergency-contacts)

---

## Architecture Overview

### System Components

```
GitHub Repository
       |
       | HTTPS POST (webhook)
       | X-Hub-Signature-256 header
       v
API Gateway (/github-webhook)
       |
       | Proxy Integration
       v
Lambda Function (secrets-detector-lambda)
       |
       ├─> IAM API (list users, keys, deactivate)
       |
       └─> SNS Topic (secrets-detection-alerts)
            |
            ├─> Email subscribers
            ├─> Slack/PagerDuty (via subscription)
            └─> CloudWatch Logs
```

### Data Flow

1. **GitHub Event**: Developer pushes commits to repository
2. **Webhook Trigger**: GitHub sends POST request to API Gateway with commit data and HMAC signature
3. **Signature Verification**: Lambda validates X-Hub-Signature-256 using GITHUB_WEBHOOK_SECRET
4. **Content Scanning**: Lambda searches commit messages, file names, and diffs for AWS access key pattern (AKIA...)
5. **Key Identification**: For each detected key, Lambda queries IAM to find owner
6. **Automatic Remediation**: Lambda sets key Status='Inactive' via IAM API
7. **Alert Generation**: Lambda publishes detailed alert to SNS topic
8. **Response**: Lambda returns HTTP 200 to GitHub (prevents webhook retry)

### Key Features

- **Real-time Detection**: Scans commits as they are pushed
- **Automatic Deactivation**: Immediately disables compromised keys
- **Signature Verification**: Validates webhook authenticity using HMAC SHA-256
- **Comprehensive Alerting**: SNS notifications with full context
- **Audit Trail**: All actions logged to CloudWatch

---

## Signature Verification

### How It Works

GitHub webhook signature verification uses HMAC (Hash-based Message Authentication Code) with SHA-256:

1. GitHub generates signature:
   ```
   signature = HMAC-SHA256(secret, request_body)
   X-Hub-Signature-256: sha256=<hex_digest>
   ```

2. Lambda recomputes signature using same secret and compares:
   ```python
   computed = hmac.new(secret, body, sha256).hexdigest()
   is_valid = hmac.compare_digest(computed, received)
   ```

3. Constant-time comparison prevents timing attacks

### Configuring GitHub Webhook Secret

#### Initial Setup

1. **Generate strong secret** (recommended: 32+ random characters):
   ```bash
   openssl rand -hex 32
   ```

2. **Store in AWS Systems Manager Parameter Store**:
   ```bash
   aws ssm put-parameter \
     --name "/secrets-detector/webhook-secret" \
     --value "YOUR_GENERATED_SECRET" \
     --type "SecureString" \
     --description "GitHub webhook HMAC secret"
   ```

3. **Update Lambda environment variable**:
   - Navigate to Lambda console → secrets-detector-lambda
   - Configuration → Environment variables
   - Edit GITHUB_WEBHOOK_SECRET
   - Or via CLI:
   ```bash
   aws lambda update-function-configuration \
     --function-name secrets-detector-lambda \
     --environment "Variables={SNS_TOPIC_ARN=<arn>,GITHUB_WEBHOOK_SECRET=<secret>}"
   ```

4. **Configure in GitHub**:
   - Repository → Settings → Webhooks → Add webhook
   - Payload URL: `https://<api-id>.execute-api.<region>.amazonaws.com/Prod/github-webhook`
   - Content type: `application/json`
   - Secret: `<paste your generated secret>`
   - Events: Select "Just the push event"
   - Active: ✓

#### Rotating the Secret

**Frequency**: Rotate every 90 days or immediately if compromised

**Procedure**:

1. Generate new secret (as above)
2. Update GitHub webhook with new secret first
3. Update Lambda environment variable with new secret
4. Verify next webhook delivery succeeds (check GitHub webhook Recent Deliveries)
5. Document rotation in change log

**WARNING**: Update GitHub before Lambda to avoid failed deliveries during rotation window.

---

## Incident Response Procedures

### Detection Alert Received

When you receive an SNS alert about a detected key, follow this procedure:

#### Phase 1: Immediate Assessment (0-5 minutes)

1. **Read the alert** carefully:
   - Note the Access Key ID
   - Note the owner (IAM username)
   - Note action taken (DEACTIVATED, KEY_NOT_FOUND_IN_IAM, etc.)
   - Note commit information (repository, pusher, commit SHA)

2. **Check Lambda CloudWatch logs**:
   ```bash
   aws logs tail /aws/lambda/secrets-detector-lambda --follow
   ```
   - Verify the key was actually deactivated
   - Look for any errors during deactivation

3. **Verify key status in IAM**:
   ```bash
   aws iam list-access-keys --user-name <USERNAME>
   ```
   - Confirm key shows Status: Inactive

#### Phase 2: Impact Assessment (5-15 minutes)

1. **Check CloudTrail for unauthorized usage**:
   ```bash
   aws cloudtrail lookup-events \
     --lookup-attributes AttributeKey=AccessKeyId,AttributeValue=<KEY_ID> \
     --start-time $(date -u -d '24 hours ago' +%Y-%m-%dT%H:%M:%S) \
     --max-results 50
   ```
   
   Look for:
   - API calls from unexpected IP addresses
   - High-cost operations (EC2 launches, data transfers)
   - Privilege escalation attempts
   - Data exfiltration (S3 GetObject, etc.)

2. **Review commit history**:
   ```bash
   git log --all --full-history --source --grep="<KEY_ID>"
   git log --all --full-history -S "<KEY_ID>"
   ```
   - Determine when key was first committed
   - Check if key exists in other branches
   - Verify if repository is public or private

3. **Assess application impact**:
   - Identify which applications use this key
   - Check application logs for authentication failures
   - Determine if services are degraded

#### Phase 3: Remediation (15-60 minutes)

1. **Generate replacement key** (if legitimate exposure):
   ```bash
   aws iam create-access-key --user-name <USERNAME>
   ```
   - Save AccessKeyId and SecretAccessKey securely

2. **Update application configuration**:
   - **For SSM/Secrets Manager**:
     ```bash
     aws ssm put-parameter \
       --name "/app/prod/AWS_ACCESS_KEY_ID" \
       --value "<NEW_KEY_ID>" \
       --type "SecureString" \
       --overwrite
     
     aws ssm put-parameter \
       --name "/app/prod/AWS_SECRET_ACCESS_KEY" \
       --value "<NEW_SECRET_KEY>" \
       --type "SecureString" \
       --overwrite
     ```
   
   - **For ECS/Fargate**: Update task definition with new secrets
   - **For EC2**: Update user data or configuration management
   - **For local development**: Rotate ~/.aws/credentials

3. **Restart affected services**:
   ```bash
   # Example for ECS:
   aws ecs update-service \
     --cluster <cluster> \
     --service <service> \
     --force-new-deployment
   ```

4. **Verify service restoration**:
   - Check application health endpoints
   - Monitor error rates
   - Test critical functionality

#### Phase 4: Repository Cleanup (1-2 hours)

1. **Remove key from current commit**:
   ```bash
   git checkout <branch>
   # Edit files to remove key
   git add <files>
   git commit -m "fix: remove exposed credentials"
   git push origin <branch>
   ```

2. **Remove from git history** (if key was committed to main/protected branches):
   
   **WARNING**: This rewrites history. Coordinate with team first.
   
   ```bash
   # Using git-filter-repo (recommended)
   pip install git-filter-repo
   git filter-repo --replace-text <(echo "AKIA1111111111111111==>REDACTED")
   
   # Or using BFG Repo-Cleaner
   java -jar bfg.jar --replace-text replacements.txt <repo>
   ```

3. **Force push** (if history was rewritten):
   ```bash
   git push --force --all origin
   git push --force --tags origin
   ```

4. **Notify team**:
   - Send email about force push
   - Team members must re-clone or reset branches

#### Phase 5: Delete Old Key (after verification)

**WAIT 24-48 HOURS** to ensure no lingering issues, then:

```bash
aws iam delete-access-key \
  --user-name <USERNAME> \
  --access-key-id <OLD_KEY_ID>
```

#### Phase 6: Post-Incident Review (1 week later)

1. Document incident:
   - Timeline of events
   - Root cause analysis
   - Blast radius
   - Response effectiveness

2. Identify improvements:
   - Developer training needs
   - Pre-commit hooks
   - Additional security controls

3. Update runbook with lessons learned

---

## Manual Key Rotation

### Scheduled Rotation (Best Practice)

Rotate IAM access keys every 90 days as a security best practice.

### Procedure

#### Step 1: Create New Key

```bash
# List current keys
aws iam list-access-keys --user-name <USERNAME>

# Create new key
aws iam create-access-key --user-name <USERNAME> > new-key.json

# Extract credentials
cat new-key.json | jq -r '.AccessKey.AccessKeyId'
cat new-key.json | jq -r '.AccessKey.SecretAccessKey'

# Immediately secure or delete the file
shred -u new-key.json  # Linux
rm -P new-key.json      # macOS
```

#### Step 2: Update Configuration

Choose the appropriate method for your deployment:

**A. AWS Systems Manager Parameter Store**:
```bash
aws ssm put-parameter \
  --name "/app/prod/AWS_ACCESS_KEY_ID" \
  --value "<NEW_KEY_ID>" \
  --type "SecureString" \
  --overwrite

aws ssm put-parameter \
  --name "/app/prod/AWS_SECRET_ACCESS_KEY" \
  --value "<NEW_SECRET_KEY>" \
  --type "SecureString" \
  --overwrite
```

**B. AWS Secrets Manager**:
```bash
aws secretsmanager update-secret \
  --secret-id app/prod/aws-credentials \
  --secret-string '{"access_key":"<NEW_KEY_ID>","secret_key":"<NEW_SECRET_KEY>"}'
```

**C. Environment Variables** (for local dev):
```bash
# Update ~/.aws/credentials
aws configure set aws_access_key_id <NEW_KEY_ID>
aws configure set aws_secret_access_key <NEW_SECRET_KEY>
```

#### Step 3: Deploy Changes

**ECS/Fargate**:
```bash
aws ecs update-service \
  --cluster <cluster> \
  --service <service> \
  --force-new-deployment
```

**Lambda**:
```bash
aws lambda update-function-configuration \
  --function-name <function> \
  --environment "Variables={KEY=VALUE,...}"
```

**EC2** (using Systems Manager):
```bash
aws ssm send-command \
  --document-name "AWS-RunShellScript" \
  --targets "Key=tag:Name,Values=<instance-tag>" \
  --parameters 'commands=["sudo systemctl restart app"]'
```

#### Step 4: Verify New Key Works

```bash
# Test with new credentials
export AWS_ACCESS_KEY_ID=<NEW_KEY_ID>
export AWS_SECRET_ACCESS_KEY=<NEW_SECRET_KEY>

# Simple test
aws sts get-caller-identity

# Application-specific tests
curl https://app/health
```

Monitor application logs for 1-2 hours to ensure no authentication errors.

#### Step 5: Deactivate Old Key

```bash
aws iam update-access-key \
  --user-name <USERNAME> \
  --access-key-id <OLD_KEY_ID> \
  --status Inactive
```

**WAIT 24-48 HOURS** before deletion to catch any missed usage.

#### Step 6: Delete Old Key

```bash
aws iam delete-access-key \
  --user-name <USERNAME> \
  --access-key-id <OLD_KEY_ID>
```

---

## Troubleshooting

### Lambda Not Detecting Keys

**Symptoms**: Known key in commit, but no alert received

**Checks**:

1. **Verify webhook delivery**:
   - GitHub: Repository → Settings → Webhooks → Recent Deliveries
   - Look for green checkmark (2xx response)
   - Click on delivery to see request/response

2. **Check Lambda logs**:
   ```bash
   aws logs tail /aws/lambda/secrets-detector-lambda --follow
   ```
   - Look for "No AWS access keys detected"
   - Verify commit data was parsed correctly

3. **Verify key pattern**:
   - Pattern: `AKIA[0-9A-Z]{16}`
   - Must be exactly 20 characters total
   - Test regex: `echo "AKIA1111111111111111" | grep -P 'AKIA[0-9A-Z]{16}'`

4. **Check Lambda environment**:
   ```bash
   aws lambda get-function-configuration \
     --function-name secrets-detector-lambda \
     --query 'Environment'
   ```

### Signature Verification Failing

**Symptoms**: Alert "Webhook Signature Verification Failed"

**Causes & Solutions**:

1. **Secret mismatch**:
   - Verify GitHub webhook secret matches GITHUB_WEBHOOK_SECRET in Lambda
   - Re-enter secret in GitHub (ensure no extra spaces)

2. **Body transformation**:
   - API Gateway must use Lambda Proxy Integration
   - Check template.yaml: Events → Type: Api (NOT HttpApi)

3. **Header case sensitivity**:
   - Lambda looks for both `X-Hub-Signature-256` and `x-hub-signature-256`
   - Check CloudWatch logs for "Signature header present: false"

4. **Encoding issues**:
   - Webhook body must be raw string (not base64-encoded)
   - Verify: `event.get('body')` should start with `{` not `eyJ...`

**Debug**:
```bash
# Check recent webhook deliveries in GitHub
# Copy request body and signature
# Test locally:
echo -n '<body>' | openssl dgst -sha256 -hmac '<secret>'
# Compare with X-Hub-Signature-256 value
```

### SNS Alerts Not Received

**Symptoms**: Lambda processes keys but no SNS notifications

**Checks**:

1. **Verify SNS_TOPIC_ARN**:
   ```bash
   aws lambda get-function-configuration \
     --function-name secrets-detector-lambda \
     --query 'Environment.Variables.SNS_TOPIC_ARN'
   ```

2. **Check SNS topic exists**:
   ```bash
   aws sns get-topic-attributes --topic-arn <ARN>
   ```

3. **Verify subscriptions**:
   ```bash
   aws sns list-subscriptions-by-topic --topic-arn <ARN>
   ```
   - Ensure subscription status is "Confirmed"
   - Check email spam folder for confirmation

4. **Test SNS manually**:
   ```bash
   aws sns publish \
     --topic-arn <ARN> \
     --subject "Test Alert" \
     --message "Test message"
   ```

5. **Check Lambda permissions**:
   ```bash
   aws lambda get-policy --function-name secrets-detector-lambda
   ```
   - Should include `sns:Publish` action

### Key Deactivation Failed

**Symptoms**: Alert says "DEACTIVATION_FAILED"

**Causes**:

1. **Insufficient IAM permissions**:
   - Lambda role needs `iam:UpdateAccessKey`
   - Check: CloudWatch logs for "AccessDenied" errors

2. **Key already deleted**:
   - Key may have been manually deleted
   - Check: `aws iam list-access-keys --user-name <USER>`

3. **IAM user deleted**:
   - User account no longer exists
   - Not a critical issue if user is gone

**Resolution**:
```bash
# Verify Lambda role permissions
aws iam get-role-policy \
  --role-name <lambda-role> \
  --policy-name <policy-name>

# Should include:
# "Action": ["iam:UpdateAccessKey"]
# "Resource": "*"
```

### API Gateway 403/500 Errors

**Symptoms**: GitHub webhook shows red X with error code

**403 Forbidden**:
- Check API Gateway API key requirements (should be none for webhooks)
- Verify API Gateway resource policy allows public access

**500 Internal Server Error**:
- Check Lambda execution errors in CloudWatch
- Verify Lambda has correct handler: `handler.handler`
- Check for Python syntax errors:
  ```bash
  python -m py_compile lambda_detector/handler.py
  ```

**502 Bad Gateway**:
- Lambda timeout (increase from 10s to 30s if needed)
- Lambda runtime error (check CloudWatch logs)

### CloudWatch Logs Not Appearing

**Checks**:

1. **Verify log group exists**:
   ```bash
   aws logs describe-log-groups \
     --log-group-name-prefix "/aws/lambda/secrets-detector"
   ```

2. **Check Lambda permissions**:
   - Lambda execution role needs `logs:CreateLogStream` and `logs:PutLogEvents`

3. **Create log group manually** (if missing):
   ```bash
   aws logs create-log-group \
     --log-group-name /aws/lambda/secrets-detector-lambda
   ```

---

## IAM Permissions

### Lambda Execution Role

The Lambda function requires the following permissions:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "CloudWatchLogs",
      "Effect": "Allow",
      "Action": [
        "logs:CreateLogGroup",
        "logs:CreateLogStream",
        "logs:PutLogEvents"
      ],
      "Resource": "arn:aws:logs:*:*:log-group:/aws/lambda/secrets-detector-lambda:*"
    },
    {
      "Sid": "ReadWebhookSecret",
      "Effect": "Allow",
      "Action": [
        "ssm:GetParameter",
        "ssm:GetParameters"
      ],
      "Resource": "arn:aws:ssm:<REGION>:<ACCOUNT_ID>:parameter/secrets-detector/*"
    },
    {
      "Sid": "IAMKeyManagement",
      "Effect": "Allow",
      "Action": [
        "iam:ListUsers",
        "iam:ListAccessKeys",
        "iam:UpdateAccessKey"
      ],
      "Resource": "*"
    },
    {
      "Sid": "PublishAlerts",
      "Effect": "Allow",
      "Action": [
        "sns:Publish"
      ],
      "Resource": "arn:aws:sns:<REGION>:<ACCOUNT_ID>:secrets-detection-alerts"
    }
  ]
}
```

**NOTE**: `Resource: "*"` for IAM actions is broad and should be narrowed for production:

```json
{
  "Sid": "IAMKeyManagementNarrowed",
  "Effect": "Allow",
  "Action": [
    "iam:ListUsers",
    "iam:ListAccessKeys",
    "iam:UpdateAccessKey"
  ],
  "Resource": [
    "arn:aws:iam::<ACCOUNT_ID>:user/app/*",
    "arn:aws:iam::<ACCOUNT_ID>:user/service/*"
  ]
}
```

This restricts actions to users under specific paths.

### Application IAM Role (for reading secrets from SSM)

Applications that retrieve secrets from SSM need:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "ssm:GetParameter",
        "ssm:GetParameters",
        "ssm:GetParametersByPath"
      ],
      "Resource": [
        "arn:aws:ssm:<REGION>:<ACCOUNT_ID>:parameter/app/prod/*",
        "arn:aws:ssm:<REGION>:<ACCOUNT_ID>:parameter/app/staging/*"
      ]
    },
    {
      "Effect": "Allow",
      "Action": [
        "kms:Decrypt"
      ],
      "Resource": "arn:aws:kms:<REGION>:<ACCOUNT_ID>:key/<KMS_KEY_ID>",
      "Condition": {
        "StringEquals": {
          "kms:ViaService": "ssm.<REGION>.amazonaws.com"
        }
      }
    }
  ]
}
```

**Temporary Policy for Testing**: The IAM policy in the current template.yaml uses `Resource: "*"` which is acceptable for initial testing but MUST be scoped down before production deployment.

---

## Emergency Contacts

### On-Call Rotation

| Role | Primary | Secondary | Escalation |
|------|---------|-----------|------------|
| **Security Engineer** | [Name] [Phone] | [Name] [Phone] | [Name] [Phone] |
| **DevOps Lead** | [Name] [Phone] | [Name] [Phone] | [Name] [Phone] |
| **Infrastructure** | [Name] [Phone] | [Name] [Phone] | [Name] [Phone] |

### Communication Channels

- **Slack**: #security-incidents
- **PagerDuty**: Security Team
- **Email**: security@company.com

### Escalation Path

1. **P1 (Critical)**: Active credential compromise with evidence of unauthorized usage
   - Notify: Security Engineer + DevOps Lead immediately
   - Escalate to: CISO within 15 minutes

2. **P2 (High)**: Credential exposure detected, no evidence of unauthorized usage
   - Notify: Security Engineer (on-call)
   - Escalate to: DevOps Lead if key cannot be rotated within 1 hour

3. **P3 (Medium)**: False positive or test key detected
   - Document in ticket
   - Review during business hours

---

## Maintenance Checklist

### Daily
- [ ] Monitor SNS alerts for any new detections
- [ ] Check Lambda error rate in CloudWatch

### Weekly
- [ ] Review CloudWatch logs for any anomalies
- [ ] Verify webhook deliveries in GitHub (spot check)
- [ ] Confirm SNS subscriptions are active

### Monthly
- [ ] Review and update this runbook
- [ ] Test synthetic payload: `sam local invoke --event tests/synthetic_payload.json`
- [ ] Audit IAM users and their access keys
- [ ] Review CloudTrail for any suspicious IAM activity

### Quarterly
- [ ] Rotate GITHUB_WEBHOOK_SECRET
- [ ] Review and tighten IAM policies
- [ ] Conduct tabletop exercise for key exposure scenario
- [ ] Update team contact information

---

## Useful Commands Reference

```bash
# Lambda Management
aws lambda list-functions --query 'Functions[?contains(FunctionName, `secrets`)]'
aws lambda get-function --function-name secrets-detector-lambda
aws lambda invoke --function-name secrets-detector-lambda --payload file://tests/synthetic_payload.json response.json

# CloudWatch Logs
aws logs tail /aws/lambda/secrets-detector-lambda --follow --format short
aws logs filter-log-events --log-group-name /aws/lambda/secrets-detector-lambda --filter-pattern "ERROR"

# IAM Key Management
aws iam list-users
aws iam list-access-keys --user-name <USERNAME>
aws iam get-access-key-last-used --access-key-id <KEY_ID>
aws iam update-access-key --user-name <USER> --access-key-id <KEY> --status Inactive

# SNS
aws sns list-topics
aws sns list-subscriptions-by-topic --topic-arn <ARN>
aws sns publish --topic-arn <ARN> --subject "Test" --message "Test message"

# SAM CLI
sam validate --template-file template.yaml
sam build
sam deploy --guided
sam local invoke SecretsDetectorFunction --event tests/synthetic_payload.json

# CloudTrail
aws cloudtrail lookup-events --lookup-attributes AttributeKey=AccessKeyId,AttributeValue=<KEY>
```

---

## Document Control

- **Version**: 1.0
- **Last Updated**: 2025-12-12
- **Owner**: Security Operations Team
- **Review Frequency**: Quarterly
- **Next Review**: 2026-03-12

---

**END OF RUNBOOK**
