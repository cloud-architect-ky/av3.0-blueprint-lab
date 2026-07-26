#!/bin/bash
# alpasim_ec2_setup.sh — ADMIN one-time: build + run REAL AlpaSim closed-loop
# evaluation of the Alpamayo 1.5 driver on a Docker-capable GPU EC2 host, then
# upload the genuine results to the shared S3 bucket for M7 to visualize.
#
# WHY THIS RUNS ON EC2, NOT IN THE M7 NOTEBOOK
# --------------------------------------------
# AlpaSim (github.com/NVlabs/alpasim) is NOT a Python library — it is a fleet of
# gRPC microservices (renderer / driver / physics / runtime / controller)
# orchestrated by Docker Compose. A SageMaker Studio JupyterLab app is itself a
# managed container with NO Docker daemon, so it cannot host AlpaSim (this is the
# same reason M4/M5/M6 were built as uv venvs, not containers). Therefore the
# admin runs AlpaSim ONCE here on a dedicated GPU host, uploads the real outputs,
# and the M7 notebook (CPU) downloads + visualizes them. Every participant sees
# the same genuine closed-loop evaluation without each paying for a GPU host.
#
# M6 -> M7 LINK (honest): AlpaSim does NOT consume M6's predicted-trajectory .npy.
# It loads the SAME Alpamayo-1.5-10B checkpoint (from the shared hf-cache that M6
# populated) and drives it closed-loop. M6 = open-loop trajectory prediction of
# Alpamayo; M7 = the same model driving in the AlpaSim loop. Shared artifact = the
# checkpoint, not the trajectory file.
#
# HOST REQUIREMENTS
# -----------------
# Run on a Docker + NVIDIA-Container-Toolkit GPU host (the AWS Deep Learning Base
# GPU AMI ships Docker, the toolkit, and driver >= 570). GPU placement is decided
# by AlpaSim's topology config (see TOPOLOGY below), confirmed from the repo:
#   - topology=1gpu : renderer+driver+physics ALL on GPU 0 -> needs ONE >=80 GB
#     card (A100 80GB / H100). The ~40 GB driver + co-resident renderer won't fit
#     on 48 GB.
#   - topology=2gpu : driver on GPU 0, renderer on GPU 1, physics on both -> each
#     card needs >=40 GB. L40S 48 GB x2 (g6e.12xlarge) fits. RECOMMENDED default.
#   24 GB cards (A10G/L4) do NOT fit the 40 GB driver either way.
#
# USAGE — ADMIN reference run (on the EC2 host, admin lab-account role):
#     export HF_TOKEN=hf_xxx                 # accepted Alpamayo + NuRec licenses
#     export NGC_API_KEY=nvapi-xxx           # for the gated NuRec (NRE) image
#     export SHARED_BUCKET=av30lab-shared-data-<acct>   # else derived via STS
#     bash scripts/alpasim_ec2_setup.sh
#     # → uploads to s3://<shared>/m7-reference/, then TERMINATE the instance.
#
# USAGE — PARTICIPANT self-run (participant on their own pre-provisioned GPU host,
# reached via SSM; see docs/M7_PARTICIPANT_SSM_RUNBOOK.md):
#     export PARTICIPANT_ID=<id>
#     export M7_OUTPUT_PREFIX=users/<id>/m7
#     export OUTPUT_BUCKET=av30lab-user-workspace-<acct>
#     export SHARED_BUCKET=av30lab-shared-data-<acct>   # hf-cache read
#     bash scripts/alpasim_ec2_setup.sh
#     # → uploads to s3://<user-workspace>/users/<id>/m7/; the admin terminates.
#
# With no PARTICIPANT_ID/M7_OUTPUT_PREFIX/OUTPUT_BUCKET set, behaviour is
# byte-for-byte the legacy admin run (writes s3://$SHARED_BUCKET/m7-reference/).
# It is idempotent where practical (re-clone/re-restore skip if present).
set -uo pipefail

