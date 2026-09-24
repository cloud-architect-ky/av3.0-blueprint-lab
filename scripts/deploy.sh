#!/bin/bash
set -euo pipefail

ADMIN_EMAIL="${ADMIN_EMAIL:?Set ADMIN_EMAIL environment variable}"
ADMIN_IP_ALLOWLIST="${ADMIN_IP_ALLOWLIST:-0.0.0.0/0}"
REGION="${AWS_REGION:-us-west-2}"
STACK_NAME="Av30BlueprintLabStack"

# --- Where am I actually deploying? -------------------------------------------
# This script uses the ambient credential chain (no --profile anywhere), so an
# AWS_PROFILE left over from unrelated work silently sends the WHOLE lab — Studio
# domain, buckets, Cognito, CloudFront — into someone else's account. That is not
# hypothetical: it nearly happened here, with AWS_PROFILE=bedrock / us-east-1
# resolving to a different account than the lab's.
#
# So: print the resolved identity before doing anything, and hard-fail on a
# mismatch when EXPECTED_ACCOUNT_ID is set. Setting it is strongly recommended and
# costs nothing:
#     EXPECTED_ACCOUNT_ID=123456789012 AWS_PROFILE=... AWS_REGION=... ./scripts/deploy.sh
CALLER=$(aws sts get-caller-identity --output json 2>/dev/null) || {
    echo "ERROR: cannot resolve AWS credentials. Set AWS_PROFILE (and AWS_REGION)." >&2
    exit 1
}
ACCOUNT_ID=$(echo "$CALLER" | jq -r '.Account')
CALLER_ARN=$(echo "$CALLER" | jq -r '.Arn')
if [ -n "${AWS_PROFILE:-}" ]; then
    CRED_SOURCE="AWS_PROFILE=$AWS_PROFILE"
else
    CRED_SOURCE="the default credential chain"
fi

echo "=== AV 3.0 Blueprint Lab Deployment ==="
echo "Account:       $ACCOUNT_ID"
echo "Region:        $REGION"
echo "Identity:      $CALLER_ARN"
echo "Credentials:   $CRED_SOURCE"
echo "Admin:         $ADMIN_EMAIL"
echo "IP Allowlist:  $ADMIN_IP_ALLOWLIST"
echo ""

if [ -n "${EXPECTED_ACCOUNT_ID:-}" ] && [ "$ACCOUNT_ID" != "$EXPECTED_ACCOUNT_ID" ]; then
    echo "ERROR: account mismatch — refusing to deploy." >&2
    echo "  EXPECTED_ACCOUNT_ID = $EXPECTED_ACCOUNT_ID" >&2
    echo "  resolved account    = $ACCOUNT_ID  (from $CRED_SOURCE)" >&2
    echo "  Fix AWS_PROFILE / AWS_REGION and re-run." >&2
    exit 1
fi
if [ -z "${EXPECTED_ACCOUNT_ID:-}" ]; then
    echo "NOTE: EXPECTED_ACCOUNT_ID is not set, so the account above is NOT being checked."
    echo "      Set it to guard against deploying into the wrong account."
    echo ""
fi

cd "$(dirname "$0")/.."

echo ">>> Step 1/6: CDK Deploy (infrastructure)..."
cd infra
if [ ! -d ".venv" ]; then
    python3 -m venv .venv
    source .venv/bin/activate
    pip install -q -r requirements.txt
else
    source .venv/bin/activate
fi
# OWNER_TAG: only needed when UPDATING a stack that was deployed with a different
# Owner tag. SageMaker treats Tags as replacement-requiring, so changing this value
# would rebuild the Studio domain (new domain id, orphaned EFS) — or hard-fail on a
# custom-named resource whose name does not change. Leave unset for a fresh deploy.
CDK_CONTEXT=(--context admin_email="$ADMIN_EMAIL"
             --context admin_ip_allowlist="$ADMIN_IP_ALLOWLIST")
if [ -n "${OWNER_TAG:-}" ]; then
    echo "    (preserving Owner tag: $OWNER_TAG)"
    CDK_CONTEXT+=(--context owner_tag="$OWNER_TAG")
fi
# HOSTED_UI_DOMAIN_EXISTS: set ONLY for a deployment that already has an unmanaged
# Cognito hosted-UI domain with this prefix (see AuthConstruct for why adoption needs
# a delete). Leave unset for a new account so CloudFormation creates the domain.
if [ -n "${HOSTED_UI_DOMAIN_EXISTS:-}" ]; then
    echo "    (hosted-UI domain assumed to exist and stay unmanaged)"
    CDK_CONTEXT+=(--context hosted_ui_domain_exists="$HOSTED_UI_DOMAIN_EXISTS")
