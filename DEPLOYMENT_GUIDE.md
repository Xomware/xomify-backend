# Xomify Backend Deployment Guide

## Overview

The backend has been reorganized into single-purpose Lambda functions with automated testing and smart deployment.

## Lambda Structure

### Single-Route Lambdas (21 total)

Each Lambda handles exactly ONE route or cron job:

#### Friends API (8 lambdas)
- `friends_list` → GET /friends/list
- `friends_pending` → GET /friends/pending
- `friends_profile` → GET /friends/profile
- `friends_all` → GET /friends/all
- `friends_request` → POST /friends/request
- `friends_accept` → POST /friends/accept
- `friends_reject` → POST /friends/reject
- `friends_remove` → DELETE /friends/remove

#### User API (3 lambdas)
- `user_get` → GET /user/user-table
- `user_update` → POST /user/user-table
- `user_all` → GET /user/all

#### Wrapped API (4 lambdas)
- `wrapped_data_get` → GET /wrapped/data
- `wrapped_data_update` → POST /wrapped/data
- `wrapped_month` → GET /wrapped/month
- `wrapped_year` → GET /wrapped/year

#### Release Radar API (2 lambdas)
- `release_radar_history` → GET /release-radar/history
- `release_radar_check` → GET /release-radar/check

#### Cron Jobs (4 lambdas)
- `cron_wrapped` → Monthly wrapped generation
- `cron_release_radar` → Weekly release radar generation
- `cron_wrapped_email` → Monthly wrapped email notifications
- `cron_release_radar_email` → Weekly release radar email notifications

## GitHub Actions Workflow

### Smart Deployment Features

1. **Change Detection**
   - Only deploys lambdas that have changed
   - Detects changes in common layer
   - Uses git diff to identify modified files

2. **Layer Management**
   - If `lambdas/common/` changes:
     - Rebuilds layer
     - Updates ALL lambdas with new layer version
   - If only specific lambdas change:
     - Only deploys those lambdas

3. **Testing**
   - Runs tests before deployment
   - Only tests changed lambdas
   - Blocks deployment if tests fail
   - Parallel test execution

4. **Proper AWS Lambda Updates**
   - Waits for code update to complete using `aws lambda wait function-updated`
   - Then updates configuration (layer)
   - Prevents "ResourceConflictException"

### Workflow Jobs

```
detect-changes → test-lambdas → deploy-layer → update-all-lambdas-layer
                              ↘ deploy-changed-lambdas → summary
```

## Testing

### Test Files Created

- `tests/conftest.py` - Shared fixtures
- `tests/test_user_get.py`
- `tests/test_user_update.py`
- `tests/test_friends_list.py`
- `tests/test_friends_request.py`
- `tests/test_friends_profile.py`
- `tests/test_wrapped_data_get.py`
- `tests/test_release_radar_history.py`

### Running Tests Locally

```bash
# Install dependencies
pip install pytest pytest-cov moto boto3

# Run all tests
pytest tests/ -v

# Run specific test
pytest tests/test_user_get.py -v

# Run with coverage
pytest tests/ -v --cov=lambdas --cov-report=html
```

### Test Structure

Each test uses:
- Mock AWS Lambda context
- Mock API Gateway events
- Dummy data (no real AWS/Spotify calls)
- Proper assertions for success/error cases

## Infrastructure Updates Needed

### AWS Lambda Functions

Create Lambda functions with naming pattern:
```
xomify-{folder_name}
```

Examples:
- `xomify-friends-list` (folder: `friends_list`)
- `xomify-user-get` (folder: `user_get`)
- `xomify-cron-wrapped` (folder: `cron_wrapped`)

**Note:** GitHub Actions converts underscores to hyphens for AWS naming.

### Lambda Layer

Create a layer named:
```
xomify-shared-packages
```

Contains:
- `lambdas/common/` - Shared Python code
- `requirements.txt` - Python dependencies

### API Gateway Routes

Update routes to point to new single-purpose lambdas:

```yaml
GET /friends/list → xomify-friends-list
GET /friends/pending → xomify-friends-pending
POST /friends/request → xomify-friends-request
...etc
```

### CloudWatch Events (Cron)

Schedule cron lambdas:

```yaml
cron(0 9 1 * ? *) → xomify-cron-wrapped (1st of month, 9am)
cron(0 9 ? * SAT *) → xomify-cron-release-radar (Saturdays, 9am)
cron(0 10 1 * ? *) → xomify-cron-wrapped-email (1st of month, 10am)
cron(0 10 ? * SAT *) → xomify-cron-release-radar-email (Saturdays, 10am)
```

## Deployment Process

1. **Push to master**
   ```bash
   git push origin master
   ```

2. **Automatic actions:**
   - Detects changed files
   - Runs tests for changed lambdas
   - Rebuilds layer if common/ changed
   - Deploys only changed lambdas
   - Updates configurations

3. **Monitor progress:**
   - GitHub Actions tab shows real-time progress
   - Summary job shows what was deployed

## Key Benefits

✅ **Faster deployments** - Only changed lambdas deploy
✅ **Safer deployments** - Tests run first, block on failure
✅ **Easier debugging** - Single-purpose functions
✅ **Better scaling** - Independent lambda scaling
✅ **Cleaner code** - No complex routing logic
✅ **Lower costs** - Only update what changed

## Migration Notes

### Old Folders (can be removed after testing)
- `lambdas/friends/` - Replaced by 8 new lambdas
- `lambdas/user/` - Replaced by 3 new lambdas

### Keep These (have shared code)
- `lambdas/wrapped/` - Has cron logic
- `lambdas/release_radar/` - Has cron logic
- `lambdas/wrapped_email/` - Has email logic
- `lambdas/release_radar_email/` - Has email logic
- `lambdas/authorizer/` - Unchanged
- `lambdas/update_user_table/` - Unchanged

## Troubleshooting

### Tests fail in CI
```bash
# Run locally to debug
pytest tests/test_<lambda_name>.py -v
```

### Deployment fails
- Check AWS credentials in GitHub Secrets
- Verify Lambda function names match pattern
- Check CloudWatch logs for Lambda errors

### Layer not updating
- Ensure `lambdas/common/` changes are committed
- Check GitHub Actions logs for layer deployment
- Verify layer ARN in AWS console

## Next Steps

1. Update infrastructure code (Terraform/CloudFormation/SAM)
2. Create Lambda functions in AWS
3. Update API Gateway routes
4. Test deployment with a small change
5. Remove old lambda folders after validation
