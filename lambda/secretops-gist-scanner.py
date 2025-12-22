# import os
# import json
# import re
# import math
# import urllib.request
# import boto3
# from collections import Counter
# from datetime import datetime

# # =============================
# # AWS SNS
# # =============================
# sns = boto3.client("sns")

# # =============================
# # STRICT Secret Patterns
# # =============================
# SECRET_PATTERNS = {
#     # AWS Access Key ID
#     "AWS_ACCESS_KEY_ID": r"\bAKIA[0-9A-Z]{16}\b",

#     # AWS Secret Access Key (with or without variable name)
#     "AWS_SECRET_ACCESS_KEY": (
#         r"(?:AWS_SECRET_ACCESS_KEY|aws_secret_access_key)?"
#         r"\s*[:=]?\s*"
#         r"([A-Za-z0-9\/+=]{40})"
#     ),
# }

# # =============================
# # Logging Helper
# # =============================
# def log(event, **data):
#     print(json.dumps({
#         "event": event,
#         "timestamp": datetime.utcnow().isoformat(),
#         **data
#     }))

# # =============================
# # Entropy Check
# # =============================
# def shannon_entropy(s):
#     freq = Counter(s)
#     entropy = 0
#     for c in freq.values():
#         p = c / len(s)
#         entropy -= p * math.log2(p)
#     return entropy

# # =============================
# # Scan Text
# # =============================
# def scan_text(text):
#     findings = []

#     for rule, pattern in SECRET_PATTERNS.items():
#         for match in re.finditer(pattern, text):
#             secret = match.group(1) if match.groups() else match.group(0)
#             entropy = shannon_entropy(secret)

#             # HARD noise filter
#             if entropy < 3.7:
#                 log(
#                     "LOW_ENTROPY_DROP",
#                     rule=rule,
#                     entropy=round(entropy, 2)
#                 )
#                 continue

#             findings.append({
#                 "rule": rule,
#                 "entropy": round(entropy, 2),
#                 "masked": f"{secret[:6]}...{secret[-4:]}"
#             })

#     return findings

# # =============================
# # GitHub API Helper
# # =============================
# def github_request(url, token):
#     req = urllib.request.Request(url)
#     req.add_header("Authorization", f"token {token}")
#     req.add_header("Accept", "application/vnd.github+json")
#     with urllib.request.urlopen(req, timeout=10) as r:
#         return json.loads(r.read().decode())

# # =============================
# # Lambda Handler
# # =============================
# def lambda_handler(event, context):

#     github_token  = os.environ["GITHUB_TOKEN"]
#     sns_topic_arn = os.environ["SNS_TOPIC_ARN"]

#     log("GIST_SCAN_START")

#     gists = github_request(
#         "https://api.github.com/gists/public?per_page=10",
#         github_token
#     )

#     log("GISTS_FETCHED", count=len(gists))

#     for gist in gists:
#         gist_url = gist.get("html_url")

#         for filename, fileinfo in gist.get("files", {}).items():
#             raw_url = fileinfo.get("raw_url")
#             if not raw_url:
#                 continue

#             try:
#                 content = urllib.request.urlopen(
#                     raw_url, timeout=10
#                 ).read().decode("utf-8", errors="ignore")

#                 findings = scan_text(content)

#                 if not findings:
#                     continue

#                 alert = {
#                     "source": "GitHub Public Gist",
#                     "gist_url": gist_url,
#                     "file": filename,
#                     "findings": findings,
#                     "detected_at": datetime.utcnow().isoformat()
#                 }

#                 log(
#                     "SECRET_CONFIRMED",
#                     gist_url=gist_url,
#                     file=filename,
#                     findings=len(findings)
#                 )

#                 sns.publish(
#                     TopicArn=sns_topic_arn,
#                     Subject="🚨 SecretOps – Public Gist Secret Detected",
#                     Message=json.dumps(alert, indent=2)
#                 )

#             except Exception as e:
#                 log(
#                     "SCAN_ERROR",
#                     file=filename,
#                     error=str(e)
#                 )

#     log("GIST_SCAN_COMPLETE")
#     return {"statusCode": 200}
