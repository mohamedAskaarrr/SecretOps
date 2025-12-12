# lambda_detector/handler.py
import os
import json
import hmac
import hashlib
import re
import base64
import boto3
from botocore.exceptions import ClientError
from datetime import datetime

SNS_TOPIC_ARN = os.environ.get('SNS_TOPIC_ARN')
GITHUB_WEBHOOK_SECRET = os.environ.get('GITHUB_WEBHOOK_SECRET')  # raw secret string

iam = boto3.client('iam')
sns = boto3.client('sns')

AWS_KEY_REGEX = re.compile(r'AKIA[0-9A-Z]{16}')

def verify_github_signature(raw_body: bytes, signature_header: str) -> bool:
    if not GITHUB_WEBHOOK_SECRET:
        # treat as misconfigured but allow local/test runs to proceed
        return False
    mac = hmac.new(GITHUB_WEBHOOK_SECRET.encode('utf-8'), msg=raw_body, digestmod=hashlib.sha256)
    expected = 'sha256=' + mac.hexdigest()
    return hmac.compare_digest(expected, signature_header or '')

def publish_alert(message: str):
    if not SNS_TOPIC_ARN:
        print('SNS_TOPIC_ARN not set; alert:', message)
        return
    try:
        sns.publish(TopicArn=SNS_TOPIC_ARN, Message=message, Subject='Secrets Detector Alert')
    except ClientError as e:
        print('sns.publish error:', e)

def disable_key_for_user(username: str, access_key_id: str) -> bool:
    try:
        iam.update_access_key(UserName=username, AccessKeyId=access_key_id, Status='Inactive')
        return True
    except ClientError as e:
        print('disable_key_for_user error:', e)
        return False

def find_key_owner(access_key_id: str):
    # best-effort: iterate users and compare AccessKeyId
    paginator = iam.get_paginator('list_users')
    for page in paginator.paginate():
        for user in page.get('Users', []):
            username = user['UserName']
            try:
                keys = iam.list_access_keys(UserName=username).get('AccessKeyMetadata', [])
                for k in keys:
                    if k.get('AccessKeyId') == access_key_id:
                        return username
            except ClientError:
                continue
    return None

def extract_text_from_payload(payload: dict) -> str:
    combined = []
    commits = payload.get('commits', [])
    for c in commits:
        combined.append(c.get('message',''))
        for f in c.get('added', []) + c.get('modified', []):
            combined.append(f)
        # if diff is present in custom webhook, include it
        if 'diff' in c:
            combined.append(c.get('diff'))
    # fallback: search entire payload
    combined.append(json.dumps(payload))
    return '\n'.join(combined)

def handler(event, context):
    try:
        raw_body = event.get('body', '') if isinstance(event, dict) else str(event)
        is_base64 = event.get('isBase64Encoded', False)
        if is_base64:
            raw_body = base64.b64decode(raw_body)
        if isinstance(raw_body, str):
            raw_body_bytes = raw_body.encode('utf-8')
        else:
            raw_body_bytes = raw_body

        sig_header = event.get('headers', {}).get('X-Hub-Signature-256') or event.get('headers', {}).get('x-hub-signature-256')
        signed_ok = verify_github_signature(raw_body_bytes, sig_header)

        try:
            payload = json.loads(raw_body_bytes)
        except Exception:
            payload = {'raw': raw_body_bytes.decode('utf-8', errors='ignore')}

        # If signature exists and verification fails -> alert and return 200 (do not act)
        if sig_header and not signed_ok:
            publish_alert(f'GitHub webhook signature verification failed. Headers: {sig_header}')
            return {'statusCode': 200, 'body': json.dumps({'status': 'signature_failed'})}

        search_text = extract_text_from_payload(payload)
        matches = set(AWS_KEY_REGEX.findall(search_text))

        if not matches:
            print('no aws keys found')
            return {'statusCode': 200, 'body': json.dumps({'status': 'no_keys'})}

        results = []
        for key in matches:
            owner = find_key_owner(key)
            if owner:
                ok = disable_key_for_user(owner, key)
                msg = {
                    'time': datetime.utcnow().isoformat() + 'Z',
                    'access_key_id': key,
                    'owner': owner,
                    'disabled': ok
                }
                publish_alert(json.dumps(msg))
                results.append(msg)
            else:
                publish_alert(json.dumps({
                    'time': datetime.utcnow().isoformat() + 'Z',
                    'access_key_id': key,
                    'owner': None,
                    'disabled': False,
                    'note': 'key not found in current IAM users'
                }))
                results.append({'access_key_id': key, 'owner': None, 'disabled': False})

        return {'statusCode': 200, 'body': json.dumps({'status': 'processed', 'results': results})}

    except Exception as e:
        print('handler general error:', e)
        publish_alert(f'Error in secrets detector lambda: {e}')
        return {'statusCode': 200, 'body': json.dumps({'status': 'error'})}
