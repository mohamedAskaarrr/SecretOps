# Branch Protection Configuration Guide

This document describes the required branch protection rules for the `main` branch. These rules must be configured through GitHub's web interface or API.

## Required Branch Protection Rules

### Rule 1: Require Pull Request Reviews Before Merging

**Configuration Steps:**
1. Go to repository Settings → Branches
2. Add branch protection rule for `main`
3. Enable: "Require a pull request before merging"
4. Set "Required approving reviews" to at least 1
5. Enable: "Dismiss stale pull request approvals when new commits are pushed"
6. Enable: "Require review from Code Owners" (optional but recommended)

**Purpose:**
- Ensures all code is reviewed before merging
- Catches bugs and security issues early
- Promotes knowledge sharing across the team

---

### Rule 2: No Direct Pushes to Main

**Configuration Steps:**
1. In the same branch protection rule settings
2. Ensure "Require a pull request before merging" is enabled (this prevents direct pushes)
3. Enable: "Do not allow bypassing the above settings" (recommended)
4. Enable: "Include administrators" to apply rules even to repository admins

**Purpose:**
- Prevents accidental or unauthorized changes
- Ensures all changes go through review process
- Maintains audit trail of all changes

---

### Rule 3: Require Status Checks to Pass Before Merging

**Configuration Steps:**
1. In branch protection rule settings
2. Enable: "Require status checks to pass before merging"
3. Enable: "Require branches to be up to date before merging"
4. Search and add required status checks (examples):
   - Build
   - Test
   - Lint
   - Security scan
   - CodeQL
   - Any other CI checks you've configured

**Purpose:**
- Ensures code quality standards are met
- Prevents broken code from being merged
- Automatically runs security scans

---

## Additional Recommended Settings

### Require Linear History
- Prevents merge commits, keeping history clean
- Enforces rebase or squash merge strategies

### Require Deployments to Succeed
- Ensures changes deploy successfully before merging
- Reduces production incidents

### Lock Branch
- Use for release branches to prevent any changes
- Useful during code freeze periods

### Require Conversation Resolution
- All PR comments must be resolved before merging
- Ensures feedback is addressed

---

## Verification Steps

After configuring branch protection rules:

1. **Test Direct Push (Should Fail)**
   ```bash
   git checkout main
   git commit --allow-empty -m "test direct push"
   git push origin main
   # Should be rejected
   ```

2. **Test PR Without Review (Should Block)**
   - Create a new branch
   - Make changes and push
   - Open PR to main
   - Try to merge without approval
   - Should be blocked

3. **Test PR Without CI (Should Block)**
   - Create PR
   - Let CI fail
   - Try to merge
   - Should be blocked until checks pass

---

## API Configuration (Alternative)

You can also configure branch protection using GitHub's API:

```bash
curl -X PUT \
  -H "Accept: application/vnd.github+json" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  https://api.github.com/repos/mohamedAskaarrr/rip-to-rest-secrets/branches/main/protection \
  -d '{
    "required_status_checks": {
      "strict": true,
      "contexts": ["build", "test", "security-scan"]
    },
    "enforce_admins": true,
    "required_pull_request_reviews": {
      "dismissal_restrictions": {},
      "dismiss_stale_reviews": true,
      "require_code_owner_reviews": true,
      "required_approving_review_count": 1
    },
    "restrictions": null,
    "allow_force_pushes": false,
    "allow_deletions": false
  }'
```

---

## Current Status

✅ Documentation created
✅ Team roles defined in SECURITY.md
✅ CODEOWNERS file created
⚠️ Branch protection rules must be configured via GitHub UI or API

**Action Required:** Repository administrator must configure the branch protection rules through GitHub Settings.

---

## References

- [GitHub Branch Protection Documentation](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/defining-the-mergeability-of-pull-requests/about-protected-branches)
- [GitHub API - Branch Protection](https://docs.github.com/en/rest/branches/branch-protection)
- [CODEOWNERS Documentation](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/about-code-owners)
