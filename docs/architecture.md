# Architecture Design

SecretOps follows a serverless, event-driven architecture.

1. GitHub Webhook sends events
2. API Gateway receives requests
3. Lambda scans payloads for secrets
4. SNS sends alerts
5. IAM keys are disabled if compromised



