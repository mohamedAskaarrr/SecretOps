# AWS Secrets Detection — Project board + Lambda skeleton + Laravel helper

Short, corporate, actionable: below you get a ready-to-import issues CSV (use GitHub Issues import), a serverless Lambda detection skeleton (Python) and a Laravel helper to fetch secrets from SSM. Drop into your repo, assign roles, and execute the sprint.

---

# 1) Importable GitHub Issues CSV (use GitHub Issues import)

Save the following as `project_issues.csv` then go to GitHub > Settings > Import issues (or use `gh` CLI). Column `ProjectColumn` corresponds to the target project board column you will create (Backlog, In Progress, Review, Done).

```
Title,Body,Assignees,Labels,Milestone,ProjectColumn
"T1: Repo kickoff & security.md","Create repo, add README, security.md, branch protection, issue templates. Deliver: threat-model.md","@team-lead","project-kickoff,documentation","Sprint 1","Backlog"
"T2: Account hardening & CloudTrail","Enable CloudTrail -> S3 + CloudWatch, create S3 bucket with BlockPublicAccess, ensure root MFA, remove root keys, create IncidentOps user","@infra","infra,security","Sprint 1","Backlog"
"T3: Secrets inventory & SSM migration","Inventory secrets, create secrets-inventory.csv, migrate secrets to SSM SecureString, PR to remove plaintext","@devops","secrets,devops","Sprint 1","Backlog"
"T4: Exposure-detection Lambda + GitHub webhook","Create Lambda + API Gateway, webhook from GitHub, scan commit diffs for key regex, publish alerts to SNS/Slack","@serverless-dev","detection,lambda","Sprint 2","Backlog"
"T5: Rotation automation","Lambda/tool that creates replacement keys, stores to SSM, updates deployment config, deactivates old key after verification","@devops","rotation,automation","Sprint 2","Backlog"
"T6: App integration (Laravel) to use SSM","Refactor app to remove static creds, add Laravel helper to fetch from SSM, use IAM role for runtime","@backend","laravel,backend","Sprint 2","Backlog"
"T7: Monitoring & runbook","CloudWatch metric filters, SNS Slack alerts, runbook.md + tabletop drill","@secops","monitoring,runbook","Sprint 3","Backlog"
"T4-test: Synthetic detection test","Create test commit payload containing AKIA... and validate Lambda disables test key and sends alert","@qa","test,automation","Sprint 2","Backlog"
"T3-cleanup: Remove secrets from git history","Use git-filter-repo (or BFG) to remove historic credentials, document process","@devops","cleanup,git","Sprint 2","Backlog"
```

---

# 2) Quick Project Board setup

Columns: Backlog, In Progress, Review, Done. Import issues, then create project board and assign `ProjectColumn` mapping above to create initial layout.

---

# 3) Lambda detection skeleton (Python) — `lambda_detector/handler.py`

Save as `lambda_detector/handler.py`.

```python
import re
import os
import json
import boto3
from botocore.exceptions import ClientError

iam = boto3.client('iam')
sns = boto3.client('sns')

SNS_TOPIC_ARN = os.environ.get('SNS_TOPIC_ARN')
# If limiting actions to specific users, set allowed_usernames list or use tags

AWS_KEY_PATTERN = r'AKIA[0-9A-Z]{16}'
GENERIC_TOKEN_PATTERN = r'([a-zA-Z0-9-_]{20,})'  # tune to reduce false positives


def disable_access_key(account_user, access_key_id):
    try:
        iam.update_access_key(UserName=account_user, AccessKeyId=access_key_id, Status='Inactive')
        return True
    except ClientError as e:
        print('Failed to disable key:', e)
        return False


def publish_alert(message):
    if not SNS_TOPIC_ARN:
        print('SNS_TOPIC_ARN not configured')
        return
    try:
        sns.publish(TopicArn=SNS_TOPIC_ARN, Message=message)
    except ClientError as e:
        print('Failed to publish SNS:', e)


def scan_text_for_keys(text):
    matches = re.findall(AWS_KEY_PATTERN, text)
    return matches


def handler(event, context):
    # Expecting GitHub push webhook forwarded via API Gateway
    body = event.get('body') if isinstance(event, dict) else str(event)
    try:
        payload = json.loads(body)
    except Exception:
        payload = {'raw': str(body)}

    combined_text = ''
    # Compose searchable text from commit diffs or message
    if 'commits' in payload:
        for c in payload['commits']:
            combined_text += c.get('message', '') + '\n'
            # Some webhooks include 'added','modified','removed' lists
            for f in ('added', 'modified'):
                for filename in c.get(f, []):
                    combined_text += filename + '\n'
            # GitHub sometimes sends 'patch' or 'diff' in other payloads; adapt if available
            combined_text += c.get('diff', '') if c.get('diff') else ''
    else:
        combined_text = json.dumps(payload)

    aws_keys = scan_text_for_keys(combined_text)

    if not aws_keys:
        print('No AWS keys detected')
        return {'statusCode': 200, 'body': 'no keys'}

    # For each found key try to find the owning user and disable (best-effort)
    for key in set(aws_keys):
        print('Detected potential key:', key)
        # List all access keys for users and match ID
        try:
            paginator = iam.get_paginator('list_users')
            found = False
            for page in paginator.paginate():
                for user in page.get('Users', []):
                    username = user['UserName']
                    aks = iam.list_access_keys(UserName=username).get('AccessKeyMetadata', [])
                    for meta in aks:
                        if meta['AccessKeyId'] == key:
                            found = True
                            ok = disable_access_key(username, key)
                            msg = f"Disabled key {key} for user {username}: {ok}"
                            publish_alert(msg)
            if not found:
                publish_alert(f"Leaked key found in repo but not mapped to current IAM users: {key}")
        except ClientError as e:
            print('IAM query error', e)
            publish_alert(f'IAM query error: {e}')

    return {'statusCode': 200, 'body': 'processed'}
```

