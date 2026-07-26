#!/bin/bash
set -euo pipefail

ADMIN_EMAIL="${ADMIN_EMAIL:?Set ADMIN_EMAIL environment variable}"
ADMIN_IP_ALLOWLIST="${ADMIN_IP_ALLOWLIST:-0.0.0.0/0}"
REGION="${AWS_REGION:-us-west-2}"
STACK_NAME="Av30BlueprintLabStack"

echo "=== AV 3.0 Blueprint Lab Deployment ==="
echo "Region: $REGION"
echo "Admin: $ADMIN_EMAIL"
echo "IP Allowlist: $ADMIN_IP_ALLOWLIST"
echo ""

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
npx cdk deploy --require-approval never \
    --context admin_email="$ADMIN_EMAIL" \
    --context admin_ip_allowlist="$ADMIN_IP_ALLOWLIST"
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
COGNITO_DOMAIN="https://av30lab-admin.auth.${REGION}.amazoncognito.com"
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
