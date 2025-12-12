# Secrets Detection Runbook

## Purpose
Short: how pipeline detects leaked AWS keys, mitigates, and escalates.

## Architecture
GitHub -> API Gateway -> Lambda (secrets-detector) -> SNS -> Ops

## Pre-req
- SNS subscription(s) (email/Slack)
- GITHUB_WEBHOOK_SECRET configured in Lambda env
- Lambda role with iam:ListUsers, iam:ListAccessKeys, iam:UpdateAccessKey

## Detection flow
1. GitHub push triggers webhook (signed).
2. Lambda verifies HMAC signature.
3. Lambda scans commits/diffs for AKIA[0-9A-Z]{16}.
4. If found: find IAM owner, disable key, publish SNS alert.

## Manual rotation (if auto-rotation not available)
1. Identify user -> create new access key in IAM console or CLI.
2. Update the application secret source (SSM/Secrets Manager).
3. Confirm service health.
4. Delete old access key.

## Troubleshooting
- If no SNS alerts:
  - Check CloudWatch logs for Lambda.
  - Confirm SNS topic ARN env var.
- If signature verify fails:
  - Confirm webhook secret matches Lambda env.
  - Reconfigure GitHub webhook secret.
- If disable fails:
  - Check IAM permissions for Lambda role.

## False positives
- Token-like strings, long base64 blobs. Always verify before sweeping.

## Emergency rollback
- If detection disabled an essential key and service impacted:
  1. Re-enable the key temporarily via IAM console.
  2. Create incident ticket and follow rotation playbook.

## Contacts
- Pager / Slack: <placeholder>
- Email: <placeholder>
