# Deployment Guide

This guide walks you through deploying the secrets detection system to AWS.

## Prerequisites

Before deploying, ensure you have:

- ✅ AWS Account with admin or sufficient IAM permissions
- ✅ AWS CLI installed and configured (`aws configure`)
- ✅ AWS SAM CLI installed (`pip install aws-sam-cli`)
- ✅ Python 3.11+ installed
- ✅ GitHub repository with admin access

## Step-by-Step Deployment

### 1. Validate Configuration

```bash
# Verify AWS credentials
aws sts get-caller-identity

# Validate SAM template
sam validate --template-file template.yaml

# Check Python syntax
python -m py_compile lambda_detector/handler.py
```

### 2. Build the Lambda Package

```bash
sam build
```

Expected output:
```
Build Succeeded

Built Artifacts  : .aws-sam/build
Built Template   : .aws-sam/build/template.yaml
```

### 3. Deploy to AWS

```bash
sam deploy --guided
```

You'll be prompted for:

| Parameter | Recommended Value | Description |
|-----------|------------------|-------------|
| Stack Name | `secrets-detector` | CloudFormation stack name |
| AWS Region | `us-east-1` | Your preferred region |
| Confirm changes | `Y` | Review changeset before deploy |
| Allow SAM IAM role creation | `Y` | Lambda needs IAM role |
| Disable rollback | `N` | Enable rollback on failure |
| Save arguments | `Y` | Save to samconfig.toml |

**Note the outputs** - you'll need the WebhookURL and AlertsSNS ARN.

### 4. Generate Webhook Secret

```bash
# Generate a strong 32-byte secret
WEBHOOK_SECRET=$(openssl rand -hex 32)
echo "Your webhook secret: $WEBHOOK_SECRET"
echo ""
echo "⚠️  Save this secret securely - you'll need it for GitHub and Lambda"
```

### 5. Update Lambda Environment Variables

```bash
# Get the function name
FUNCTION_NAME="secrets-detector-lambda"

# Get the SNS topic ARN from stack outputs
SNS_TOPIC_ARN=$(aws cloudformation describe-stacks \
  --stack-name secrets-detector \
  --query 'Stacks[0].Outputs[?OutputKey==`AlertsSNS`].OutputValue' \
  --output text)

# Update Lambda configuration
aws lambda update-function-configuration \
  --function-name $FUNCTION_NAME \
  --environment "Variables={GITHUB_WEBHOOK_SECRET=$WEBHOOK_SECRET,SNS_TOPIC_ARN=$SNS_TOPIC_ARN}"

echo "✓ Lambda environment variables updated"
```

### 6. Subscribe to SNS Alerts

```bash
# Get your email
read -p "Enter email for alerts: " EMAIL

# Subscribe to SNS topic
aws sns subscribe \
  --topic-arn $SNS_TOPIC_ARN \
  --protocol email \
  --notification-endpoint $EMAIL

echo "✓ Subscription request sent"
echo "  Check your email and confirm the subscription"
```

**Important**: Check your email inbox and click the confirmation link!

### 7. Configure GitHub Webhook

Get the API Gateway URL:

```bash
WEBHOOK_URL=$(aws cloudformation describe-stacks \
  --stack-name secrets-detector \
  --query 'Stacks[0].Outputs[?OutputKey==`WebhookURL`].OutputValue' \
  --output text)

echo "Your webhook URL: $WEBHOOK_URL"
```

#### In GitHub:

1. Go to your repository
2. Settings → Webhooks → Add webhook
3. Configure:
   - **Payload URL**: `<WebhookURL from above>`
   - **Content type**: `application/json`
   - **Secret**: `<WEBHOOK_SECRET from step 4>`
   - **SSL verification**: Enable SSL verification
   - **Which events**: Select "Just the push event"
   - **Active**: ✓ Checked

4. Click "Add webhook"

### 8. Test the Deployment

#### Method A: Use Test Payload Locally

```bash
# Test Lambda function locally
sam local invoke SecretsDetectorFunction \
  --event tests/synthetic_payload.json \
  --env-vars '{"GITHUB_WEBHOOK_SECRET":"'$WEBHOOK_SECRET'","SNS_TOPIC_ARN":"'$SNS_TOPIC_ARN'"}'
```

#### Method B: Push a Test Commit

1. Create a test branch:
   ```bash
   git checkout -b test/detector-verification
   ```

2. Add a test file with fake key:
   ```bash
   echo "AWS_ACCESS_KEY_ID=AKIA1111111111111111" > test-config.txt
   git add test-config.txt
   git commit -m "test: verify secrets detector"
   git push origin test/detector-verification
   ```

3. Check results:
   ```bash
   # Watch CloudWatch logs
   aws logs tail /aws/lambda/secrets-detector-lambda --follow
   
   # Check webhook delivery in GitHub
   # Repository → Settings → Webhooks → Recent Deliveries
   ```

4. Clean up test:
   ```bash
   git push origin --delete test/detector-verification
   git checkout main
   git branch -D test/detector-verification
   ```

### 9. Verify Deployment

