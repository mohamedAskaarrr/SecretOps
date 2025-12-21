import json
import os
import hmac
import hashlib
import base64
import urllib.request
import re

# =============================
# Regex Detection Rules
# =============================
SECRET_PATTERNS = {
    # ================= AWS =================
    "AWS_ACCESS_KEY": r"AKIA[0-9A-Z]{16}",
    "AWS_SECRET_KEY": r"(?i)aws(.{0,20})?(secret|access)[^a-zA-Z0-9]{0,5}[A-Za-z0-9\/+=]{40}",

    # ================= GitHub =================
    "GITHUB_TOKEN": r"ghp_[A-Za-z0-9]{36}|github_pat_[A-Za-z0-9_]{80,}",

    # ================= Google =================
    "GOOGLE_API_KEY": r"AIza[0-9A-Za-z\-_]{35}",

    # ================= Stripe =================
    "STRIPE_SECRET_KEY": r"sk_live_[0-9a-zA-Z]{24}",

    # ================= Slack =================
    "SLACK_TOKEN": r"xox[baprs]-[0-9a-zA-Z]{10,48}",

    # ================= JWT =================
    "JWT": r"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}",

    # ================= Generic API Keys =================
    "GENERIC_API_KEY": r"(?i)(api[_-]?key|token|secret)[\"'\s:=]{1,5}[A-Za-z0-9_\-]{16,64}",

    # ================= Password Assignments =================
    "HARDCODED_PASSWORD": r"(?i)(password|passwd|pwd)[\"'\s:=]{1,5}.+"
}


# =============================
# GitHub API – Fetch Commit Diff
# =============================
def fetch_commit_diff(repo, commit_sha, token):
    url = f"https://api.github.com/repos/{repo}/commits/{commit_sha}"

    req = urllib.request.Request(url)
    req.add_header("Authorization", f"token {token}")
    req.add_header("Accept", "application/vnd.github.v3.diff")

    with urllib.request.urlopen(req) as res:
        return res.read().decode("utf-8")




# =============================
# Scan Diff for Secrets
# =============================


def scan_diff(diff_text):
    added = set()
    removed = set()

    for line in diff_text.splitlines():
        if line.startswith("+++"):
            continue

        if line.startswith("+"):
            for secret_type, pattern in SECRET_PATTERNS.items():
                if re.search(pattern, line):
                    added.add(secret_type)

        if line.startswith("-"):
            for secret_type, pattern in SECRET_PATTERNS.items():
                if re.search(pattern, line):
                    removed.add(secret_type)

    return list(added), list(removed)

# =============================
# Lambda Handler
# =============================
def lambda_handler(event, context):

    # 1️⃣ Load secrets from environment
    webhook_secret = os.environ["GITHUB_WEBHOOK_SECRET"].encode()
    github_token = os.environ["GITHUB_TOKEN"]

    # 2️⃣ Normalize headers
    headers = {k.lower(): v for k, v in event.get("headers", {}).items()}

    signature_header = headers.get("x-hub-signature-256")
    if not signature_header:
        return {"statusCode": 401, "body": "Missing GitHub signature"}

    # 3️⃣ Get raw body
    body = event.get("body", "")
    if event.get("isBase64Encoded"):
        body = base64.b64decode(body)
    else:
        body = body.encode()

    # 4️⃣ Verify HMAC signature
    computed_hash = hmac.new(
        webhook_secret,
        body,
        hashlib.sha256
    ).hexdigest()

    expected_signature = f"sha256={computed_hash}"

    if not hmac.compare_digest(expected_signature, signature_header):
        return {"statusCode": 401, "body": "Invalid GitHub signature"}

    # 5️⃣ Filter only push events
    if headers.get("x-github-event") != "push":
        return {"statusCode": 204, "body": "Event ignored"}

    # 6️⃣ Parse payload
    payload = json.loads(body)

    normalized = {
        "repo": payload["repository"]["full_name"],
        "pusher": payload["pusher"]["name"],
        "commits": payload.get("commits", [])
    }

    print("NORMALIZED EVENT:", json.dumps(normalized))

    # 7️⃣ Detection Phase
    for commit in normalized["commits"]:
        try:
            diff = fetch_commit_diff(
                normalized["repo"],
                commit["id"],
                github_token
            )

            findings = scan_diff(diff)

            if findings:
                print("🚨 SECRET DETECTED", {
                    "repo": normalized["repo"],
                    "commit": commit["id"],
                    "findings": findings
                })

        except Exception as e:
            print("Detection error:", str(e))

    return {
        "statusCode": 200,
        "body": "Webhook verified and detection completed"
    }
