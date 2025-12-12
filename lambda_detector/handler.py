"""
AWS Lambda handler for detecting leaked AWS access keys in GitHub webhooks.

This Lambda function:
1. Verifies GitHub webhook signatures (HMAC SHA-256)
2. Scans commits for AWS access key patterns (AKIA...)
3. Attempts to identify and deactivate compromised keys via IAM
4. Publishes alerts to SNS for all detections and errors
5. Returns HTTP 200 to all webhook calls (as per GitHub best practices)

Environment Variables Required:
- SNS_TOPIC_ARN: ARN of SNS topic for alerts
- GITHUB_WEBHOOK_SECRET: Secret for verifying webhook signatures (optional but recommended)

IAM Permissions Required:
- iam:ListUsers
- iam:ListAccessKeys
- iam:UpdateAccessKey
- sns:Publish
- logs:CreateLogGroup, logs:CreateLogStream, logs:PutLogEvents

Security Hardening TODO (for production):
- Implement rate limiting per source IP or signature
- Rotate GITHUB_WEBHOOK_SECRET periodically via AWS Secrets Manager
- Narrow IAM Resource ARNs to specific user paths or tags
- Add CloudWatch metrics for monitoring detection rates
- Consider async processing for large payloads (SQS queue)
"""

import re
import os
import json
import hmac
import hashlib
from datetime import datetime
from typing import Dict, List, Set, Optional, Any
import boto3
from botocore.exceptions import ClientError

# Initialize AWS clients
iam = boto3.client('iam')
sns = boto3.client('sns')

# Environment configuration
SNS_TOPIC_ARN = os.environ.get('SNS_TOPIC_ARN')
GITHUB_WEBHOOK_SECRET = os.environ.get('GITHUB_WEBHOOK_SECRET')

# AWS Access Key pattern: AKIA followed by 16 alphanumeric characters
AWS_KEY_PATTERN = re.compile(r'AKIA[0-9A-Z]{16}')


def verify_signature(payload_body: str, signature_header: Optional[str]) -> bool:
    """
    Verify GitHub webhook signature using HMAC SHA-256.
    
    Args:
        payload_body: Raw request body as string
        signature_header: Value of X-Hub-Signature-256 header
    
    Returns:
        True if signature is valid or GITHUB_WEBHOOK_SECRET is not configured
        False if signature verification fails
    """
    if not GITHUB_WEBHOOK_SECRET:
        print("WARNING: GITHUB_WEBHOOK_SECRET not configured - signature verification skipped")
        return True
    
    if not signature_header:
        print("WARNING: No X-Hub-Signature-256 header present")
        return True  # Allow if secret not configured
    
    # GitHub sends signature as "sha256=<hex_digest>"
    if not signature_header.startswith('sha256='):
        print(f"ERROR: Invalid signature format: {signature_header}")
        return False
    
    expected_signature = signature_header.split('=')[1]
    
    # Compute HMAC SHA-256
    secret_bytes = GITHUB_WEBHOOK_SECRET.encode('utf-8')
    payload_bytes = payload_body.encode('utf-8')
    computed_hmac = hmac.new(secret_bytes, payload_bytes, hashlib.sha256)
    computed_signature = computed_hmac.hexdigest()
    
    # Constant-time comparison to prevent timing attacks
    is_valid = hmac.compare_digest(computed_signature, expected_signature)
    
    if not is_valid:
        print(f"ERROR: Signature verification failed")
        print(f"Expected: {expected_signature[:10]}...")
        print(f"Computed: {computed_signature[:10]}...")
    
    return is_valid


def publish_alert(message: str, subject: str = "Secrets Detection Alert") -> None:
    """
    Publish alert message to SNS topic.
    
    Args:
        message: Alert message body
        subject: Alert subject line
    """
    if not SNS_TOPIC_ARN:
        print('ERROR: SNS_TOPIC_ARN not configured - cannot publish alert')
        print(f'Alert message: {message}')
        return
    
    try:
        sns.publish(
            TopicArn=SNS_TOPIC_ARN,
            Subject=subject[:100],  # SNS subject limit is 100 chars
            Message=message
        )
        print(f"SNS alert published: {subject}")
    except ClientError as e:
        print(f'ERROR: Failed to publish SNS alert: {e}')
    except Exception as e:
        print(f'ERROR: Unexpected error publishing SNS: {e}')


