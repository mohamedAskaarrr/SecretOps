# SecretOps 🔐
**Automated Detection & Remediation of Exposed Secrets using AWS**

## Overview
SecretOps is a cloud security project that detects exposed API keys and secrets in GitHub repositories and automatically responds using AWS services.

## Problem Statement
Exposed secrets in source code are a major cause of cloud breaches. Manual detection is slow and unreliable.

## Solution
SecretOps uses a serverless, event-driven AWS architecture to detect and remediate leaked secrets in near real-time.

## Architecture
GitHub → API Gateway → AWS Lambda → SNS → IAM Remediation

## Current Progress
- IAM groups & policies created
- Team roles assigned
- API Gateway & Lambda setup started








## Tech Stack
- GitHub Webhooks
- AWS API Gateway (HTTP API)
- AWS Lambda (Python)
- Amazon SNS
- AWS IAM

## Status
🚧 In Progress
thanks

AWS_SECRET_ACCESS_KEY=AKIA1234567890123456

AWS_SECRET_ACCESS_KEY=abcdabcdabcdabcdabcdabcdabcdabcdabcdabbd



