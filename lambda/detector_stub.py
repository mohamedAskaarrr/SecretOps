import json
import os
import hmac
import hashlib
import base64
import urllib.request
import re
import boto3



# =============================
# AWS Client
# =============================
sns = boto3.client("sns")

# =============================
# Regex Detection Rules
# =============================

# =============================
# Regex Detection Rules
# =============================
SECRET_PATTERNS = {
    "AWS_ACCESS_KEY": r"AKIA[0-9A-Z]{16}",
    "AWS_SECRET_KEY": r"(?i)aws(.{0,20})?(secret|access)[^a-zA-Z0-9]{0,5}[A-Za-z0-9\/+=]{40}",
    "GITHUB_TOKEN": r"ghp_[A-Za-z0-9]{36}|github_pat_[A-Za-z0-9_]{80,}",
    "GOOGLE_API_KEY": r"AIza[0-9A-Za-z\-_]{35}",
    "STRIPE_SECRET_KEY": r"sk_live_[0-9a-zA-Z]{24}",
    "SLACK_TOKEN": r"xox[baprs]-[0-9A-Za-z]{10,48}",
    "JWT": r"eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+",
    "GENERIC_API_KEY": r"(?i)(api[_-]?key|token|secret)[\"'\s:=]{1,5}[A-Za-z0-9_\-]{16,64}",
    "HARDCODED_PASSWORD": r"(?i)(password|passwd|pwd)[\"'\s:=]{1,5}.+"
}

# =============================
# Fetch Commit Diff
# =============================
def fetch_commit_diff(repo, commit_sha, token):
    url = f"https://api.github.com/repos/{repo}/commits/{commit_sha}"
    req = urllib.request.Request(url)
    req.add_header("Authorization", f"token {token}")
    req.add_header("Accept", "application/vnd.github.v3.diff")

    with urllib.request.urlopen(req, timeout=10) as res:
        return res.read().decode("utf-8", errors="ignore")

# =============================
# Scan Diff (Added + Removed)
# =============================
def scan_diff(diff_text):
    added = set()
    removed = set()

    for line in diff_text.splitlines():
        if line.startswith("+++"):
            continue

        if line.startswith("+"):
            for t, p in SECRET_PATTERNS.items():
                if re.search(p, line):
                    added.add(t)

        if line.startswith("-"):
            for t, p in SECRET_PATTERNS.items():
                if re.search(p, line):
                    removed.add(t)

    return list(added), list(removed)

# =============================
# Send SNS Email
# =============================
def send_alert(subject, message):
    print("📧 Sending SNS alert")
    sns.publish(
        TopicArn=os.environ["SNS_TOPIC_ARN"],
        Subject=subject,
        Message=message
    )

# =============================
# Lambda Handler
# =============================
def lambda_handler(event, context):

    webhook_secret = os.environ["GITHUB_WEBHOOK_SECRET"].encode()
    github_token = os.environ["GITHUB_TOKEN"]

    headers = {k.lower(): v for k, v in event.get("headers", {}).items()}
    signature = headers.get("x-hub-signature-256")

    if not signature:
        return {"statusCode": 401, "body": "Missing signature"}

    body = event.get("body", "")
    if event.get("isBase64Encoded"):
        body = base64.b64decode(body)
    else:
        body = body.encode()

    digest = hmac.new(webhook_secret, body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(f"sha256={digest}", signature):
        return {"statusCode": 401, "body": "Invalid signature"}

    if headers.get("x-github-event") != "push":
        return {"statusCode": 204, "body": "Ignored"}

    payload = json.loads(body)

    repo = payload["repository"]["full_name"]
    pusher = payload["pusher"]["name"]
    commits = payload.get("commits", [])

    print("NORMALIZED EVENT:", json.dumps({
        "repo": repo,
        "pusher": pusher,
        "commit_count": len(commits)
    }))

    for commit in commits:
        try:
            diff = fetch_commit_diff(repo, commit["id"], github_token)
            added, removed = scan_diff(diff)

            if added:
                send_alert(
                    "🚨 Secret Added",
                    f"""
🚨 SECRET ADDED 🚨

Repository: {repo}
Commit: {commit['id']}
Pusher: {pusher}

Added secrets:
{added}

Immediate action required.
"""
                )

            if removed:
                send_alert(
                    "✅ Secret Removed",
                    f"""
✅ SECRET REMOVED ✅

Repository: {repo}
Commit: {commit['id']}
Pusher: {pusher}

Removed secrets:
{removed}

Good security hygiene confirmed.
"""
                )

        except Exception as e:
            print("Detection error:", str(e))

    return {
        "statusCode": 200,
        "body": "Detection & alerting completed"
    }