# SSM RunCommand runs as root but may not export HOME/USER; several installers
# (uv, rustup) and `source "$HOME/..."` need it. Default under `set -u`.
export HOME="${HOME:-/root}"
export USER="${USER:-root}"
# rustup/cargo + uv install to these; make them visible for the rest of the run.
export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"

# --------------------------------------------------------------------------
# Configuration
# --------------------------------------------------------------------------
# Prefer the instance-store NVMe if the DLAMI mounted one, else the EBS root.
if [ -d /opt/dlami/nvme ]; then
    WORK="${ALPASIM_WORK:-/opt/dlami/nvme/alpasim-work}"
else
    WORK="${ALPASIM_WORK:-$HOME/alpasim-work}"
fi
REPO_DIR="$WORK/alpasim"
REPO_URL="https://github.com/NVlabs/alpasim.git"
REPO_TAG="${ALPASIM_TAG:-alpasim-base-v0.96.0}"   # pin; empty ALPASIM_TAG => default branch
LOG_DIR="$WORK/out"
HF_HOME_DIR="${HF_HOME:-$WORK/hf}"

# One demo scene (verified present in data/scenes/sim_scenes.csv, 26.01 OSS set).
SCENE_ID="${SCENE_ID:-clipgt-01d503d4-449b-46fc-8d78-9085e70d3554}"
# 2gpu = driver(GPU0) + renderer(GPU1); use 1gpu only on a single >=80 GB card.
TOPOLOGY="${TOPOLOGY:-2gpu}"
NRE_IMAGE="${NRE_IMAGE:-nvcr.io/nvidia/nre/nre-ga:26.04}"

# Output routing. Two modes, decided purely by env (defaults => legacy admin mode):
#   - ADMIN reference run (default): PARTICIPANT_ID unset, results go to the shared
#     bucket under m7-reference/ (one run, shared by all participants).
#   - PARTICIPANT self-run: set PARTICIPANT_ID=<id>, M7_OUTPUT_PREFIX=users/<id>/m7,
#     OUTPUT_BUCKET=<user-workspace-bucket> so each participant writes their OWN
#     results and they never collide. See docs/M7_PARTICIPANT_SSM_RUNBOOK.md.
PARTICIPANT_ID="${PARTICIPANT_ID:-}"
M7_OUTPUT_PREFIX="${M7_OUTPUT_PREFIX:-m7-reference}"

echo "=== AV 3.0 Blueprint Lab — M7 AlpaSim reference evaluation (admin, EC2) ==="
echo "work dir  : $WORK"
echo "scene     : $SCENE_ID"
echo "topology  : $TOPOLOGY"
echo "HF_HOME   : $HF_HOME_DIR"
echo ""

# --------------------------------------------------------------------------
# Pre-flight
# --------------------------------------------------------------------------
FAIL=0
if ! command -v nvidia-smi &>/dev/null; then
    echo "ERROR: nvidia-smi not found — this must run on a GPU host."; FAIL=1
else
    # GPU-COUNT guard: topology=2gpu puts the renderer on GPU 1, so we need >=2
    # GPUs; topology=1gpu needs 1 (but a >=80 GB card). Catch the common mistake
    # of picking a big-vCPU-but-single-GPU box (e.g. g6e.16xlarge has 1 GPU while
    # g6e.12xlarge has 4) NOW, before the ~30 min build, instead of failing at
    # launch with 'renderer requested GPUs [1] but only 0 .. 0 are available'.
    GPU_COUNT=$(nvidia-smi --query-gpu=name --format=csv,noheader 2>/dev/null | grep -c .)
    NEED=$([ "$TOPOLOGY" = "1gpu" ] && echo 1 || echo 2)
    echo "[preflight] GPUs detected: $GPU_COUNT (topology=$TOPOLOGY needs >= $NEED)"
    if [ "${GPU_COUNT:-0}" -lt "$NEED" ]; then
        echo "ERROR: topology=$TOPOLOGY needs >= $NEED GPU(s) but this host has $GPU_COUNT."
        echo "       AWS instance-name size is NOT the GPU count: in g6e, only 12xlarge(4),"
        echo "       24xlarge(4), 48xlarge(8) are multi-GPU — xlarge..8xlarge AND 16xlarge"
        echo "       are single-GPU. For topology=2gpu use g6e.12xlarge (4x L40S 48GB)."
        echo "       (A single >=80GB card can run TOPOLOGY=1gpu instead.)"
        FAIL=1
    fi
