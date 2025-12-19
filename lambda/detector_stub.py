import json
import os
import hmac
import hashlib
import base64

def lambda_handler(event, context):
    # 1️⃣ Get secret from environment
    secret = os.environ["GITHUB_WEBHOOK_SECRET"].encode()

    # 2️⃣ Get headers (normalize case)
    headers = {k.lower(): v for k, v in event.get("headers", {}).items()}

    signature_header = headers.get("x-hub-signature-256")
    if not signature_header:
        return {
            "statusCode": 401,
            "body": "Missing GitHub signature"
        }

    # 3️⃣ Get raw body
    body = event.get("body", "")
    if event.get("isBase64Encoded"):
        body = base64.b64decode(body)
    else:
        body = body.encode()

    # 4️⃣ Compute HMAC SHA256
    computed_hash = hmac.new(
        secret,
        body,
        hashlib.sha256
    ).hexdigest()

    expected_signature = f"sha256={computed_hash}"

    # 5️⃣ Compare signatures safely
    if not hmac.compare_digest(expected_signature, signature_header):
        return {
            "statusCode": 401,
            "body": "Invalid GitHub signature"
        }

    # 6️⃣ Filter event type
    event_type = headers.get("x-github-event")
    if event_type != "push":
        return {
            "statusCode": 204,
            "body": "Event ignored"
        }

    # 7️⃣ Parse and normalize payload
    payload = json.loads(body)

    normalized = {
        "repo": payload["repository"]["full_name"],
        "pusher": payload["pusher"]["name"],
        "commits": [
            {
                "id": c["id"],
                "message": c["message"],
                "added": c["added"],
                "modified": c["modified"],
                "removed": c["removed"]
            }
            for c in payload.get("commits", [])
        ]
    }

    print("NORMALIZED EVENT:", json.dumps(normalized))

    return {
        "statusCode": 200,
        "body": "Webhook verified and processed"
    }