fi
npx cdk deploy --require-approval never "${CDK_CONTEXT[@]}"
cd ..

echo ">>> Step 2/6: Reading stack outputs..."
OUTPUTS=$(aws cloudformation describe-stacks --stack-name "$STACK_NAME" --query 'Stacks[0].Outputs' --region "$REGION")
ADMIN_BUCKET=$(echo "$OUTPUTS" | jq -r '.[] | select(.OutputKey=="AdminBucketName") | .OutputValue')
USER_BUCKET=$(echo "$OUTPUTS" | jq -r '.[] | select(.OutputKey=="UserBucketName") | .OutputValue')
ADMIN_CF=$(echo "$OUTPUTS" | jq -r '.[] | select(.OutputKey=="AdminDistributionId") | .OutputValue')
USER_CF=$(echo "$OUTPUTS" | jq -r '.[] | select(.OutputKey=="UserDistributionId") | .OutputValue')
API_URL=$(echo "$OUTPUTS" | jq -r '.[] | select(.OutputKey=="ApiUrl") | .OutputValue')
POOL_ID=$(echo "$OUTPUTS" | jq -r '.[] | select(.OutputKey=="UserPoolId") | .OutputValue')
CLIENT_ID=$(echo "$OUTPUTS" | jq -r '.[] | select(.OutputKey=="UserPoolClientId") | .OutputValue')
ADMIN_URL=$(echo "$OUTPUTS" | jq -r '.[] | select(.OutputKey=="AdminUrl") | .OutputValue')
USER_URL=$(echo "$OUTPUTS" | jq -r '.[] | select(.OutputKey=="UserUrl") | .OutputValue')

echo ">>> Step 3/6: Generating frontend config..."
mkdir -p web/admin/public web/user/public
# Read the hosted-UI URL from the stack rather than assuming the prefix exists. The
# old hardcoded value made config.json look correct even while the UserPoolDomain was
# not declared in the CDK at all, so a fresh account got a config pointing at a
# hostname that does not resolve.
COGNITO_DOMAIN=$(echo "$OUTPUTS" | jq -r '.[] | select(.OutputKey=="CognitoHostedUiUrl") | .OutputValue')
if [ -z "$COGNITO_DOMAIN" ] || [ "$COGNITO_DOMAIN" = "null" ]; then
    echo "ERROR: stack output CognitoHostedUiUrl is missing — the Cognito hosted-UI" >&2
    echo "       domain is not deployed, so admin sign-in cannot work. Refusing to" >&2
    echo "       write a config.json that points at a nonexistent host." >&2
    exit 1
fi
ADMIN_CONFIG="{\"apiBaseUrl\":\"$API_URL\",\"cognitoPoolId\":\"$POOL_ID\",\"cognitoClientId\":\"$CLIENT_ID\",\"region\":\"$REGION\",\"cognitoDomain\":\"$COGNITO_DOMAIN\",\"cognitoRedirectUri\":\"$ADMIN_URL\",\"userDashboardUrl\":\"$USER_URL\"}"
echo "$ADMIN_CONFIG" > web/admin/public/config.json
USER_CONFIG="{\"apiBaseUrl\":\"$API_URL\",\"region\":\"$REGION\"}"
echo "$USER_CONFIG" > web/user/public/config.json

echo ">>> Step 4/6: Building frontends..."
cd web/admin && npm ci --silent && npm run build && cd ../..
cd web/user && npm ci --silent && npm run build && cd ../..

echo ">>> Step 5/6: Uploading to S3..."
aws s3 sync web/admin/dist/ "s3://$ADMIN_BUCKET/" --delete --region "$REGION" --quiet
aws s3 sync web/user/dist/ "s3://$USER_BUCKET/" --delete --region "$REGION" --quiet

echo ">>> Step 6/6: Invalidating CloudFront caches..."
aws cloudfront create-invalidation --distribution-id "$ADMIN_CF" --paths "/*" --output text > /dev/null
aws cloudfront create-invalidation --distribution-id "$USER_CF" --paths "/*" --output text > /dev/null

echo ""
echo "=== Deployment Complete ==="
echo "Admin Dashboard: $ADMIN_URL"
echo "API Endpoint:    $API_URL"
echo ""
echo "Next steps:"
echo "  1. Create Cognito admin user: aws cognito-idp admin-create-user --user-pool-id $POOL_ID --username admin"
echo "  2. Pre-cache models: HF_TOKEN=xxx ./scripts/cache_models.sh"