fi
if ! command -v docker &>/dev/null; then
    echo "ERROR: docker not found — use a Docker-capable host (DL Base GPU AMI)."; FAIL=1
fi
if ! docker compose version &>/dev/null 2>&1; then
    echo "ERROR: 'docker compose' plugin not available."; FAIL=1
fi
# NVIDIA container runtime (renderer/driver need --gpus).
if ! docker run --rm --gpus all nvidia/cuda:12.8.0-base-ubuntu22.04 nvidia-smi &>/dev/null; then
    echo "WARN: could not verify the NVIDIA container runtime with a test container"
    echo "      (docker run --gpus all ...). Continuing, but the sim needs it."
fi
if [ -z "${HF_TOKEN:-}" ]; then
    echo "ERROR: HF_TOKEN not set (needed to download the gated NuRec scene)."; FAIL=1
fi
# NGC_API_KEY is OPTIONAL: gate-0 (2026-07-12) confirmed nre-ga:26.04 is
# PUBLIC_PULLABLE (anonymous pull works). A key is only a fallback in case NVIDIA
# later gates the image. So we don't fail without it — just note it.
if [ -z "${NGC_API_KEY:-}" ]; then
    echo "Note: NGC_API_KEY not set. The NRE renderer image $NRE_IMAGE is public"
    echo "      (verified), so anonymous pull should work. Set NGC_API_KEY only if"
    echo "      the pull is later denied."
fi
[ "$FAIL" -eq 0 ] || { echo "Pre-flight failed — fix the above and re-run."; exit 1; }

# uv (>=0.9.17) and cargo (for utils_rs) — install if missing.
if ! command -v uv &>/dev/null; then
    echo "[deps] installing uv ..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    # shellcheck disable=SC1090
    [ -f "$HOME/.local/bin/env" ] && source "$HOME/.local/bin/env"
    export PATH="$HOME/.local/bin:$PATH"
fi
if ! command -v cargo &>/dev/null; then
    echo "[deps] installing Rust toolchain (cargo) ..."
    curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y
    # shellcheck disable=SC1091
    [ -f "$HOME/.cargo/env" ] && source "$HOME/.cargo/env"
    export PATH="$HOME/.cargo/bin:$PATH"
fi

mkdir -p "$WORK" "$HF_HOME_DIR"
export HF_HOME="$HF_HOME_DIR"

# --------------------------------------------------------------------------
# Resolve the shared bucket (env, else STS-derived default)
# --------------------------------------------------------------------------
if [ -z "${SHARED_BUCKET:-}" ]; then
    _acct="$(aws sts get-caller-identity --query Account --output text 2>/dev/null || true)"
    [ -n "$_acct" ] && SHARED_BUCKET="av30lab-shared-data-${_acct}"
fi
[ -n "${SHARED_BUCKET:-}" ] || { echo "ERROR: SHARED_BUCKET unresolved."; exit 1; }
echo "[s3] shared bucket: $SHARED_BUCKET"

# Where the results get written. Defaults to the shared bucket (admin reference
# mode); a participant self-run sets OUTPUT_BUCKET to their user-workspace bucket.
OUTPUT_BUCKET="${OUTPUT_BUCKET:-$SHARED_BUCKET}"
if [ -n "$PARTICIPANT_ID" ]; then
    echo "[s3] participant self-run: id=$PARTICIPANT_ID output=s3://$OUTPUT_BUCKET/$M7_OUTPUT_PREFIX/"
else
    echo "[s3] admin reference run: output=s3://$OUTPUT_BUCKET/$M7_OUTPUT_PREFIX/"
fi

