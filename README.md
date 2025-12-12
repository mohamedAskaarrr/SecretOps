# RIP to REST Secrets

🔐 **Automated AWS Secrets Detection and Remediation System**

A serverless pipeline that detects leaked AWS access keys in GitHub commits, automatically deactivates them, and sends alerts—all in real-time.

## 🎯 Overview

This project provides an end-to-end solution for protecting your AWS infrastructure from accidentally committed credentials. When a developer pushes code containing AWS access keys to GitHub, this system:

1. ✅ Receives a webhook from GitHub
2. ✅ Verifies the webhook signature (HMAC SHA-256)
3. ✅ Scans commits for AWS access key patterns (`AKIA[0-9A-Z]{16}`)
4. ✅ Identifies the key owner via IAM API
5. ✅ Automatically deactivates the compromised key
6. ✅ Publishes detailed alerts to SNS (email, Slack, PagerDuty)
7. ✅ Logs everything to CloudWatch

## 🏗️ Architecture

```
GitHub Push Event → API Gateway → Lambda Function → IAM (deactivate key)
                                         ↓
                                    SNS Topic → Email/Slack/PagerDuty
                                         ↓
                                  CloudWatch Logs
```

**Technology Stack:**
- **AWS Lambda** (Python 3.11) - Detection engine
- **API Gateway** - Webhook receiver
- **IAM API** - Key identification and deactivation
- **SNS** - Alert distribution
- **CloudWatch** - Logging and monitoring
- **AWS SAM** - Infrastructure as Code

## 🚀 Quick Start

### Prerequisites

- AWS Account with appropriate IAM permissions
- [AWS SAM CLI](https://docs.aws.amazon.com/serverless-application-model/latest/developerguide/install-sam-cli.html) installed
- Python 3.11+
- GitHub repository with admin access

### Deployment

1. **Clone the repository:**
   ```bash
   git clone https://github.com/mohamedAskaarrr/rip-to-rest-secrets.git
   cd rip-to-rest-secrets
   ```

2. **Validate the SAM template:**
   ```bash
   sam validate --template-file template.yaml
   ```

3. **Deploy to AWS:**
   ```bash
   sam build
   sam deploy --guided
   ```
   
   Follow the prompts:
   - Stack Name: `secrets-detector`
   - AWS Region: `us-east-1` (or your preferred region)
   - Confirm changes: `Y`
   - Allow SAM CLI IAM role creation: `Y`
   - Save arguments to configuration file: `Y`

4. **Note the API Gateway endpoint** from the deployment outputs:
   ```
   WebhookURL: https://abc123xyz.execute-api.us-east-1.amazonaws.com/Prod/github-webhook
   ```

5. **Generate a webhook secret:**
   ```bash
   openssl rand -hex 32
   ```

6. **Configure GitHub webhook:**
   - Go to your repository → Settings → Webhooks → Add webhook
   - Payload URL: `<WebhookURL from step 4>`
   - Content type: `application/json`
   - Secret: `<generated secret from step 5>`
   - Events: Select "Just the push event"
   - Active: ✓

7. **Update Lambda environment variable:**
   ```bash
   aws lambda update-function-configuration \
     --function-name secrets-detector-lambda \
     --environment "Variables={GITHUB_WEBHOOK_SECRET=<your_secret>}"
   ```

8. **Subscribe to SNS alerts:**
   ```bash
   aws sns subscribe \
     --topic-arn <AlertsSNS from deployment outputs> \
     --protocol email \
     --notification-endpoint your-email@example.com
   ```
   
   Confirm the subscription via the email you receive.

## 🧪 Testing

### Local Testing

Test the Lambda function locally with the provided synthetic payload:

```bash
sam local invoke SecretsDetectorFunction --event tests/synthetic_payload.json
```

The test payload contains a fake AWS key (`AKIA1111111111111111`) for safe testing.

### Manual Integration Test

1. Create a test branch in your repository
2. Add a file with a test key: `AKIA1111111111111111`
3. Push the commit
4. Check CloudWatch logs: `aws logs tail /aws/lambda/secrets-detector-lambda --follow`
5. Verify you received an SNS alert

See [tests/README.md](tests/README.md) for detailed testing instructions.

## 📚 Documentation

- **[Operational Runbook](docs/runbook.md)** - Complete guide for operations, incident response, and troubleshooting
  - Architecture details
  - Signature verification setup
  - Incident response procedures
  - Manual key rotation steps
  - Troubleshooting guide
  - IAM permissions

## 🛠️ Development

### Project Structure

```
rip-to-rest-secrets/
├── lambda_detector/
│   └── handler.py              # Main Lambda function
├── tests/
│   ├── synthetic_payload.json  # Test webhook payload
│   └── README.md               # Testing documentation
├── docs/
│   └── runbook.md              # Operational runbook
├── .github/
│   └── workflows/
│       └── ci.yml              # CI pipeline
├── template.yaml               # AWS SAM template
└── README.md                   # This file
```

### CI/CD Pipeline

Pull requests are automatically validated via GitHub Actions:

- ✅ SAM template validation
- ✅ Python syntax checking (`py_compile`)
- ✅ Security scanning (Bandit)

### Contributing

1. Fork the repository
2. Create a feature branch: `git checkout -b feature/my-feature`
3. Make your changes
4. Run validation: `sam validate && python -m py_compile lambda_detector/handler.py`
5. Commit: `git commit -m "feat: add my feature"`
6. Push: `git push origin feature/my-feature`
7. Open a Pull Request

## 🔒 Security

### Lambda IAM Permissions

The Lambda function requires:
- `iam:ListUsers` - To find key owners
- `iam:ListAccessKeys` - To query user keys
- `iam:UpdateAccessKey` - To deactivate keys
- `sns:Publish` - To send alerts
- `logs:*` - For CloudWatch logging

**⚠️ Production Hardening:**
- Narrow IAM `Resource` ARNs to specific user paths (e.g., `/app/*`)
- Implement rate limiting
- Rotate webhook secret quarterly
- Enable CloudWatch alarms for detection rate anomalies

### Reporting Vulnerabilities

Please report security vulnerabilities to the repository owner. Do NOT create public issues for security concerns.

## 📊 Monitoring

### CloudWatch Logs

View Lambda execution logs:
```bash
aws logs tail /aws/lambda/secrets-detector-lambda --follow
```

### Metrics to Monitor

- Lambda invocation count
- Lambda error rate
- SNS publish success rate
- IAM API call failures
- Detection rate (keys found per day)

### Recommended Alarms

Create CloudWatch alarms for:
- Lambda errors > 5% of invocations
- No webhook activity for 24+ hours (indicates webhook misconfiguration)
- High detection rate (> 5 keys/hour indicates possible attack)

## 🤝 Support

- **Issues**: [GitHub Issues](https://github.com/mohamedAskaarrr/rip-to-rest-secrets/issues)
- **Documentation**: See [docs/runbook.md](docs/runbook.md)

## 📝 License

This project is provided as-is for educational and security purposes.

## 🙏 Acknowledgments

Built with:
- [AWS SAM](https://aws.amazon.com/serverless/sam/)
- [GitHub Webhooks](https://docs.github.com/webhooks)
- [Bandit Security Linter](https://bandit.readthedocs.io/)

---

**⚡ Stay secure! Never commit credentials to source control. ⚡**