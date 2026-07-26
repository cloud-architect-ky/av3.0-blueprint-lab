#!/bin/bash
# cache_models.sh — Pre-cache NVIDIA models to S3 for AV 3.0 Blueprint Lab
# Downloads models from Hugging Face Hub to a local temp directory,
# then syncs to the shared S3 bucket for SageMaker access.
set -uo pipefail

# --------------------------------------------------------------------------
# Configuration
# --------------------------------------------------------------------------
REGION="${AWS_REGION:-us-west-2}"
STACK_NAME="Av30BlueprintLabStack"
TEMP_DIR="${TMPDIR:-/tmp}/av30-model-cache"

# Model registry: name | HF repo | S3 prefix | gated flag
#
# NOTE: Alpamayo-1.5-10B (M6) is intentionally NOT here. M6 loads its weights
# from the HuggingFace OFFLINE cache tree (hf-cache/hub/), not this flat
# model-cache, because at runtime it also pulls a hidden Cosmos-Reason2-8B VLM
# backbone that a flat weights-only copy would miss. The admin populates M6's
# checkpoints as part of the hf-cache run (see README Step 6b / docs/ALPAMAYO_M6.md),
# so a flat model-cache/alpamayo-1.5/ copy would just be unused dead weight.
declare -a MODELS=(
    "Cosmos Reason 1 (7B)|nvidia/Cosmos-Reason1-7B|cosmos-reason1|false"
    "Cosmos Transfer 2.5 (2B)|nvidia/Cosmos-Transfer2.5-2B|cosmos-transfer2.5|true"
    "Cosmos Predict 2.5 (2B)|nvidia/Cosmos-Predict2.5-2B|cosmos-predict2.5|true"
)

# --------------------------------------------------------------------------
# Pre-flight checks
# --------------------------------------------------------------------------
echo "=== AV 3.0 Blueprint Lab — Model Pre-caching ==="
echo ""

# Check HF_TOKEN
if [ -z "${HF_TOKEN:-}" ]; then
    echo "ERROR: HF_TOKEN environment variable is not set."
    echo ""
    echo "To obtain a token:"
    echo "  1. Go to https://huggingface.co/settings/tokens"
    echo "  2. Create a token with 'read' access"
    echo "  3. For gated models (Alpamayo), accept the license at the model page first"
    echo "  4. Export the token: export HF_TOKEN=hf_..."
    echo ""
    exit 1
fi

# Check required CLI tools
for cmd in hf aws jq; do
    if ! command -v "$cmd" &> /dev/null; then
        echo "ERROR: '$cmd' is not installed or not in PATH."
        if [ "$cmd" = "hf" ]; then
            echo "  Install: pip install huggingface_hub"
        fi
        exit 1
    fi
done

# Resolve S3 bucket name
if [ -n "${MODEL_BUCKET:-}" ]; then
    BUCKET="$MODEL_BUCKET"
    echo "Using bucket from MODEL_BUCKET env var: $BUCKET"
elif [ -n "${1:-}" ]; then
    BUCKET="$1"
    echo "Using bucket from argument: $BUCKET"
else
    echo "Resolving bucket from CloudFormation stack '$STACK_NAME'..."
    OUTPUTS=$(aws cloudformation describe-stacks \
        --stack-name "$STACK_NAME" \
        --query 'Stacks[0].Outputs' \
        --region "$REGION" 2>/dev/null) || {
        echo "ERROR: Could not read CloudFormation stack '$STACK_NAME' in $REGION."
        echo "  Either deploy the stack first, or pass the bucket name:"
        echo "  MODEL_BUCKET=my-bucket ./scripts/cache_models.sh"
        echo "  ./scripts/cache_models.sh my-bucket-name"
        exit 1
    }
    BUCKET=$(echo "$OUTPUTS" | jq -r '.[] | select(.OutputKey=="SharedDataBucketArn") | .OutputValue' | sed 's|arn:aws:s3:::||')
    if [ -z "$BUCKET" ] || [ "$BUCKET" = "null" ]; then
        echo "ERROR: Could not find SharedDataBucketArn in stack outputs."
        exit 1
    fi
    echo "Resolved bucket from stack: $BUCKET"