# --------------------------------------------------------------------------
# Restore the Alpamayo 1.5 + Cosmos-Reason2 checkpoints from the shared hf-cache
# (populated by M6). AlpaSim's driver container bind-mounts $HF_HOME into
# /root/.cache/huggingface (base_config.yaml), so a warm cache means no
# re-download and no re-accepting the gated MODEL license at driver-load time.
# --------------------------------------------------------------------------
if [ -d "$HF_HOME_DIR/hub" ] && ls "$HF_HOME_DIR/hub"/models--nvidia--Alpamayo-* >/dev/null 2>&1; then
    echo "[hf-cache] Alpamayo already present in $HF_HOME_DIR/hub — skipping restore"
else
    echo "[hf-cache] Restoring checkpoints from s3://$SHARED_BUCKET/hf-cache/hub/ ..."
    mkdir -p "$HF_HOME_DIR/hub"
    aws s3 sync "s3://$SHARED_BUCKET/hf-cache/hub/" "$HF_HOME_DIR/hub/" --only-show-errors \
        && echo "[hf-cache] restore complete" \
        || echo "[hf-cache] WARN: restore failed; driver will fall back to HF download (HF_TOKEN)."
fi

# --------------------------------------------------------------------------
# Clone AlpaSim (pinned) + NGC login for the gated renderer image
# --------------------------------------------------------------------------
if [ -d "$REPO_DIR/.git" ]; then
    echo "[clone] $REPO_DIR already present — skipping"
else
    echo "[clone] cloning $REPO_URL (tag=${REPO_TAG:-<default branch>}) ..."
    if [ -n "$REPO_TAG" ]; then
        git clone --depth 1 --branch "$REPO_TAG" "$REPO_URL" "$REPO_DIR" 2>&1 | tail -3 \
            || { echo "[clone] tag $REPO_TAG not found — falling back to default branch";
                 git clone --depth 1 "$REPO_URL" "$REPO_DIR" 2>&1 | tail -3; }
    else
        git clone --depth 1 "$REPO_URL" "$REPO_DIR" 2>&1 | tail -3
    fi
fi
cd "$REPO_DIR" || { echo "ERROR: cannot cd $REPO_DIR"; exit 1; }

# NGC: log in only if a key is provided (the NRE image is public, so anonymous
# pull normally works — see gate-0). Then confirm the renderer image is reachable
# before the long build, whichever auth path applies.
if [ -n "${NGC_API_KEY:-}" ]; then
    echo "[ngc] docker login nvcr.io (key provided) ..."
    echo "$NGC_API_KEY" | docker login nvcr.io -u '$oauthtoken' --password-stdin \
        || echo "[ngc] WARN: NGC login failed; trying anonymous pull (image is public)."
else
    echo "[ngc] no NGC_API_KEY — using anonymous pull (nre-ga is public)."
fi
if docker manifest inspect "$NRE_IMAGE" >/dev/null 2>&1; then
    echo "[ngc] renderer image accessible: $NRE_IMAGE"
else
    echo "ERROR: cannot access $NRE_IMAGE (neither anonymous nor keyed). If NVIDIA"
    echo "       has gated it, set NGC_API_KEY with access and re-run."
    exit 1
fi

# --------------------------------------------------------------------------
# Build the AlpaSim environment (compiles protos, installs alpasim_wizard).
# setup_local_env.sh MUST be sourced, not executed.
# --------------------------------------------------------------------------
echo "[build] source setup_local_env.sh (protos + uv sync + wizard CLI) ..."
# shellcheck disable=SC1091
source ./setup_local_env.sh || { echo "ERROR: setup_local_env.sh failed."; exit 1; }

# The wizard bind-mounts these host dirs into the service containers and fails
# with "Mount point does not exist" if any is absent. The Alpamayo driver loads
# its weights from the HF cache (not /mnt/drivers), and we don't use trafficsim,
# so these can be empty — but the directories must exist. nre-artifacts is
# created by the scene download; create the rest up front.
echo "[dirs] ensuring wizard mount-point dirs exist ..."
mkdir -p "$REPO_DIR/data/drivers" \
         "$REPO_DIR/data/nre-artifacts/ego-hoods" \
         "$REPO_DIR/data/trafficsim-models"