Notes: this is intentionally conservative — it disables only when it finds exact AccessKeyId owned by an IAM user. For production, add strong rate-limiting, signatures, and verification to avoid abuse.

---

# 4) Serverless deploy (AWS SAM snippet) — `template.yaml` (minimal)

```yaml
AWSTemplateFormatVersion: '2010-09-09'
Transform: AWS::Serverless-2016-10-31
Resources:
  DetectorFunction:
    Type: AWS::Serverless::Function
    Properties:
      Handler: handler.handler
      Runtime: python3.11
      CodeUri: lambda_detector/
      Environment:
        Variables:
          SNS_TOPIC_ARN: !Ref AlertsTopic
      Policies:
        - Statement:
          - Effect: Allow
            Action:
              - iam:ListUsers
              - iam:ListAccessKeys
              - iam:UpdateAccessKey
            Resource: '*'
      Events:
        ApiGitHub:
          Type: Api
          Properties:
            Path: /github-webhook
            Method: post

  AlertsTopic:
    Type: AWS::SNS::Topic
    Properties:
      TopicName: project-alerts
```

IAM: above uses broad `Resource: '*'` for listing/updates; tighten later.

---

# 5) Laravel helper (PHP) — `app/Services/AwsSsmService.php`

Save under `app/Services/AwsSsmService.php`.

```php
<?php

namespace App\Services;

use Aws\Ssm\SsmClient;
use Illuminate\Support\Facades\Cache;

class AwsSsmService
{
    protected $client;

    public function __construct()
    {
        $this->client = new SsmClient([
            'version' => 'latest',
            'region' => config('services.aws.region', 'us-east-1')
            // Credentials are omitted so AWS SDK will use environment/role
        ]);
    }

    /**
     * Fetch parameter from SSM SecureString with simple caching
     */
    public function getParameter(string $name, bool $withDecryption = true)
    {
        $cacheKey = "ssm:{$name}";
        return Cache::remember($cacheKey, 300, function () use ($name, $withDecryption) {
            $result = $this->client->getParameter([
                'Name' => $name,
                'WithDecryption' => $withDecryption
            ]);

            return $result['Parameter']['Value'] ?? null;
        });
    }
}
```

## Usage (Laravel)

1. Install AWS SDK for PHP via composer:

```
composer require aws/aws-sdk-php
```

2. Bind service in a service provider (e.g. `AppServiceProvider`):

```php
$this->app->singleton(\App\Services\AwsSsmService::class, function ($app) {
    return new \App\Services\AwsSsmService();
});
```

3. Use in controllers or command:

```php
$ssm = app(\App\Services\AwsSsmService::class);
$apiKey = $ssm->getParameter('/myapp/prod/API_KEY');
```

Note: when running on EC2/ECS/Lambda, set IAM Role with `ssm:GetParameter` policy; avoid storing AWS keys in `.env`.

---

# 6) Quick IAM policy snippets (attach to Lambda role and App role)

**Lambda (detector)**: needs `iam:ListUsers`, `iam:ListAccessKeys`, `iam:UpdateAccessKey`, plus `sns:Publish` and `logs:*`.

**App runtime**: needs `ssm:GetParameter` on the parameter ARNs your app requires.

Minimal JSON example for SSM access (app):

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": ["ssm:GetParameter", "ssm:GetParameters"],
      "Resource": ["arn:aws:ssm:REGION:ACCOUNT_ID:parameter/app/*"]
    }
  ]
}
```

---

# 7) Next actions (one-liners to hand to team leads)

* Infra: create project S3 bucket + CloudTrail + GuardDuty trial. (T2)
* DevOps: run secrets inventory & migrate to SSM. (T3)
* Serverless Dev: deploy Lambda detector + test webhook. (T4)
* Backend: integrate Laravel helper and remove keys from code. (T6)
* DevOps: implement rotation Lambda (T5) after detection works. (T5)
* SecOps: create CloudWatch alerts, SNS->Slack, and publish runbook. (T7)
* QA: run synthetic test to validate detection and rotation. (T4-test)

---

# Files included in this document (copy & paste):

* `project_issues.csv` (above)
* `lambda_detector/handler.py` (above)
* `template.yaml` (SAM) (above)
* `app/Services/AwsSsmService.php` (above)

---

If you want, I can now: convert the CSV into a ready-to-import GitHub `issues.csv` file in the repo (I can create the file content here), or generate a `serverless.yml` instead of SAM, or give you the exact IAM JSON with your account ID filled (I'll need your account-id). Which of these should I do next? (No waiting — I will produce it in the next message.)