Checklist:
- [ ] Lambda function deployed successfully
- [ ] API Gateway endpoint accessible
- [ ] SNS subscription confirmed (check email)
- [ ] GitHub webhook configured and active
- [ ] Test webhook delivery shows green checkmark
- [ ] CloudWatch logs show function execution
- [ ] SNS alert received for test commit

### 10. Monitor the System

#### CloudWatch Logs

```bash
# View recent logs
aws logs tail /aws/lambda/secrets-detector-lambda --since 1h

# Follow live logs
aws logs tail /aws/lambda/secrets-detector-lambda --follow

# Search for errors
aws logs filter-log-events \
  --log-group-name /aws/lambda/secrets-detector-lambda \
  --filter-pattern "ERROR" \
  --start-time $(date -u -d '1 hour ago' +%s)000
```

#### Lambda Metrics

```bash
# Get invocation count (last 24 hours)
aws cloudwatch get-metric-statistics \
  --namespace AWS/Lambda \
  --metric-name Invocations \
  --dimensions Name=FunctionName,Value=secrets-detector-lambda \
  --start-time $(date -u -d '24 hours ago' +%Y-%m-%dT%H:%M:%S) \
  --end-time $(date -u +%Y-%m-%dT%H:%M:%S) \
  --period 3600 \
  --statistics Sum
```

## Troubleshooting

### Webhook Delivery Failed (4xx/5xx)

```bash
# Check Lambda logs for errors
aws logs tail /aws/lambda/secrets-detector-lambda --since 10m

# Verify Lambda exists and is active
aws lambda get-function --function-name secrets-detector-lambda

# Test Lambda directly
aws lambda invoke \
  --function-name secrets-detector-lambda \
  --payload file://tests/synthetic_payload.json \
  response.json
cat response.json
```

### No SNS Alerts Received

```bash
# Verify subscription is confirmed
aws sns list-subscriptions-by-topic --topic-arn $SNS_TOPIC_ARN

# Test SNS directly
aws sns publish \
  --topic-arn $SNS_TOPIC_ARN \
  --subject "Test Alert" \
  --message "Test message from secrets detector"
```

### Signature Verification Failing

```bash
# Verify environment variable is set
aws lambda get-function-configuration \
  --function-name secrets-detector-lambda \
  --query 'Environment.Variables.GITHUB_WEBHOOK_SECRET'

# Check CloudWatch logs for signature errors
aws logs filter-log-events \
  --log-group-name /aws/lambda/secrets-detector-lambda \
  --filter-pattern "signature"
```

## Updating the Deployment

To update the Lambda code or configuration:

```bash
# Make your changes to lambda_detector/handler.py or template.yaml

# Rebuild and deploy
sam build
sam deploy

# No need to reconfigure GitHub webhook unless URL changes
```

## Cost Estimation

**Monthly costs** (typical usage, 100 webhook calls/day):

| Service | Usage | Cost |
|---------|-------|------|
| Lambda | 3,000 invocations, 128MB, 2s avg | $0.00 (free tier) |
| API Gateway | 3,000 requests | $0.01 |
| CloudWatch Logs | 100 MB logs, 30 days retention | $0.50 |
| SNS | 3 alerts/month | $0.00 |
| **Total** | | **~$0.51/month** |

## Cleanup (Uninstall)

To remove the deployment:

```bash
# Delete the CloudFormation stack
sam delete --stack-name secrets-detector

# Verify deletion
aws cloudformation describe-stacks --stack-name secrets-detector
# Should return "Stack with id secrets-detector does not exist"

# Remove webhook from GitHub manually:
# Repository → Settings → Webhooks → Delete webhook
```

## Security Hardening (Production)

Before production use, implement these additional security measures:

1. **Narrow IAM permissions**:
   - Edit template.yaml IAM policies
   - Replace `Resource: "*"` with specific ARNs
   - Limit to specific user paths (e.g., `/app/*`)

2. **Enable CloudWatch Alarms**:
   ```bash
   # Create alarm for Lambda errors
   aws cloudwatch put-metric-alarm \
     --alarm-name secrets-detector-errors \
     --alarm-description "Alert on Lambda errors" \
     --metric-name Errors \
     --namespace AWS/Lambda \
     --statistic Sum \
     --period 300 \
     --threshold 5 \
     --comparison-operator GreaterThanThreshold \
     --evaluation-periods 1 \
     --dimensions Name=FunctionName,Value=secrets-detector-lambda
   ```

3. **Implement rate limiting**:
   - Use API Gateway usage plans
   - Set throttle limits

4. **Secret rotation**:
   - Rotate GITHUB_WEBHOOK_SECRET every 90 days
   - Store in AWS Secrets Manager for automatic rotation

5. **Enable AWS WAF** (if public-facing):
   - Protect API Gateway from DDoS
   - Add rate limiting rules

## Additional Resources

- [AWS SAM Documentation](https://docs.aws.amazon.com/serverless-application-model/)
- [GitHub Webhooks Guide](https://docs.github.com/webhooks)
- [Operational Runbook](docs/runbook.md)
- [Testing Guide](tests/README.md)

## Support

For issues or questions:
- Check [docs/runbook.md](docs/runbook.md) troubleshooting section
- Open an issue on GitHub
- Review CloudWatch logs for detailed error messages

---

**Last Updated**: 2025-12-12