# --------------------------------------------------------------------------
# Run the real closed-loop evaluation (single demo scene, standard inference).
# CFG-nav stays OFF (default) so the driver fits ~40 GB. REASONING_OVERLAY adds
# the Chain-of-Causation overlay to the eval video (ties back to M6's reasoning).
# --------------------------------------------------------------------------
# Inject HF env into the DRIVER container so it loads Alpamayo from the mounted
# HF cache OFFLINE (no token, no network). Without this the driver hits the gated
# repo online and dies with a 401 — the base driver service has no `environments`.
# (Same offline-cache lesson as M6; see docs/ALPAMAYO_M6.md.) CLI list overrides
# with `KEY=VALUE` items break Hydra's grammar, so we drop a small deploy config
# `deploy/local_m7.yaml` (extends `local`) that sets driver.environments, and
# select it with deploy=local_m7.
DEPLOY_OVERRIDE="$REPO_DIR/src/wizard/configs/deploy/local_m7.yaml"
echo "[run] writing $DEPLOY_OVERRIDE (driver HF-offline env) ..."
cat > "$DEPLOY_OVERRIDE" <<'YAML'
# @package _global_
# M7 deploy: local containers + HF-offline env on the driver so Alpamayo loads
# from the mounted HF cache without a token or network (avoids the gated 401).
defaults:
  - local
  - _self_
services:
  driver:
    environments:
      - HF_TOKEN
      - HF_HOME=/root/.cache/huggingface
      - HF_HUB_OFFLINE=1
      - TRANSFORMERS_OFFLINE=1
YAML

# Custom topology: the stock `2gpu` puts THREE driver replicas on GPU 0 (plus
# physics) — three 40 GB Alpamayo copies do not fit an L40S (46 GB) and OOM. This
# 4-GPU layout gives the driver GPU 0 ALL to itself (one replica), renderer GPU 1,
# physics GPU 2, trafficsim GPU 3 — so the 40 GB driver fits with headroom. One
# demo scene needs no concurrency, so rollouts-per-service = 1.
TOPO_OVERRIDE="$REPO_DIR/src/wizard/configs/topology/m7_4gpu.yaml"
echo "[run] writing $TOPO_OVERRIDE (driver alone on GPU 0) ..."
cat > "$TOPO_OVERRIDE" <<'YAML'
# @package _global_
# M7 4-GPU layout: driver alone on GPU 0 (40 GB Alpamayo fits an L40S 46 GB),
# renderer GPU 1, physics GPU 2, trafficsim GPU 3. One replica each, 1 rollout.
defines:
  nre_cache_size: 2
services:
  renderer:
    gpus: [1]
    replicas_per_container: 1
  driver:
    replicas_per_container: 1
    gpus: [0]
  physics:
    replicas_per_container: 1
    gpus: [2]
  trafficsim:
    replicas_per_container: 1
    gpus: [3]
  controller:
    replicas_per_container: 1
    gpus: null
runtime:
  nr_workers: 1
  endpoints:
    renderer:
      n_concurrent_rollouts: 1
    driver:
      n_concurrent_rollouts: 1
    physics:
      n_concurrent_rollouts: 1
      skip: false
    controller:
      n_concurrent_rollouts: 1
    trafficsim:
      n_concurrent_rollouts: 1
      skip: true
YAML
TOPOLOGY="m7_4gpu"

echo "[run] alpasim_wizard deploy=local_m7 topology=$TOPOLOGY driver=alpamayo1_5 scene=$SCENE_ID ..."
uv run alpasim_wizard \
    deploy=local_m7 \
    topology="$TOPOLOGY" \
    driver=alpamayo1_5 \
    scenes.scene_ids="['$SCENE_ID']" \
    wizard.log_dir="$LOG_DIR" \
    eval.video.video_layouts=[REASONING_OVERLAY]
RUN_RC=$?
if [ "$RUN_RC" -ne 0 ]; then
    echo "ERROR: alpasim_wizard exited $RUN_RC — inspect $LOG_DIR and 'docker compose logs'."
    exit 1
fi

