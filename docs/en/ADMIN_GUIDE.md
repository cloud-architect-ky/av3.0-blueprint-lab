# AV 3.0 Blueprint Lab — Admin Guide

Everything the workshop admin does **before, during, and after** the event, in the
order you'll do it. Participants only need their dashboard link (see
[PARTICIPANT_GUIDE.md](PARTICIPANT_GUIDE.md)); everything else is on you.

> **Golden rule:** all the heavy, gated, GPU, and credential work is the admin's.
> If you finish the pre-event checklist below, a participant can run M0–M11 from a
> browser with **no AWS account, no Hugging Face token, and no license clicks**
> (the one exception is the optional M7 self-run — see §7).

---

## 0. What you are operating

- **One CDK stack** (`Av30PlatformStack`) → VPC, KMS-encrypted S3 (shared + per-user
  workspace), DynamoDB, Cognito, WAF, API Gateway + Lambda, 2 CloudFront dashboards
  (admin + user), and a SageMaker Studio domain with a per-user execution role
  `av30lab-sagemaker-execution-role`.
- **Two S3 buckets** (names are derived from **your** account + region — the
  examples in this guide use account `<aws-account-id>` / `us-west-2`, the reference
  deployment; substitute your own — see §1.5):
  - `av30lab-shared-data-<account>` — models, datasets, notebook templates, M7 reference.
  - `av30lab-user-workspace-<account>` — one `users/<id>/` prefix per participant.

> **Note on the IDs in this guide.** Everywhere you see `<aws-account-id>` or
> `us-west-2` (bucket names, ARNs, quota "current" values, CLI examples), those
> are from the reference deployment. They are **not** hard-coded in the stack —
> the account is taken from your credentials and the region from `$AWS_REGION`
> at deploy time (§5). Pick yours in §1.5, then read the examples with your own
> values substituted.
- **12 notebooks M0–M11**. Most are participant-self-service; a few need one-time
  admin pre-work (models, datasets, the M7 reference run). See the matrix in §4.

---

## 1. Pre-event timeline

| When | Task | Why the lead time |
|---|---|---|
| **Day −7** | Request GPU + job quota increases (§2) | Approvals take 24–48 h, sometimes longer |
| **Day −7** | Accept all gated HF licenses on your admin account (§3) | Instant, but easy to forget one |
| **Day −3** | `cdk bootstrap` + `deploy.sh` (§5) | ~25 min; leaves time to fix issues |
| **Day −3** | Stage nuScenes + pre-cache models + HF offline cache (§6) | 30–90 min of background transfers |
| **Day −2** | Run the M7 AlpaSim reference eval on EC2 (§6.4), if using M7 | ~$30, tens of min–2 h on a GPU box |
| **Day −1** | Upload notebook templates, smoke-test one user end-to-end (§8) | Catches provisioning/quota gaps |
| **Day 0** | Provision participants, hand out dashboard links (§9), monitor (§10) | — |
| **Day +0** | Delete users, **revoke HF token, rotate NGC key** (§12) | Security hygiene |

---

## 1.5. Choosing your AWS account and Region (do this first)

The platform is **account- and region-agnostic** — nothing in the stack pins the
reference account (`<aws-account-id>`) or region (`us-west-2`). Everything derives at
deploy time: the **account** from your AWS credentials, and the **region** from the
`AWS_REGION` you export in §5. Decide both before you request quotas (§2), because
GPU quotas and gated-model availability are per-account **and** per-region.

**Choosing the account**
- Use an account **you are an admin of** (or have IAM rights to create roles,
  Cognito pools, CloudFront, VPCs, and SageMaker domains). `deploy.sh` runs
  `cdk bootstrap`, which needs elevated permissions once per account+region.
- Prefer a **dedicated / sandbox** account: the stack creates a Studio domain,
  buckets, and a WAF, and teardown (`scripts/teardown.sh`) is cleanest when it
  isn't sharing the account with unrelated production resources.
- Whatever account your credentials point at when you run `deploy.sh` is where it
  lands. Confirm before deploying:
  ```bash
  aws sts get-caller-identity --query Account --output text
  ```
  This account id is what fills the `<account>` in every bucket name and ARN.