fi

echo "Region:    $REGION"
echo "Bucket:    $BUCKET"
echo "Temp dir:  $TEMP_DIR"
echo ""

# Authenticate with Hugging Face
export HF_TOKEN="$HF_TOKEN"
hf auth login --token "$HF_TOKEN" 2>/dev/null || true

# --------------------------------------------------------------------------
# Download and sync models
# --------------------------------------------------------------------------
mkdir -p "$TEMP_DIR"

SUCCESS_COUNT=0
FAIL_COUNT=0
declare -a FAILED_MODELS=()
declare -a SUCCESS_MODELS=()

TOTAL=${#MODELS[@]}
CURRENT=0

for entry in "${MODELS[@]}"; do
    IFS='|' read -r NAME REPO PREFIX GATED <<< "$entry"
    CURRENT=$((CURRENT + 1))

    echo "---------------------------------------------------------------"
    echo "[$CURRENT/$TOTAL] $NAME"
    echo "  Repository: $REPO"
    echo "  Destination: s3://$BUCKET/model-cache/$PREFIX/"
    if [ "$GATED" = "true" ]; then
        echo "  NOTE: Gated model — requires license acceptance at https://huggingface.co/$REPO"
    fi
    echo ""

    LOCAL_PATH="$TEMP_DIR/$PREFIX"
    mkdir -p "$LOCAL_PATH"

    # Step 1: Download from Hugging Face
    echo "  Downloading from Hugging Face..."
    if ! hf download "$REPO" \
        --local-dir "$LOCAL_PATH" \
        --token "$HF_TOKEN" 2>&1 | tail -5; then
        echo "  FAILED: Download failed for $NAME"
        echo "  Possible causes:"
        if [ "$GATED" = "true" ]; then
            echo "    - License not accepted: visit https://huggingface.co/$REPO"
        fi
        echo "    - Invalid or expired HF_TOKEN"
        echo "    - Network connectivity issue"
        echo ""
        FAIL_COUNT=$((FAIL_COUNT + 1))
        FAILED_MODELS+=("$NAME")
        continue
    fi

    # Step 2: Sync to S3
    echo "  Syncing to S3..."
    if ! aws s3 sync "$LOCAL_PATH" "s3://$BUCKET/model-cache/$PREFIX/" \
        --region "$REGION" \
        --only-show-errors; then
        echo "  FAILED: S3 upload failed for $NAME"
        FAIL_COUNT=$((FAIL_COUNT + 1))
        FAILED_MODELS+=("$NAME")
        continue
    fi

    echo "  OK: $NAME cached successfully."
    echo ""
    SUCCESS_COUNT=$((SUCCESS_COUNT + 1))
    SUCCESS_MODELS+=("$NAME")
done

# --------------------------------------------------------------------------
# Cleanup and summary
# --------------------------------------------------------------------------
echo ""
echo "==============================================================="
echo "=== Model Pre-caching Summary ==="
echo "==============================================================="
echo ""
echo "  Successful: $SUCCESS_COUNT / $TOTAL"
if [ ${#SUCCESS_MODELS[@]} -gt 0 ]; then
    for m in "${SUCCESS_MODELS[@]}"; do
        echo "    [OK] $m"
    done
fi
echo ""
echo "  Failed:     $FAIL_COUNT / $TOTAL"
if [ ${#FAILED_MODELS[@]} -gt 0 ]; then
    for m in "${FAILED_MODELS[@]}"; do
        echo "    [FAIL] $m"
    done
fi
echo ""
echo "  S3 location: s3://$BUCKET/model-cache/"
echo ""

# Offer cleanup
read -r -p "Remove local temp files ($TEMP_DIR)? [Y/n] " CLEANUP
CLEANUP="${CLEANUP:-Y}"
if [[ "$CLEANUP" =~ ^[Yy] ]]; then
    rm -rf "$TEMP_DIR"
    echo "  Temp files removed."
else
    echo "  Temp files kept at: $TEMP_DIR"
fi

echo ""
if [ $FAIL_COUNT -gt 0 ]; then
    echo "Some models failed. Re-run after fixing the issues above."
    exit 1
fi
echo "All models cached successfully."