def scan_text_for_keys(text: str) -> Set[str]:
    """
    Search text for AWS access key patterns and deduplicate.
    
    Args:
        text: Text content to scan
    
    Returns:
        Set of unique access key IDs found
    """
    matches = AWS_KEY_PATTERN.findall(text)
    unique_keys = set(matches)
    
    if unique_keys:
        print(f"Found {len(unique_keys)} unique access key(s): {', '.join(unique_keys)}")
    
    return unique_keys


def find_key_owner(access_key_id: str) -> Optional[str]:
    """
    Attempt to find the IAM user that owns the given access key.
    
    Args:
        access_key_id: AWS access key ID to search for
    
    Returns:
        Username if found, None otherwise
    """
    try:
        # Paginate through all IAM users
        paginator = iam.get_paginator('list_users')
        for page in paginator.paginate():
            for user in page.get('Users', []):
                username = user['UserName']
                try:
                    # List access keys for this user
                    keys_response = iam.list_access_keys(UserName=username)
                    for key_meta in keys_response.get('AccessKeyMetadata', []):
                        if key_meta['AccessKeyId'] == access_key_id:
                            print(f"Key {access_key_id} belongs to user: {username}")
                            return username
                except ClientError as e:
                    print(f"Error listing keys for user {username}: {e}")
                    continue
        
        print(f"Key {access_key_id} not found in any IAM user")
        return None
    
    except ClientError as e:
        print(f"ERROR: Failed to query IAM users: {e}")
        return None


def deactivate_access_key(username: str, access_key_id: str) -> bool:
    """
    Deactivate an IAM access key by setting Status to 'Inactive'.
    
    Args:
        username: IAM username that owns the key
        access_key_id: Access key ID to deactivate
    
    Returns:
        True if successful, False otherwise
    """
    try:
        iam.update_access_key(
            UserName=username,
            AccessKeyId=access_key_id,
            Status='Inactive'
        )
        print(f"SUCCESS: Deactivated key {access_key_id} for user {username}")
        return True
    except ClientError as e:
        print(f"ERROR: Failed to deactivate key {access_key_id} for user {username}: {e}")
        return False


def extract_commit_data(payload: Dict[str, Any]) -> str:
    """
    Extract searchable text from GitHub webhook payload.
    
    Args:
        payload: Parsed GitHub webhook payload
    
    Returns:
        Combined text from commit messages, file names, and diffs
    """
    searchable_text = []
    
    commits = payload.get('commits', [])
    if not commits:
        print("No commits found in payload")
        # Fallback: search entire payload
        return json.dumps(payload)
    
    for commit in commits:
        # Add commit message
        message = commit.get('message', '')
        if message:
            searchable_text.append(f"Commit message: {message}")
        
        # Add file names from added/modified/removed lists
        for file_list_key in ['added', 'modified', 'removed']:
            files = commit.get(file_list_key, [])
            for filename in files:
                searchable_text.append(f"File: {filename}")
        
        # Some GitHub events include diff/patch data
        diff = commit.get('diff', '') or commit.get('patch', '')
        if diff:
            searchable_text.append(f"Diff: {diff}")
    
    combined = '\n'.join(searchable_text)
    print(f"Extracted {len(searchable_text)} text segments from {len(commits)} commit(s)")
    
    return combined


def handle_detected_keys(access_keys: Set[str], commit_info: Dict[str, Any]) -> None:
    """
    Process detected access keys: identify owner, deactivate, and alert.
    
    Args:
        access_keys: Set of detected access key IDs
        commit_info: Information about the commit(s) where keys were found
    """
    timestamp = datetime.utcnow().isoformat()
    
    for key_id in access_keys:
        print(f"\n{'='*60}")
        print(f"Processing detected key: {key_id}")
        print(f"{'='*60}")
        
        # Attempt to find the owner
        owner = find_key_owner(key_id)
        
        if owner:
            # Try to deactivate the key
            success = deactivate_access_key(owner, key_id)
            action_taken = "DEACTIVATED" if success else "DEACTIVATION_FAILED"
        else:
            action_taken = "KEY_NOT_FOUND_IN_IAM"
            success = False
        
        # Build alert message
        alert_message = f"""
SECURITY ALERT: AWS Access Key Detected in Git Commit

Timestamp: {timestamp}
Access Key ID: {key_id}
Owner: {owner if owner else 'UNKNOWN (not found in IAM)'}
Action Taken: {action_taken}

Commit Information:
{json.dumps(commit_info, indent=2)}

IMMEDIATE ACTIONS REQUIRED:
1. Verify if this is a legitimate key exposure
2. If owner found and key deactivated, verify application functionality
3. Generate replacement key if needed and update application configuration
4. Review commit history to ensure key is removed from all branches
5. Consider using git-filter-repo to remove key from repository history
6. Review CloudWatch logs for any unauthorized API usage with this key
7. Update GITHUB_WEBHOOK_SECRET if webhook security is compromised

For detailed procedures, see: docs/runbook.md
"""
        
        # Publish alert
        subject = f"AWS Key Detected: {key_id} - {action_taken}"
        publish_alert(alert_message, subject)


def handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Main Lambda handler for GitHub webhook events.
    
    Args:
        event: API Gateway proxy event containing GitHub webhook
        context: Lambda context object
    
    Returns:
        API Gateway response with status code and body
    """
    print(f"Lambda invocation started")
    print(f"Event type: {type(event)}")
    
    try:
        # Extract request body and headers
        body_raw = event.get('body', '')
        headers = event.get('headers', {})
        
        # GitHub sends headers in lowercase when proxied through API Gateway
        signature_header = headers.get('X-Hub-Signature-256') or headers.get('x-hub-signature-256')
        
        print(f"Signature header present: {bool(signature_header)}")
        
        # Verify webhook signature
        if signature_header or GITHUB_WEBHOOK_SECRET:
            is_valid = verify_signature(body_raw, signature_header)
            if not is_valid:
                error_msg = "GitHub webhook signature verification failed"
                print(f"ERROR: {error_msg}")
                publish_alert(
                    f"SECURITY WARNING: {error_msg}\n\nTimestamp: {datetime.utcnow().isoformat()}\n\n"
                    f"This may indicate:\n"
                    f"1. Webhook secret mismatch between GitHub and Lambda\n"
                    f"2. Request tampering\n"
                    f"3. Replay attack attempt\n\n"
                    f"Please verify GITHUB_WEBHOOK_SECRET configuration.",
                    "Webhook Signature Verification Failed"
                )
                # Return 200 with status message (GitHub expects 2xx for webhook deliveries)
                return {
                    'statusCode': 200,
                    'body': json.dumps({'status': 'signature_failed'})
                }
        
        # Parse GitHub payload
        try:
            payload = json.loads(body_raw) if body_raw else {}
        except json.JSONDecodeError as e:
            print(f"ERROR: Failed to parse JSON payload: {e}")
            return {
                'statusCode': 200,
                'body': json.dumps({'status': 'invalid_json'})
            }
        
        # Extract commit information for context
        commit_info = {
            'repository': payload.get('repository', {}).get('full_name', 'unknown'),
            'pusher': payload.get('pusher', {}).get('name', 'unknown'),
            'ref': payload.get('ref', 'unknown'),
            'commits_count': len(payload.get('commits', []))
        }
        
        print(f"Processing webhook from: {commit_info['repository']}")
        print(f"Pusher: {commit_info['pusher']}")
        print(f"Commits: {commit_info['commits_count']}")
        
        # Extract and scan commit data
        searchable_text = extract_commit_data(payload)
        detected_keys = scan_text_for_keys(searchable_text)
        
        if not detected_keys:
            print("No AWS access keys detected - webhook processed successfully")
            return {
                'statusCode': 200,
                'body': json.dumps({'status': 'no_keys_detected'})
            }
        
        # Handle detected keys
        handle_detected_keys(detected_keys, commit_info)
        
        return {
            'statusCode': 200,
            'body': json.dumps({
                'status': 'processed',
                'keys_detected': len(detected_keys)
            })
        }
    
    except Exception as e:
        error_msg = f"Unexpected error in Lambda handler: {str(e)}"
        print(f"ERROR: {error_msg}")
        
        # Publish error alert
        publish_alert(
            f"Lambda Error: {error_msg}\n\nTimestamp: {datetime.utcnow().isoformat()}",
            "Lambda Handler Error"
        )
        
        # Always return 200 to GitHub to avoid webhook retries
        return {
            'statusCode': 200,
            'body': json.dumps({'status': 'error', 'message': str(e)})
        }