# --------------------------------------------------------------------------
# Verify the genuine outputs exist
# --------------------------------------------------------------------------
AGG="$LOG_DIR/aggregate"
echo "[verify] checking outputs under $LOG_DIR ..."
MISSING=0
[ -s "$AGG/metrics_results.txt" ] || { echo "  MISSING aggregate/metrics_results.txt"; MISSING=1; }
[ -s "$AGG/metrics_results.png" ] || echo "  (note) aggregate/metrics_results.png missing"
ls "$LOG_DIR"/rollouts/**/metrics.parquet >/dev/null 2>&1 \
    || ls "$LOG_DIR"/rollouts/*/*/metrics.parquet >/dev/null 2>&1 \
    || { echo "  MISSING rollouts/**/metrics.parquet"; MISSING=1; }
_mp4="$(ls "$LOG_DIR"/rollouts/*/*.mp4 "$AGG"/videos/*/*.mp4 2>/dev/null | head -1)"
[ -n "$_mp4" ] || echo "  (note) no eval mp4 found"
[ "$MISSING" -eq 0 ] || { echo "ERROR: required outputs missing — not uploading."; exit 1; }
echo "[verify] core outputs present."

# --------------------------------------------------------------------------
# Upload the genuine results for the M7 notebook to read.
#   - admin mode  : s3://<shared>/m7-reference/           (shared by all)
#   - participant : s3://<user-workspace>/users/<id>/m7/  (their own)
# The EC2 host uses an instance-profile that can write the chosen location; the
# SageMaker exec role is not involved in this upload.
# --------------------------------------------------------------------------
REF="s3://${OUTPUT_BUCKET}/${M7_OUTPUT_PREFIX}"
echo "[upload] -> $REF/ ..."
aws s3 sync "$AGG" "$REF/aggregate/" --only-show-errors
# one representative eval video (keep the upload small)
[ -n "$_mp4" ] && aws s3 cp "$_mp4" "$REF/eval/eval.mp4" --only-show-errors
# per-rollout parquet(s)
for pq in $(ls "$LOG_DIR"/rollouts/*/*/metrics.parquet 2>/dev/null); do
    sc="$(basename "$(dirname "$(dirname "$pq")")")"
    ba="$(basename "$(dirname "$pq")")"
    aws s3 cp "$pq" "$REF/rollouts/$sc/$ba/metrics.parquet" --only-show-errors
done

# A small provenance manifest the notebook can read.
if [ -n "$PARTICIPANT_ID" ]; then
    _run_kind="participant self-run (participant ran AlpaSim on their own GPU host)"
else
    _run_kind="admin reference evaluation (one-time, shared across participants)"
fi
cat > "$WORK/run.json" <<JSON
{
  "module": "M7_AlpaSim_ClosedLoop",
  "simulator": "AlpaSim (NVlabs/alpasim)",
  "driver": "alpamayo1_5",
  "model": "nvidia/Alpamayo-1.5-10B",
  "scene_id": "$SCENE_ID",
  "topology": "$TOPOLOGY",
  "renderer_image": "$NRE_IMAGE",
  "instance_type": "${INSTANCE_TYPE:-unknown}",
  "participant_id": "${PARTICIPANT_ID:-}",
  "run_kind": "$_run_kind"
}
JSON
aws s3 cp "$WORK/run.json" "$REF/run.json" --only-show-errors

echo ""
echo "=== DONE — genuine AlpaSim results uploaded to $REF/ ==="
echo "    aggregate/metrics_results.txt|png, rollouts/**/metrics.parquet, eval/eval.mp4, run.json"
echo ""
if [ -n "$PARTICIPANT_ID" ]; then
    echo ">>> Participant $PARTICIPANT_ID: results are in $REF/ — open M7 in your"
    echo "    SageMaker workspace (CPU) and Run All to visualize them."
    echo ""
    echo "!!! You CANNOT terminate this instance yourself. Tell the workshop admin"
    echo "    you are DONE so they can terminate it and stop the ~\$10.5/hr charge."
else
    echo "!!! REMEMBER TO TERMINATE THIS GPU INSTANCE to stop charges:"
    echo "    aws ec2 terminate-instances --instance-ids <this-instance-id>"
fi