**Choosing the Region** — this matters more than the account, because it gates GPU
capacity and model access:
- **GPU availability varies by region.** The GPU families this lab uses (`g5`,
  `g6`, and optionally `p4d`/`p5`) are **not** in every region, and quota approvals
  are per-region. Pick a region with strong GPU capacity — `us-west-2` (Oregon)
  and `us-east-1` (N. Virginia) are the safest; **`ml.p5.48xlarge` in particular
  is only offered in a few regions (us-west-2 / us-east-1).**
- **Latency:** closer to the participants is nicer for the interactive Studio UI,
  but capacity should win the tie — a region where you can't get GPUs is useless.
- **Data residency / org policy:** if your organisation restricts regions, choose a
  compliant one that still has the GPU families above.
- **Model + dataset staging is region-local.** The HF/model caches and nuScenes are
  staged into the shared bucket **in your chosen region** (§6); if you later move
  regions you must re-stage (see the "Region portability" note in `README.md`).

**Verify a candidate region has the capacity you need** before committing (empty
output for a family means it isn't offered there):
```bash
export AWS_REGION="us-west-2"     # your candidate
# GPU instance types offered for SageMaker Studio apps in this region:
aws service-quotas list-service-quotas --service-code sagemaker --region "$AWS_REGION" \
  --query "Quotas[?contains(QuotaName,'Studio JupyterLab Apps running on ml.g6') || contains(QuotaName,'Studio JupyterLab Apps running on ml.g5')].{Name:QuotaName,Current:Value,Code:QuotaCode}" \
  --output table
```

Once account + region are settled, export `AWS_REGION` (§5 uses it throughout),
request the quotas in §2 **in that region**, and stage caches (§6) **in that
region**. Changing either later means re-bootstrapping, re-quota-ing, and
re-staging — so lock it in now.

---

## 2. Service quotas (request Day −7)

Two families of quota matter. The README's quota table covers the first; the
**job quotas** below are easy to miss and block M9/M11 for a full room.

### 2a. Studio JupyterLab App quotas (interactive notebooks)
Search "**Studio JupyterLab Apps running on**" in the Service Quotas console. These
are the instance types the **user dashboard's Instance Options** actually offers
(recommended + alternatives), so a participant can only pick from this set — the
quotas below cover every one of them. Quota **codes are region-independent**; the
"Current" column is what account `<aws-account-id>` had in `us-west-2` (yours may
differ — always verify with the command below).

**GPU verified this cycle:** every GPU module ran successfully on the g6 family —
in particular **ml.g6.24xlarge (4× L4, 96 GB)** completed M2/M3 (captioning,
curation) and M4/M5/M6 (Cosmos Transfer/Predict, Alpamayo). g6 is the current-gen
L4 family and is usually far easier to get capacity for than p4d/p5, so it is the
recommended workhorse for a real room; p4d/p5 remain the "native-resolution / full
720p" path if you have the quota.

| Instance | Quota code | Current | Min for a 10-person room | Role in the dashboard |
|---|---|---|---|---|
| ml.t3.medium | L-71FAF417 | 2500 | ≥20 | **Recommended** for all CPU notebooks (M0, M1, M7, M8, M9, M11) |
| ml.t3.large | L-2733D4D5 | 30 | ≥0 | CPU alternative |
| ml.t3.xlarge | L-61F9C762 | 30 | ≥0 | CPU alternative (M1) |
| ml.m5.large | L-3BDCD216 | 11 | ≥0 | CPU alternative |
| ml.m5.xlarge | L-77B8159A | 11 | ≥0 | CPU alternative (M9) |
| ml.g5.xlarge | L-988CE6C5 | 5 | ≥5 | **Recommended** for M10 (Nerfstudio) |
| ml.g5.2xlarge | L-F73C7DB9 | 5 | ≥0 | M10 alternative |
| ml.g5.4xlarge | L-81940D85 | 5 | ≥0 | M10 alternative |
| ml.g5.12xlarge | L-8D2ED7BF | 5 | ≥5 | **Recommended** for M2, M3 (4× A10G, 96 GB) |
| ml.g5.24xlarge | L-F087CCFC | 2 | ≥1 | M2–M6 alternative |
| ml.g5.48xlarge | L-83AB5D73 | 2 | ≥1 | M2–M6 alternative / OOM fallback |
| ml.g6.xlarge | L-AABA5942 | 5 | ≥0 | M10 alternative (L4) |
| ml.g6.2xlarge | L-92D1521D | 5 | ≥0 | M10 alternative (L4) |
| ml.g6.4xlarge | L-692B8304 | 5 | ≥0 | M10 alternative (L4) |
| ml.g6.12xlarge | L-962247BA | 2 | ≥2 | M2/M3 capacity fallback (4× L4, 96 GB) |
| **ml.g6.24xlarge** | **L-8ACE1754** | **2** | **≥2** | **M2–M6 workhorse (4× L4, 96 GB) — verified this cycle** |
| ml.g6.48xlarge | L-125B7142 | 2 | ≥0 | M4/M5/M6 alternative (8× L4) |
| ml.p4d.24xlarge | L-AD63F1D2 | 2 | ≥2 | M4, M5, M6 native-res path (8× A100; **defaults to 0 — must request**) |
| ml.p5.48xlarge | L-B41FBF28 | 1 | ≥1 | Heavy-model fallback (8× H100; us-west-2 / us-east-1 only) |

Sizing the room: request the **recommended** instance for each module at ≥ the
number of concurrent participants, and at least the minimum shown for the one or
two fallbacks you intend to steer people to (capacity errors surface an
alternative in the dashboard). You do **not** need quota for every alternative —
only the ones you'll actually direct the room to use. If you standardise the GPU
modules on **g6.24xlarge** (recommended), request that one to ≥ your headcount and
you can leave p4d/p5 at their defaults.

### 2b. SageMaker **job** quotas (M9 and M11 — the ones people forget)
M9 submits a real **training job** and M11 runs real **processing jobs** on
separate managed instances (not the notebook's instance). These have their own
quotas:

| Quota | Code | Verified value (reference deploy example: us-west-2) | Needed by |
|---|---|---|---|
| ml.m5.xlarge for **training** job usage | L-CCE2AFA6 | 30 | M9 (needs ≥2 — it's a 2-node job) |
| ml.m5.xlarge for **processing** job usage | L-0307F515 | 16 | M11 (needs ≥1 — sequential 3-step DAG) |

Both are comfortably above the workshop's needs today, but **verify** — if either
is 0 in your account, M9/M11 fail at job submission even though the notebook opens.
Note `ml.g5.*` **processing** job quota is 0 here; that's fine because M11 runs on
CPU by design.

```bash
# Check everything at once:
aws service-quotas list-service-quotas --service-code sagemaker --region "$AWS_REGION" \
  --query "Quotas[?contains(QuotaName,'Studio JupyterLab Apps') || contains(QuotaName,'for training job') || contains(QuotaName,'for processing job')].{Name:QuotaName,Value:Value,Code:QuotaCode}" \
  --output table

# Request an increase (example: g6.24xlarge apps to 10 for a full room):
aws service-quotas request-service-quota-increase \
  --service-code sagemaker --quota-code L-8ACE1754 --desired-value 10 --region "$AWS_REGION"
```

> The quota **codes** above are the same in every region; run these against
> **your** `$AWS_REGION` (§5) so you're requesting capacity where you'll actually
> deploy. GPU availability varies by region — see §1.5 for choosing one.

---

## 3. Gated Hugging Face + NGC licenses (accept Day −7)

On **your admin HF account**, click "Agree and access repository" on each. This is
the only place licenses are accepted — participants never see this.

| Repo | Needed by | License |
|---|---|---|
| nvidia/Cosmos-Reason1-7B | M2 | NVIDIA Open Model (not gated, but log in) |
| nvidia/Cosmos-Guardrail1 | M4, M5 | NVIDIA Open Model |
| nvidia/Cosmos-Transfer2.5-2B | M4 | NVIDIA Open Model |
| nvidia/Cosmos-Predict2.5-2B | M5 | NVIDIA Open Model |
| nvidia/Alpamayo-1.5-10B | M6, M7 | **Non-commercial** (research/eval only) |
| nvidia/Cosmos-Reason2-8B | M6, M7 (hidden Alpamayo backbone) | NVIDIA Open Model |
| nvidia/PhysicalAI-Autonomous-Vehicles | M6 (demo clip) | NVIDIA AV Dataset (12-month expiry) |
| nvidia/PhysicalAI-Autonomous-Vehicles-NuRec | M7 (AlpaSim scenes) | NVIDIA AV NuRec Dataset |

**M7 also needs NGC** (separate from HF): the NuRec renderer image
`nvcr.io/nvidia/nre/nre-ga:26.04`. Get a key at
`https://org.ngc.nvidia.com/setup/api-key`. (In testing this image was
anonymously pullable, but have a key ready in case that changes.)

> Set `export HF_TOKEN=hf_...` once you've accepted everything; you'll use it in §6.

---

## 4. Per-module admin pre-work matrix

This is the heart of the guide — **which modules need admin work vs. run themselves.**

| Module | Compute (what participant sees) | Admin pre-work required | Doc |
|---|---|---|---|
| M0 Overview | CPU t3.medium | none | — |
| M1 Data Exploration | CPU t3.medium | Stage nuScenes-mini (§6.1) | — |
| M2 Cosmos Reason | GPU g5.12xlarge (or g6.24xlarge) | Pre-cache model to `model-cache/` (§6.2) | — |
| M3 Cosmos Curator | GPU g5.12xlarge (or g6.24xlarge) | (uses M2 output; no extra cache) | — |
| M4 Cosmos Transfer | GPU g6.24xlarge (or p4d.24xlarge for 720p) | HF **offline cache** to `hf-cache/hub/` (§6.3) | [COSMOS_M4_M5.md](COSMOS_M4_M5.md) |
| M5 Cosmos Predict | GPU g6.24xlarge (or p4d.24xlarge for native) | HF offline cache (§6.3) | [COSMOS_M4_M5.md](COSMOS_M4_M5.md) |
| M6 Alpamayo VLA | GPU g6.24xlarge (or p4d.24xlarge) | HF offline cache **+ demo clip** (§6.3) | [ALPAMAYO_M6.md](ALPAMAYO_M6.md) |
| M7 AlpaSim | CPU t3.medium (visualizer) | **Run reference eval on EC2 once** (§6.4) | [ALPASIM_M7.md](ALPASIM_M7.md) |
| M8 OpenSearch | CPU t3.medium | (uses M2 output; no extra cache) | — |
| M9 HyperPod | CPU t3.medium (submits real DDP job) | none (job quota §2b) | [HYPERPOD_M9.md](HYPERPOD_M9.md) |
| M10 Nerfstudio | GPU g5.xlarge (or g6.xlarge) | gsplat CUDA build runs per-session via `scripts/setup_gsplat_env.sh` (§11) | See §11 below |
| M11 Pipeline | CPU t3.medium (runs real SageMaker Pipeline) | none (job quota §2b) | [PIPELINE_M11.md](PIPELINE_M11.md) |

**Bottom line:** the required one-time admin caches are **nuScenes (M1) + model-cache
(M2) + hf-cache (M4/M5/M6) + M6 demo clip**, plus the **M7 reference run** if you're
running M7. M9 and M11 need **no cache** — just the job quotas in §2b.

---

## 5. Deploy the platform (Day −3)

```bash
# Required env
export ADMIN_EMAIL="you@example.com"       # becomes the Cognito admin + SNS alert target
export AWS_REGION="us-west-2"              # YOUR chosen region (§1.5); account comes from your creds
export HF_TOKEN="hf_..."                    # for the caching steps in §6
# Optional: lock the admin dashboard to your IP
export ADMIN_IP_ALLOWLIST="203.0.113.0/24" # default 0.0.0.0/0

# One-time CDK bootstrap (per account+region)
cd infra && source .venv/bin/activate && pip install -r requirements.txt
npx cdk bootstrap aws://$(aws sts get-caller-identity --query Account --output text)/$AWS_REGION
cd ..

# Deploy stack + build/upload both dashboards (~25 min)
./scripts/deploy.sh
```

`deploy.sh` passes `ADMIN_EMAIL` and `ADMIN_IP_ALLOWLIST` to CDK via `--context`
(**not** env vars — if you skip `deploy.sh` and run `cdk deploy` by hand, you must
pass `--context admin_email=...` or the SNS budget alert reverts to a placeholder).
It prints the **Admin Dashboard URL** and **API endpoint** at the end.

**Create the admin login** (username must be the email — Cognito uses email as the
sign-in alias):
```bash
aws cognito-idp admin-create-user \
  --user-pool-id <POOL_ID_FROM_DEPLOY_OUTPUT> \
  --username "$ADMIN_EMAIL" \
  --user-attributes Name=email,Value=$ADMIN_EMAIL Name=email_verified,Value=true \
  --temporary-password 'TempPass1!' --region $AWS_REGION
```
Log in to the admin dashboard; you'll be forced to set a new password.

---

## 6. One-time data + model staging (Day −3 to −2)

All of these write to the **shared** bucket. Steps 6.3/6.4 must run on a machine
that can reach the gated repos with your token.

### 6.1 nuScenes-mini (M1/M2/M10)
```bash
./scripts/stage_nuscenes.sh    # pulls the public AWS Open Data mirror → datasets/nuscenes-mini/
```

### 6.2 Simple model cache (M2/M3)
```bash
pip install huggingface_hub && hf auth login --token "$HF_TOKEN"
./scripts/cache_models.sh      # → s3://<shared>/model-cache/ (Cosmos-Reason1-7B, Transfer2.5, Predict2.5)
```

### 6.3 HF offline cache (M4/M5/M6) — the "no participant token" trick
M4/M5/M6 load gated checkpoints through HF's **own cache layout** at runtime
(M6 also pulls a hidden Cosmos-Reason2-8B backbone). The robust way to populate it:
**run M4, M5, and M6 once each on a GPU JupyterLab app** with your admin token,
then sync the cache tree:
```bash
aws s3 sync /mnt/sagemaker-nvme/hf/hub s3://<shared>/hf-cache/hub/ --only-show-errors
```
`setup_cosmos_env.sh` restores this into `HF_HOME` and sets `HF_HUB_OFFLINE=1`, so
participants run offline with no token. **M6 also needs a demo clip** (its dataset
can't be read offline):
```bash
source /mnt/sagemaker-nvme/cosmos-work/alpamayo_env.sh
unset HF_HUB_OFFLINE TRANSFORMERS_OFFLINE   # this save must be online
python scripts/alpamayo_save_clip.py --clip 030c760c-ae38-49aa-9ad8-f5650a545d26 \
  --t0-us 5100000 --out /mnt/sagemaker-nvme/m6_work/clips
aws s3 cp /mnt/sagemaker-nvme/m6_work/clips/030c760c-*.pt s3://<shared>/hf-cache/alpamayo-demo/
```
Full sequence: [COSMOS_M4_M5.md](COSMOS_M4_M5.md), [ALPAMAYO_M6.md](ALPAMAYO_M6.md).

### 6.4 M7 AlpaSim reference eval (only if running M7)
AlpaSim is a Docker-Compose microservice system needing a ≥40 GB GPU — it
**cannot run in a Studio notebook**. Run it once on a Docker-capable GPU EC2 host:
```bash
# On a Deep Learning Base GPU AMI box (g6e.12xlarge, public subnet):
ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
export HF_TOKEN=hf_... NGC_API_KEY=nvapi-... \
  SHARED_BUCKET=av30lab-shared-data-$ACCOUNT
bash scripts/alpasim_ec2_setup.sh    # → uploads s3://<shared>/m7-reference/
# then TERMINATE the instance.
```
The M7 notebook (CPU) downloads and visualizes these results for every participant.
~$30 one-time; participant cost $0. Full details + the optional participant
self-run path: [ALPASIM_M7.md](ALPASIM_M7.md), [M7_MANUAL_TEST_RUNBOOK.md](M7_MANUAL_TEST_RUNBOOK.md).

### 6.5 Upload notebook templates + scripts (do this LAST, after any notebook edits)
```bash
# <shared> = av30lab-shared-data-<account>. $AWS_REGION is the value exported in §5 (or: export AWS_REGION=...)
aws s3 sync notebooks/ s3://<shared>/notebook-templates/ --region "$AWS_REGION"
aws s3 sync scripts/   s3://<shared>/notebook-templates/scripts/ --region "$AWS_REGION"
```
These are copied into each user's workspace at provisioning time (and the notebooks
fall back to downloading scripts from this path). **Re-run this whenever you change
a notebook or script** — otherwise participants get the old version. Participants
already provisioned can re-sync from a JupyterLab terminal:
`aws s3 cp s3://<shared>/notebook-templates/<NB>.ipynb ~/`.

> **Note on `scripts/patch_notebooks.py`:** a manual, in-place `.ipynb` transformer
> from an earlier bootstrap. It is **NOT wired into any automation** (deploy, CDK,
> or provisioning) — the repo `notebooks/*.ipynb` are the single source of truth.
> Every module entry is now `[]` (a no-op); the tool **hard-fails** if a notebook
> ever drifts from its expected patterns, so it can never silently ship an
> unpatched notebook. You normally never run it — edit the notebook directly and
> re-sync via §6.5. The cross-module S3 contract those notebooks rely on is in
> [DATA_CONTRACT.md](DATA_CONTRACT.md).

---

## 7. Optional: M7 participant self-run (advanced)

By default every participant shares your one M7 reference eval (§6.4) and needs no
token. If you instead want **each participant to run AlpaSim themselves** on their
own admin-provisioned GPU host over SSM:
- You pre-provision a GPU EC2 host per participant and grant least-privilege SSM
  access (exact-ARN or ABAC). **Participants cannot terminate hosts — you do**
  (cost-runaway guard).
- Each participant needs **their own HF token** (the NuRec dataset is gated and not
  in the shared cache).
- Cost ~$10.5/hr/host, ≤16 concurrent by the G-vCPU quota.

Full runbooks: [M7_MANUAL_TEST_RUNBOOK.md](M7_MANUAL_TEST_RUNBOOK.md) Part C (admin
provisioning + IAM) and [M7_PARTICIPANT_SSM_RUNBOOK.md](M7_PARTICIPANT_SSM_RUNBOOK.md)
(participant steps). This is opt-in; skip it for a standard workshop.

---

## 8. Smoke test (Day −1) — prove one user works end-to-end

1. Admin Dashboard → **Add User** → test name + email → **Provision**.
2. Copy the **Participant Dashboard Link** from the success dialog (the durable
   `?userId=&token=` link — **not** the 5-minute "Direct workspace URL").
3. Open that link in a fresh browser → the Pipeline Map with 11 module nodes renders.
4. Click **M2** → **Instance Options** → recommended `ml.g5.12xlarge` preselected →
   **Apply & Restart** → **Open Workspace** → JupyterLab opens.
5. Run **M1** (CPU) end-to-end, then **M2** (GPU) — confirms the GPU image is
   auto-selected and the model cache resolves.
6. If you're running M9/M11, run one of each once as the test user to confirm the
   job quotas (§2b) and IAM are in place — they submit real managed jobs.
7. **Delete** the test user (Users tab → Delete) — removes app/space/profile + S3.

---

## 9. Provision participants (Day 0)

**Single user:** Admin Dashboard → **Add User** → name + email → **Provision**.
Hand them the **Participant Dashboard Link** (durable, non-expiring). The Users
table has a **Dashboard Link** column with a copy button per user.

**Bulk (CSV):** Admin Dashboard → bulk upload. The CSV needs a header row with
`name` and `email` columns (case-insensitive). Provisioning runs in parallel;
retry any failures individually.

Each participant gets: a SageMaker user profile + space, a `users/<id>/` S3 prefix
seeded with the notebook templates, and a personal dashboard link.

**Send participants two things:**
- **Before the event** — [PRE_LEARNING_GUIDE.md](PRE_LEARNING_GUIDE.md) (concepts +
  optional deeper-dive reading, ~45–60 min) so they arrive with context.
- **On the day** — their dashboard link + [PARTICIPANT_GUIDE.md](PARTICIPANT_GUIDE.md)
  (the click-by-click runbook).

---

## 10. During the workshop — monitor & control

- **Sessions tab** — live view of who's running what, on which instance, and cost.
- **Capacity errors** (`EC2InsufficientCapacityError`): tell participants to pick
  the alternative in Instance Options (`ml.g6.12xlarge` for M2/M3). It's a capacity
  shortage, not a quota problem.
- **Cost control** — a daily budget alarm emails `ADMIN_EMAIL` via SNS; the
  lifecycle config auto-stops idle apps after ~3 h; you can **force-terminate** any
  session from the Sessions tab. Watch for idle p4d boxes (~$37.69/hr).
- **GPU image reminder** — if a participant reports "No GPU detected" on a GPU
  instance, they launched the CPU image; Instance Options → GPU instance → Apply
  re-selects the GPU image.

---

## 11. M10 Nerfstudio — gsplat build (per-session)

**M10 now trains** — the `splatfacto` cell works after a one-time gsplat CUDA
build. `gsplat` ships a pure-Python wheel and compiles its CUDA kernels from
source on first use, but the SageMaker Distribution image's conda CUDA dev
packages are incomplete. **`scripts/setup_gsplat_env.sh`** (M10 cell 3 invokes it)
fixes the whole chain: installs the missing dev headers, symlinks `nvvm` so `nvcc`
finds `cicc`, mirrors the CUDA headers/libs into the standard `$CUDA_HOME` paths
(so the build works with zero env vars, even inside `ns-train`'s subprocess), and
source-builds `gsplat==1.4.0`.

- It is **ephemeral** — the SMD app resets `/opt/conda` on restart, so the setup
  cell re-runs each session (~3–5 min cold, seconds when already built).
- The demo uses **synthetic sin-wave camera poses**, so training runs end-to-end
  (a genuine Gaussian-Splatting pipeline) but the reconstruction is a smoke test,
  not a metrically correct scene. Wiring real nuScenes calibration is the next step.
- **M10 caveat:** the gsplat CUDA build runs per-session via
  `scripts/setup_gsplat_env.sh`; treat M10 as an optional/demo module and expect the
  final training cell to be sensitive to the GPU image's CUDA toolchain.

---

## 12. Teardown & post-event security

- **One-shot teardown:** **`scripts/teardown.sh`** reclaims everything with the
  admin AWS creds. Dry-run by default (enumerates, changes nothing); `--yes` to
  act, `--user <id>` to scope to a single user, `--destroy` to also `cdk destroy`.
  Per user it deletes app→space→profile→AOSS→S3→DDB (same order as the delete_user
  Lambda), then runs a **global `av30-semantic-*` AOSS sweep** to catch any
  orphaned OpenSearch Serverless collection (these bill continuously — the sweep is
  the safety net), and terminates `Participant`+`av30-alpasim-*`-tagged GPU EC2
  hosts. It prints a manual HF/NGC key-revocation checklist at the end.
- **Delete a single user interactively:** Admin Dashboard → Users → **Delete**
  (same dependency order in one action).
- **Tear down the stack** (if the platform is temporary): `scripts/teardown.sh
  --yes --destroy`, or `cd infra && npx cdk destroy`. Note the shared-data bucket
  is RETAIN — it and its cached models survive a destroy and must be emptied by hand.
- **Revoke the admin HF token** `hf_...` — the S3 caches are all participants ever
  touch, so the token isn't needed after staging.
- **Rotate the NGC API key** if you used M7.
- The idle stack still costs ~$80/mo (NAT, VPC endpoints, DynamoDB, CloudFront) —
  destroy it if you're done.

---

## 13. Admin troubleshooting quick table

| Symptom | Cause / Fix |
|---|---|
| `ResourceLimitExceeded: ...Studio JupyterLab Apps... is 0` | GPU app quota not raised — §2a. |
| M9 job fails at submission / M11 processing step never starts | m5.xlarge **job** quota (§2b) or exec-role IAM — both verified present in this account; re-check if you redeployed. |
| Participant "No GPU detected" on a GPU instance | CPU image selected — re-Apply via Instance Options. |
| M4/M5/M6 ask for an HF token | `hf-cache/hub/` not staged (§6.3) — participants fall back to online download. |
| M6 fails to load its clip | demo `.pt` not uploaded to `hf-cache/alpamayo-demo/` (§6.3). |
| M7 notebook shows nothing | `m7-reference/` reference eval not run (§6.4). |
| M10 training cell fails on gsplat | Re-run M10 cell 3 (`scripts/setup_gsplat_env.sh`) — the CUDA build is per-session and resets on app restart. §11. |
| SNS budget alert went to placeholder@example.com | Deployed without `--context admin_email` — redeploy via `deploy.sh`. |
| Participant link shows "Demo Mode" | They opened the bare URL; resend the full `?userId=&token=` link. |
| Bulk provision partial failure | Retry failed rows individually; check `bulk_provision` CloudWatch logs. |

---

## Related docs
- [PRE_LEARNING_GUIDE.md](PRE_LEARNING_GUIDE.md) — send to participants before the event.
- [PARTICIPANT_GUIDE.md](PARTICIPANT_GUIDE.md) — hand this to participants on the day.
- [PREREQUISITES.md](PREREQUISITES.md) — the token/license detail behind §3/§6.
- Module deep-dives: [COSMOS_M4_M5.md](COSMOS_M4_M5.md), [ALPAMAYO_M6.md](ALPAMAYO_M6.md),
  [ALPASIM_M7.md](ALPASIM_M7.md), [HYPERPOD_M9.md](HYPERPOD_M9.md),
  [PIPELINE_M11.md](PIPELINE_M11.md).
- [README.md](../../README.md) — full deployment + architecture reference.
