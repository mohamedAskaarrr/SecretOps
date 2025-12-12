# Test Artifacts

## Synthetic Test Payload

### File: `synthetic_payload.json`

This file contains a sample GitHub webhook payload for testing the secrets detector Lambda function.

**Key Features:**
- Contains a fake AWS access key ID: `AKIA1111111111111111`
- Simulates a Git push event with commit data
- Includes diff showing the key being added to a config file
- Safe for testing (not a real AWS credential)

### Local Testing with SAM CLI

To test the Lambda function locally with this payload:

```bash
# Install AWS SAM CLI
pip install aws-sam-cli

# Invoke the Lambda function locally
sam local invoke SecretsDetectorFunction --event tests/synthetic_payload.json
```

**Expected Behavior:**
1. Lambda logs show: "Found 1 unique access key(s): AKIA1111111111111111"
2. Lambda attempts to find the key owner in IAM (will fail locally without AWS credentials)
3. Lambda publishes an SNS alert (requires SNS_TOPIC_ARN environment variable)
4. Lambda returns HTTP 200 with status "processed"

### Testing with Environment Variables

To test signature verification, set the environment variable:

```bash
sam local invoke SecretsDetectorFunction \
  --event tests/synthetic_payload.json \
  --env-vars '{"GITHUB_WEBHOOK_SECRET":"test-secret-123","SNS_TOPIC_ARN":"arn:aws:sns:us-east-1:123456789012:test-topic"}'
```

**Note:** Signature verification will fail unless you add a valid X-Hub-Signature-256 header to the event.

### Testing Signature Verification

To generate a valid signature for the payload:

```bash
# Calculate HMAC SHA-256 signature
SIGNATURE=$(echo -n "$(cat tests/synthetic_payload.json)" | openssl dgst -sha256 -hmac "test-secret-123" | cut -d' ' -f2)
echo "X-Hub-Signature-256: sha256=$SIGNATURE"
```

Then update the event to include headers:

```json
{
  "body": "<json_payload_as_string>",
  "headers": {
    "X-Hub-Signature-256": "sha256=<calculated_signature>"
  }
}
```

### Manual Testing Checklist

When testing the Lambda function, verify:

- [ ] Python syntax compiles without errors
- [ ] SAM template validates successfully
- [ ] Lambda function invokes without runtime errors
- [ ] Access key pattern is detected in commit diff
- [ ] Function returns HTTP 200 status
- [ ] CloudWatch logs show detection messages
- [ ] SNS alerts would be published (if SNS_TOPIC_ARN configured)
- [ ] Signature verification works (if GITHUB_WEBHOOK_SECRET configured)

### Creating Custom Test Payloads

To create your own test payloads:

1. Visit a test repository on GitHub
2. Settings → Webhooks → Add webhook
3. Set URL to a request capture service (e.g., webhook.site)
4. Push a commit
5. Copy the webhook payload from the service
6. Sanitize any sensitive data
7. Add test credentials to the payload

### Integration Testing

For end-to-end testing in AWS:

1. Deploy the Lambda function: `sam deploy --guided`
2. Note the API Gateway endpoint URL from outputs
3. Configure GitHub webhook with the endpoint URL
4. Push a commit with a test key (AKIA1111111111111111)
5. Check CloudWatch logs for detection
6. Verify SNS alert was received
7. Clean up test commits

### Security Notes

⚠️ **NEVER** commit real AWS credentials to any repository, even for testing purposes.

- The fake key `AKIA1111111111111111` follows the AWS access key format but is not a real credential
- For production testing, use AWS Security Token Service (STS) temporary credentials
- Immediately rotate any real credentials that are accidentally committed

---

For more information, see the operational runbook: [docs/runbook.md](../docs/runbook.md)
