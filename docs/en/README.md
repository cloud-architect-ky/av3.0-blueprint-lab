<!-- Language: **English** · [한국어](../ko/README.md) · [日本語](../ja/README.md) -->

# AV 3.0 Blueprint Lab — Documentation (English)

**Language:** **English** · [한국어](../ko/README.md) · [日本語](../ja/README.md)

This directory holds the full English documentation set for the AV 3.0 Blueprint
Lab. For a project overview and the fastest install path, start at the
[repository README](../../README.md).

## The 12 modules

The lab is a hands-on NVIDIA + AWS **Physical AI data pipeline** delivered as 12
SageMaker Studio notebooks (M0–M11):

| Module | What it does | Instance |
|---|---|---|
| **M0** | Pipeline overview — maps the end-to-end pipeline to the modules (no compute) | CPU `t3.medium` |
| **M1** | Data Exploration — ingest & explore real **nuScenes-mini** sensor data; select scenes | CPU `t3.medium` |
| **M2** | Cosmos Reason Captioning — VLM captions of sampled clips | GPU `g5.12xlarge` |
| **M3** | Cosmos Curator — **NeMo Curator** video curation (split, transcode, filter, dedup) | GPU `g5.12xlarge` |
| **M4** | Cosmos Transfer — weather/condition augmentation of real clips | GPU (`g6.24xlarge` verified) |
| **M5** | Cosmos Predict — synthetic scenario (video2world) generation | GPU |
| **M6** | Alpamayo VLA — **Alpamayo-1.5-10B** vision-language-action inference + trajectory | GPU |
| **M7** | AlpaSim Closed-Loop Eval — visualize genuine closed-loop policy evaluation | CPU `t3.medium` (+ GPU EC2) |
| **M8** | OpenSearch Semantic Search — k-NN retrieval over caption embeddings | CPU `t3.medium` |
| **M9** | HyperPod Distributed Training — a real 2-node `torch.distributed` DDP job | CPU `t3.medium` (+ job nodes) |
| **M10** | Nerfstudio 3D Reconstruction — NeRF / 3D Gaussian Splatting (optional/demo) | GPU `g5.xlarge` |
| **M11** | Pipeline Automation — a real SageMaker Pipeline (Caption→Curate→Augment) | CPU `t3.medium` (+ processing job) |

Recommended path: **M0 → M1 → M2 → M3**, then branch to synthetic data (M4/M5),
policy + simulation (M6/M7), search (M8), or production patterns (M9/M11).

## Which docs to read, in order

**If you are the admin setting up the lab:**
1. [PREREQUISITES.md](PREREQUISITES.md) — accounts, tokens, quotas, gated licenses.
2. [ADMIN_GUIDE.md](ADMIN_GUIDE.md) — the day-by-day setup runbook (deploy, stage
   data/models, provision participants, monitor, tear down).
3. [DATA_CONTRACT.md](DATA_CONTRACT.md) — the cross-module S3 data contract (reference).

**If you are a participant:**
1. [PRE_LEARNING_GUIDE.md](PRE_LEARNING_GUIDE.md) — concepts to read before the event.
2. [PARTICIPANT_GUIDE.md](PARTICIPANT_GUIDE.md) — the day-of, click-by-click runbook.

**Per-module deep dives:**
- [COSMOS_M4_M5.md](COSMOS_M4_M5.md) — Cosmos Transfer (M4) & Predict (M5).
- [ALPAMAYO_M6.md](ALPAMAYO_M6.md) — Alpamayo VLA (M6).
- [ALPASIM_M7.md](ALPASIM_M7.md) — AlpaSim closed-loop evaluation (M7).
- [HYPERPOD_M9.md](HYPERPOD_M9.md) — distributed training (M9).
- [PIPELINE_M11.md](PIPELINE_M11.md) — SageMaker Pipelines (M11).

**M7 GPU / SSM runbooks (advanced):**
- [M7_MANUAL_TEST_RUNBOOK.md](M7_MANUAL_TEST_RUNBOOK.md) — admin: run the real
  AlpaSim reference eval on a GPU EC2 host.
- [M7_PARTICIPANT_SSM_RUNBOOK.md](M7_PARTICIPANT_SSM_RUNBOOK.md) — participant:
  optional self-run of real AlpaSim over SSM.
