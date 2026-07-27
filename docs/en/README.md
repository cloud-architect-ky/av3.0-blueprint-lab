<!-- Language: **English** · [한국어](../ko/README.md) · [日本語](../ja/README.md) -->

# AV 3.0 Blueprint Lab

**Docs language:** **English** · [한국어](../ko/README.md) · [日本語](../ja/README.md)

A self-service AWS platform for hands-on execution of the [Building an End-to-End Physical AI Data Pipeline for Autonomous Vehicle 3.0 on AWS with NVIDIA](https://aws.amazon.com/blogs/industries/building-an-end-to-end-physical-ai-data-pipeline-for-autonomous-vehicle-3-0-on-aws-with-nvidia/).
Participants work through **12 Jupyter notebook modules
(M0–M11)** covering the full autonomous-vehicle data pipeline — data exploration,
video captioning (Cosmos Reason), data curation (Cosmos Curator), synthetic
augmentation (Cosmos Transfer & Predict), vision-language-action inference
(Alpamayo), closed-loop simulation (AlpaSim), semantic search, distributed
training, 3D reconstruction, and production pipeline automation.

The platform deploys as a **single AWS CDK stack** with admin + participant
dashboards, multi-user SageMaker Studio provisioning, and automated cost controls.
Anyone can deploy it into **their own AWS account**.

> This repository ships **workshop code and docs only**. It orchestrates
> third-party models and datasets (NVIDIA Cosmos/Alpamayo, nuScenes, NuRec) that
> you download yourself under **their own licenses** — some **non-commercial**.
> See [NOTICE](../../NOTICE).

---

## The 12 modules

| Module | What it does | Recommended instance |
|---|---|---|
| **M0** | Pipeline overview — maps the end-to-end pipeline to the modules (no compute) | `ml.t3.medium` (CPU) |
| **M1** | Data Exploration — ingest & explore real **nuScenes-mini** sensor data; select scenes | `ml.t3.medium` (CPU) |
| **M2** | Cosmos Reason Captioning — VLM captions of sampled clips | `ml.g5.12xlarge` (GPU) |
| **M3** | Cosmos Curator — **NeMo Curator** video curation (split, transcode, filter, dedup) | `ml.g5.12xlarge` (GPU) |
| **M4** | Cosmos Transfer — weather/condition augmentation of real clips | GPU (`ml.g6.24xlarge` verified) |
| **M5** | Cosmos Predict — synthetic scenario (video2world) generation | GPU (`ml.g6.24xlarge` verified) |
| **M6** | Alpamayo VLA — **Alpamayo-1.5-10B** vision-language-action inference + trajectory | GPU (`ml.g6.24xlarge` verified) |
| **M7** | AlpaSim Closed-Loop Eval — visualize genuine closed-loop policy evaluation | `ml.t3.medium` (CPU) + GPU EC2 |
| **M8** | OpenSearch Semantic Search — k-NN retrieval over caption embeddings | `ml.t3.medium` (CPU) |
| **M9** | HyperPod Distributed Training — a real 2-node `torch.distributed` DDP job | `ml.t3.medium` (CPU) + job nodes |
| **M10** | Nerfstudio 3D Reconstruction — NeRF / 3D Gaussian Splatting (optional/demo) | `ml.g5.xlarge` (GPU) |
| **M11** | Pipeline Automation — a real SageMaker Pipeline (Caption→Curate→Augment) | `ml.t3.medium` (CPU) + processing job |

Recommended path: **M0 → M1 → M2 → M3**, then branch to synthetic data (M4/M5),
policy + simulation (M6/M7), search (M8), or production patterns (M9/M11).
Instances shown are the dashboard defaults; each GPU module also offers
alternatives (e.g. `ml.g6.12xlarge` when `ml.g5.12xlarge` capacity is short).

---

## Which docs to read

The full guides live under **`docs/<lang>/`** in **English / 한국어 / 日本語**
(the links below point to the docs in this language directory; use the switcher
at the top of the page to change language):

| You are… | Read (in order) |
|---|---|
| **Admin — setting up the lab** | [PREREQUISITES](PREREQUISITES.md) → [ADMIN_GUIDE](ADMIN_GUIDE.md) → [DATA_CONTRACT](DATA_CONTRACT.md) |
| **Participant** | [PRE_LEARNING_GUIDE](PRE_LEARNING_GUIDE.md) → [PARTICIPANT_GUIDE](PARTICIPANT_GUIDE.md) |
| **Per-module deep dives** | [COSMOS_M4_M5](COSMOS_M4_M5.md) · [ALPAMAYO_M6](ALPAMAYO_M6.md) · [ALPASIM_M7](ALPASIM_M7.md) · [HYPERPOD_M9](HYPERPOD_M9.md) · [PIPELINE_M11](PIPELINE_M11.md) |
| **M7 GPU / SSM (advanced)** | [M7_MANUAL_TEST_RUNBOOK](M7_MANUAL_TEST_RUNBOOK.md) (admin) · [M7_PARTICIPANT_SSM_RUNBOOK](M7_PARTICIPANT_SSM_RUNBOOK.md) (participant) |

---

## Prerequisites

| Requirement | Version | Notes |
|---|---|---|
| AWS Account | — | With SageMaker, S3, DynamoDB, Cognito, CloudFront access |
| AWS CLI | v2.x | Configured (`aws sts get-caller-identity`) |
| Node.js | 18+ | CDK CLI + frontend builds |
| Python | 3.12+ | CDK infrastructure code |
| AWS CDK | 2.x | `npm install -g aws-cdk` |
| jq | — | JSON parsing in deploy scripts |
| Hugging Face token | — | **Admin-only** — pre-caches gated models (M2/M4/M5/M6) and runs the M7 reference eval. **Participants need NO HF token.** See [PREREQUISITES.md](PREREQUISITES.md). |
| NGC API key | — | **Admin-only, M7 only** — the AlpaSim NuRec renderer image. |

### Service quotas (request early — 24–48 h lead time)

GPU **Studio JupyterLab App** quotas default to low or **0** on fresh accounts —
request increases before the workshop. There are also separate **job** quotas for
M9/M11 that are easy to miss. Full table + CLI commands: **[ADMIN_GUIDE.md](ADMIN_GUIDE.md)** and **[PREREQUISITES.md](PREREQUISITES.md)**.

Check current values:
```bash
aws service-quotas list-service-quotas \
  --service-code sagemaker --region "${AWS_REGION:-us-west-2}" \
  --query 'Quotas[?contains(QuotaName, `Studio JupyterLab Apps`) || contains(QuotaName, `for training job`) || contains(QuotaName, `for processing job`)].{Name:QuotaName,Value:Value,Code:QuotaCode}' \
  --output table
```

---

## Quick Start

All commands derive your account and region from the environment — nothing is
hardcoded.

```bash
# 1. Clone
git clone <repository-url> av3.0-blueprint-lab
cd av3.0-blueprint-lab

# 2. Required environment variables
export ADMIN_EMAIL="<admin-email>"           # e.g. you@example.com
export AWS_REGION="us-west-2"                 # default; see "Region selection"
export HF_TOKEN="hf_..."                      # admin Hugging Face read token
# Optional but recommended: restrict admin-dashboard access to your IP/CIDR
export ADMIN_IP_ALLOWLIST="203.0.113.0/24"    # default 0.0.0.0/0 = WAF open

# 2b. Accept gated model/dataset licenses on Hugging Face (before Step 6).
#     Log in to huggingface.co and click "Agree and access repository" on each
#     gated repo — full list in PREREQUISITES.md.

# 3. Bootstrap CDK (one-time per account + region)
cd infra && python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt
npx cdk bootstrap "aws://$(aws sts get-caller-identity --query Account --output text)/$AWS_REGION"
cd ..

# 4. Deploy infrastructure + dashboards (~25 min)
./scripts/deploy.sh

# 5. Create the first Cognito admin user
#    (deploy.sh prints the exact command with your pool id; username MUST be an email)
aws cognito-idp admin-create-user \
    --user-pool-id <cognito-pool-id> \
    --username "$ADMIN_EMAIL" \
    --user-attributes Name=email,Value="$ADMIN_EMAIL" Name=email_verified,Value=true \
    --temporary-password 'TempPass1!' \
    --region "$AWS_REGION"

# 6. Pre-cache NVIDIA models to S3 (background, 30–60 min)
./scripts/cache_models.sh
#    M4/M5/M6 additionally need an offline HF cache, M6 a demo clip, and M7 a
#    one-time GPU-EC2 reference eval — see ADMIN_GUIDE.md §6 and the
#    per-module deep dives (COSMOS_M4_M5, ALPAMAYO_M6, ALPASIM_M7).

# 7. Stage the nuScenes-mini dataset to S3 (required by M1 / M3 / M10)
./scripts/stage_nuscenes.sh
#    Pulls from the public AWS Open Data mirror (no login; nuScenes terms apply).

# 8. Upload notebook templates + helper scripts to the shared bucket
ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
aws s3 sync notebooks/ "s3://av30lab-shared-data-$ACCOUNT/notebook-templates/" --region "$AWS_REGION"
aws s3 sync scripts/   "s3://av30lab-shared-data-$ACCOUNT/notebook-templates/scripts/" --region "$AWS_REGION"
```

Then open the **Admin Dashboard URL** printed by `deploy.sh`, log in with the
email + temporary password from Step 5, provision a test user, and open the
**Participant Dashboard Link** to verify the pipeline map. The full day-by-day
runbook — smoke test, bulk provisioning, monitoring, teardown — is in
**[ADMIN_GUIDE.md](ADMIN_GUIDE.md)**.

---

## Architecture

```
        CloudFront (2x)  ─────────  Admin Dashboard  |  User Dashboard
              │                              │
        S3 static (admin)               S3 static (user)
              │
        API Gateway + Lambda  ── create_user, delete_user, bulk_provision,
              │                    list_sessions, terminate_session,
              │                    change_instance, get_costs, update_progress, …
   ┌──────────┼───────────────────────────────┐
 Cognito   DynamoDB                    SageMaker Studio Domain
 (auth)    (sessions,                  └─ per-user profile + JupyterLab space
            progress)                        │
                                       S3 shared-data bucket
                                        (model-cache / datasets / hf-cache /
                                         notebook-templates / m7-reference)
```

- **Network:** VPC with private subnets, NAT Gateway, VPC endpoints for S3/SageMaker.
- **Storage:** KMS-encrypted S3 (shared data + per-user workspaces); pre-cached models.
- **Compute:** SageMaker Studio Domain with a lifecycle config for auto-setup.
- **Auth:** Cognito user pool with an optional **WAF IP allowlist** for the admin plane.
- **API:** Lambda-backed REST API for user management, sessions, and progress.
- **Monitoring:** CloudWatch alarms, SNS notifications, a daily budget alert.
- **Frontends:** React SPAs on CloudFront (admin dashboard + user pipeline map).

---

## Project structure

```
av3.0-blueprint-lab/
├── infra/                  # AWS CDK app (Python): stack, constructs, Lambdas
│   ├── app.py  cdk.json  requirements.txt
│   ├── stacks/av30_stack.py
│   ├── av30_constructs/    # network, storage, database, sagemaker, auth, api, dashboards, monitoring
│   └── lambda/             # create_user, delete_user, bulk_provision, change_instance, get_costs, update_progress, …
├── notebooks/              # 12 workshop notebooks M0–M11
├── web/
│   ├── admin/              # Admin dashboard (React + Vite)
│   └── user/               # Participant pipeline map (React + Vite)
├── scripts/                # deploy.sh, teardown.sh, cache_models.sh, stage_nuscenes.sh,
│                           # setup_*.sh, alpasim_ec2_setup.sh, grab_gpu_instance.py, …
├── docs/{en,ko,ja}/        # Full trilingual documentation set
├── LICENSE                 # MIT-0 (workshop code)
├── NOTICE                  # third-party model/dataset licenses (incl. non-commercial)
└── README.md               # repository landing page
```

---

## Cost & cleanup

| Scenario | Cost | Notes |
|---|---|---|
| Idle (infra only) | ~$80/mo | NAT Gateway, VPC endpoints, DynamoDB, CloudFront |
| GPU modules | per-hour | `ml.g5.xlarge` ~$1.41/hr (M10), `ml.g5.12xlarge` ~$6.68/hr (M2/M3), `ml.p4d.24xlarge` ~$37.69/hr (M4/M5/M6) |
| M7 AlpaSim on EC2 | ~$30 one-time (admin) | reference eval on `g6e.12xlarge`; optional participant self-run ~$10.5/hr/host |
| Full week (mixed) | ~$400–600+ | dominated by the p4d modules and user count |

**Cost controls:** daily budget alarm (SNS → `<admin-email>`), admin
force-terminate from the Sessions tab, and lifecycle auto-stop of idle apps
(~180 min). **Teardown:** `scripts/teardown.sh` (dry-run by default; `--yes`,
`--user <id>`, `--destroy`) removes per-user apps/spaces/profiles, sweeps orphaned
OpenSearch Serverless collections, and terminates tagged GPU EC2 hosts. After the
event, **revoke the admin HF token and rotate the NGC key**. Details in
[ADMIN_GUIDE.md](ADMIN_GUIDE.md).

---

## Region selection

Default: **us-west-2 (Oregon)** — deepest GPU capacity and `ml.p5.48xlarge`
availability. Change with `export AWS_REGION=...` before deploying.

| Region | p4d.24xlarge | p5.48xlarge | g5.12xlarge | Notes |
|---|---|---|---|---|
| us-west-2 (Oregon) | ✅ | ✅ | ✅ | **Default** |
| us-east-1 (Virginia) | ✅ | ✅ | ✅ | Alternative |
| ap-northeast-2 (Seoul) | ✅ | ❌ | ✅ | No p5 fallback |

S3 model-cache paths are region-local — re-run `cache_models.sh` after changing regions.

---

## License

The **workshop code** in this repository (CDK infra, Lambdas, notebooks,
dashboards, scripts) is licensed under **MIT-0** — see [LICENSE](../../LICENSE).

The **models and datasets** the notebooks download are **not** covered by that
license and are **not redistributed** here. Each keeps its own terms — notably
**Alpamayo-1.5-10B (M6/M7) is non-commercial (research/evaluation only)** and
**nuScenes** is non-commercial. Review and comply with every applicable license;
see [NOTICE](../../NOTICE) for the full list.
