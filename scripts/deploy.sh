#!/bin/bash
set -euo pipefail

# --- Target region ------------------------------------------------------------------
# This lab supports deploying an ADDITIONAL, independent copy into another region in the
# same account (see docs/en/ADDING_A_REGION.md). Choose it explicitly:
#
#     ./scripts/deploy.sh --region ap-northeast-2
#     REGION=ap-northeast-2 ./scripts/deploy.sh
#     AWS_REGION=ap-northeast-2 ./scripts/deploy.sh
#
# Precedence: --region > REGION > AWS_REGION > the profile's region. There is NO literal
# default. It used to be "us-west-2" here while infra/app.py independently defaulted the
# same way, so the two could disagree — the CDK would build region B while every later
# step in this script operated on region A. The resolved value is now pinned into the CDK
# with -c region so they cannot diverge.
REGION_CLI=""
ARGS=()
while [ $# -gt 0 ]; do
    case "$1" in
        --region) shift; REGION_CLI="${1:-}" ;;
        --region=*) REGION_CLI="${1#*=}" ;;
        -h|--help)
            sed -n '1,40p' "$0" | grep '^#' | sed 's/^# \{0,1\}//'
            exit 0 ;;
        *) ARGS+=("$1") ;;
    esac
    shift
done
[ ${#ARGS[@]} -gt 0 ] && { echo "Unknown argument: ${ARGS[0]}" >&2; exit 2; }

ADMIN_EMAIL="${ADMIN_EMAIL:?Set ADMIN_EMAIL environment variable}"
ADMIN_IP_ALLOWLIST="${ADMIN_IP_ALLOWLIST:-0.0.0.0/0}"
REGION="${REGION_CLI:-${REGION:-${AWS_REGION:-$(aws configure get region 2>/dev/null)}}}"
if [ -z "$REGION" ]; then
    echo "ERROR: no region. Pass --region <region>, or set REGION/AWS_REGION." >&2
    echo "       This script will not guess: guessing deploys to the wrong region." >&2
    exit 2
fi
# Everything downstream (aws CLI calls, the CDK, S3 syncs) must use this one value.
export AWS_REGION="$REGION"
export AWS_DEFAULT_REGION="$REGION"
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
             --context admin_ip_allowlist="$ADMIN_IP_ALLOWLIST"
             # Pin the CDK to the same region this script resolved, so infra/app.py
             # cannot pick a different one from the ambient environment.
             --context region="$REGION")
if [ -n "${OWNER_TAG:-}" ]; then
    echo "    (preserving Owner tag: $OWNER_TAG)"
    CDK_CONTEXT+=(--context owner_tag="$OWNER_TAG")
fi
# HOSTED_UI_DOMAIN_EXISTS: set ONLY for a deployment that already has an unmanaged
# Cognito hosted-UI domain with this prefix (see AuthConstruct for why adoption needs
# a delete). Leave unset for a new account so CloudFormation creates the domain.
# API Gateway account-level CloudWatch role. AWS::ApiGateway::Account is a per-account
# PER-REGION singleton implemented as an unconditional PATCH /account, so creating it
# OVERWRITES whatever role the region already has — measured in this account,
# ap-northeast-1 and ap-northeast-2 each already have one owned by an unrelated stack.
# It therefore defaults OFF. But with it off in a region that has none, the stage is
# configured for INFO logging while the account has no role, and execution logs are
# silently absent. So decide it explicitly, per region, from the live value.
APIGW_ROLE_NOW=$(aws apigateway get-account --region "$REGION" \
    --query cloudwatchRoleArn --output text 2>/dev/null)
if [ -z "${APIGW_ACCOUNT_ROLE:-}" ]; then
    if [ "$APIGW_ROLE_NOW" = "None" ] || [ -z "$APIGW_ROLE_NOW" ]; then
        echo "    NOTE: $REGION has no API Gateway account-level CloudWatch role, so API"
        echo "          execution logs will not be emitted. This deploy will NOT create"
        echo "          one (creating it is an account-wide overwrite). If this region is"
        echo "          yours alone, re-run with APIGW_ACCOUNT_ROLE=true to create it."
    else
        echo "    NOTE: $REGION already has an API Gateway account role:"
        echo "          $APIGW_ROLE_NOW"
        echo "          Leaving it alone. Do NOT set APIGW_ACCOUNT_ROLE unless you own it."
    fi
else
    if [ "$APIGW_ROLE_NOW" != "None" ] && [ -n "$APIGW_ROLE_NOW" ] \
       && ! printf '%s' "$APIGW_ROLE_NOW" | grep -q "$STACK_NAME"; then
        echo "REFUSING: APIGW_ACCOUNT_ROLE=true would overwrite an existing account-level" >&2
        echo "          API Gateway role in $REGION that this stack does not own:" >&2
        echo "          $APIGW_ROLE_NOW" >&2
        echo "          That silently breaks another stack's API access logging." >&2
        exit 1
    fi
    echo "    (creating the API Gateway account-level CloudWatch role)"
    CDK_CONTEXT+=(--context apigw_account_role="$APIGW_ACCOUNT_ROLE")
fi
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
# ---------------------------------------------------------------------------------
# Budget-alert deliverability check.
#
# An SNS EMAIL subscription is only live once the recipient clicks the confirmation
# link. CloudFormation reports CREATE_COMPLETE for the REQUEST, never waits, never
# retries, and SNS deletes an unconfirmed pending subscription after ~3 days. So a
# perfectly green stack can have a budget alarm with nowhere to deliver.
#
# That happened here: the subscription created 2026-07-02 was CREATE_COMPLETE in
# CloudFormation while SNS reported "Subscription does not exist" for the same ARN, so
# three days of ~$269 spend against a $200/day budget alerted nobody. Check every time.
ALERT_TOPIC=$(aws sns list-topics --region "$REGION" \
    --query "Topics[?contains(TopicArn,'av30lab-admin-notifications')].TopicArn" \
    --output text 2>/dev/null | head -1)
if [ -n "$ALERT_TOPIC" ]; then
    CONFIRMED=$(aws sns list-subscriptions-by-topic --region "$REGION" \
        --topic-arn "$ALERT_TOPIC" \
        --query "length(Subscriptions[?SubscriptionArn!='PendingConfirmation'])" \
        --output text 2>/dev/null)
    PENDING=$(aws sns list-subscriptions-by-topic --region "$REGION" \
        --topic-arn "$ALERT_TOPIC" \
        --query "length(Subscriptions[?SubscriptionArn=='PendingConfirmation'])" \
        --output text 2>/dev/null)
    if [ "${CONFIRMED:-0}" = "0" ]; then
        echo
        echo "!!! BUDGET ALERTS ARE NOT DELIVERABLE ($ALERT_TOPIC)"
        echo "    confirmed subscriptions: ${CONFIRMED:-0}   pending: ${PENDING:-0}"
        if [ "${PENDING:-0}" != "0" ]; then
            echo "    A confirmation email is waiting for $ADMIN_EMAIL — click the link in it."
            echo "    SNS DELETES the pending request after ~3 days and CloudFormation will"
            echo "    NOT recreate it, because it already considers the resource created."
        else
            echo "    There is no subscription at all. CloudFormation may still show one as"
            echo "    CREATE_COMPLETE — that is the request, not a live subscription."
            echo "    Re-request it, then click the link in the email:"
            echo "      aws sns subscribe --region $REGION --topic-arn $ALERT_TOPIC \\"
            echo "        --protocol email --notification-endpoint $ADMIN_EMAIL"
        fi
        echo "    Until this is confirmed the daily budget alarm alerts nobody."
        echo
    else
        echo ">>> Budget alerts deliverable: ${CONFIRMED} confirmed subscription(s)."
    fi
fi

echo "=== Deployment Complete ==="
echo "Admin Dashboard: $ADMIN_URL"
echo "API Endpoint:    $API_URL"
echo ""
echo "Next steps:"
echo "  1. Create Cognito admin user: aws cognito-idp admin-create-user --user-pool-id $POOL_ID --username admin"
echo "  2. Pre-cache models: HF_TOKEN=xxx ./scripts/cache_models.sh"
