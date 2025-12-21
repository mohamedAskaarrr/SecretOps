import os
import json
import re
import urllib.request
import urllib.parse
import boto3
from datetime import datetime

# =============================
# AWS Clients
# =============================
sns = boto3.client("sns")

# =============================
# Secret Patterns (REUSED)
# =============================
SECRET_PATTERNS = {
    "AWS_ACCESS_KEY": r"AKIA[0-9A-Z]{16}",
    "AWS_SECRET_KEY": r"(?i)aws(.{0,20})?(secret|access)[^a-zA-Z0-9]{0,5}[A-Za-z0-9\/+=]{40}",
    "GITHUB_TOKEN": r"ghp_[A-Za-z0-9]{36}|github_pat_[A-Za-z0-9_]{80,}",
    "GOOGLE_API_KEY": r"AIza[0-9A-Za-z\-_]{35}",
    "STRIPE_SECRET_KEY": r"sk_live_[0-9a-zA-Z]{24}",
    "SLACK_TOKEN": r"xox[baprs]-[0-9a-zA-Z]{10,48}",
    "JWT": r"eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+",
    "GENERIC_SECRET": r"(?i)(api[_-]?key|token|secret|password)[\"'\s:=]{1,5}[A-Za-z0-9_\-]{8,}"
}

# =============================
# GitHub API Helper
# =============================
def github_request(url, token):
    req = urllib.request.Request(url)
    req.add_header("Authorization", f"token {token}")
    req.add_header("Accept", "application/vnd.github+json")
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read().decode())

# =============================
# Scan Text
# =============================
def scan_text(text):
    findings = []
    for name, pattern in SECRET_PATTERNS.items():
        if re.search(pattern, text):
            findings.append(name)
    return list(set(findings))

# =============================
# Lambda Handler
# =============================
def lambda_handler(event, context):

    github_token  = os.environ["GITHUB_TOKEN"]
    sns_topic_arn = os.environ["SNS_TOPIC_ARN"]

    start_time = datetime.utcnow().isoformat()

    print(json.dumps({
        "event": "GIST_SCAN_START",
        "timestamp": start_time
    }))

    # ---------------------------------
    # GitHub SEARCH API (THIS WAS MISSING)
    # ---------------------------------
    query = "AWS_SECRET_ACCESS_KEY"
    encoded_query = urllib.parse.quote(query)

    search_url = (
        f"https://api.github.com/search/code"
        f"?q={encoded_query}+in:file+is:public"
        f"&per_page=5"
    )

    try:
        search_results = github_request(search_url, github_token)
        items = search_results.get("items", [])
    except Exception as e:
        print(json.dumps({
            "event": "SEARCH_FAILED",
            "error": str(e)
        }))
        return {"statusCode": 500}

    # ---------------------------------
    # Scan each result
    # ---------------------------------
    for item in items:
        file_url = item.get("html_url")
        api_url  = item.get("url")

        try:
            file_data = github_request(api_url, github_token)

            content = file_data.get("content")
            if not content:
                continue

            decoded = content.encode("utf-8")
            text = decoded.decode("utf-8", errors="ignore")

            findings = scan_text(text)

            if findings:
                alert = {
                    "source": "GitHub Public Code / Gist",
                    "file_url": file_url,
                    "secrets": findings,
                    "detected_at": datetime.utcnow().isoformat()
                }

                print(json.dumps({
                    "event": "SECRET_DETECTED",
                    "details": alert
                }))

                sns.publish(
                    TopicArn=sns_topic_arn,
                    Subject="🚨 SecretOps – Public Secret Detected",
                    Message=json.dumps(alert, indent=2)
                )

        except Exception as e:
            print(json.dumps({
                "event": "SCAN_ERROR",
                "file": file_url,
                "error": str(e)
            }))

    print(json.dumps({
        "event": "GIST_SCAN_COMPLETE",
        "timestamp": datetime.utcnow().isoformat()
    }))

    return {"statusCode": 200}
