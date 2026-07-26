# AV 3.0 Blueprint Lab — Prerequisites

## For participants: nothing to prepare for the notebooks 🎉

**For every notebook module you do NOT need a Hugging Face account, token, or any
model-license approval.** Every model the notebooks use (Cosmos Reason, Cosmos
Transfer, Cosmos Predict, Alpamayo) is **pre-cached to S3 by the workshop admin**,
and the notebooks load them **offline**. Just open your dashboard link and run the
modules — see [PARTICIPANT_GUIDE.md](PARTICIPANT_GUIDE.md).

> All you need is the **participant dashboard link** your admin sends you.

### One exception — the optional M7 self-run needs your own HF token 🔑
M7's *notebook* (visualizing results) needs no token like every other module. But
if you take the **optional advanced path** of running the real AlpaSim simulation
yourself on a GPU host over SSM (see
[M7_PARTICIPANT_SSM_RUNBOOK.md](M7_PARTICIPANT_SSM_RUNBOOK.md)), you **do** need
your own Hugging Face token, because AlpaSim downloads the gated
**`nvidia/PhysicalAI-Autonomous-Vehicles-NuRec`** scene at runtime (this dataset is
*not* in the shared offline cache, unlike the models). Before the M7 self-run:

1. Create a Hugging Face account and a token (`https://huggingface.co/settings/tokens`).
2. Accept the license on
   [`nvidia/PhysicalAI-Autonomous-Vehicles-NuRec`](https://huggingface.co/datasets/nvidia/PhysicalAI-Autonomous-Vehicles-NuRec)
   ("Agree and access repository") with that account.
3. Have the token ready to `export HF_TOKEN=hf_…` inside the SSM session.

If you only run the M7 notebook (the default), skip this — you need no token.

### License note (M6 / M7)
The Alpamayo-1.5-10B weights used by M6/M7 are under a **non-commercial** license
(research/evaluation only). You don't download them yourself, but by running
M6/M7 you acknowledge that license.

---

## For the workshop admin: pre-cache the models (do this once, before the event)

The notebooks never make participants authenticate to Hugging Face. Instead, the
admin downloads everything once (with an HF token + accepted licenses) and stages
it to S3. Two separate caches:

### A. Simple model cache — M2 (`model-cache/`)
`scripts/cache_models.sh` downloads each repo with `hf download --local-dir` and
`aws s3 sync`s it to `s3://<shared>/model-cache/<name>/`. The **M2** notebook
`aws s3 sync`s from there — a plain file tree. (M3 is a pure-Python curation step
and loads no model; it consumes M2's `captions.json` output.)

```bash
export HF_TOKEN=hf_...            # admin token, licenses accepted (see list below)
./scripts/cache_models.sh          # resolves the shared bucket from the stack
```

### B. HF offline cache — M4, M5, M6 (`hf-cache/hub/`)
M4/M5/M6 load gated checkpoints through Hugging Face's own cache layout at
runtime (M4/M5 via the Cosmos repos' `examples/inference.py`; M6 via
`Alpamayo1_5.from_pretrained`, which also pulls a hidden `Cosmos-Reason2-8B` VLM
backbone). To make that work **without a participant token**, the admin stages
the **HF cache tree** to `s3://<shared>/hf-cache/hub/`; `setup_cosmos_env.sh`
restores it into `HF_HOME` and sets `HF_HUB_OFFLINE=1`.

The most reliable way to populate this cache (guarantees every revision +
side-file each model needs is present) is to **run M4, M5 and M6 once on a GPU
instance with your admin HF token**, then sync the resulting cache:

```bash
# On a GPU JupyterLab app, after M4 + M5 + M6 have each run once successfully:
aws s3 sync /mnt/sagemaker-nvme/hf/hub \
  s3://<shared-bucket>/hf-cache/hub/ --only-show-errors
```

After that, participants need no token: `setup_cosmos_env.sh` sees the S3 cache,
restores it, and runs offline.

> **M6 also needs a demo clip.** M6's `PhysicalAI-Autonomous-Vehicles` dataset
> cannot be read offline, so the admin pre-saves a demo clip once
> (`scripts/alpamayo_save_clip.py`) and uploads it to
> `s3://<shared>/hf-cache/alpamayo-demo/` (under `hf-cache/` so it uploads from
> the GPU app terminal with the exec role's write scope). See
> [ALPAMAYO_M6.md](ALPAMAYO_M6.md) for the full one-time sequence.

### C. AlpaSim closed-loop reference eval — M7 (`m7-reference/`)
M7 evaluates the Alpamayo policy **closed-loop** with the real AlpaSim simulator,
which is a Docker-Compose microservice system that **cannot run in a Studio
notebook** (no Docker daemon) and needs a ≥40 GB GPU. So the admin runs it **once
on a GPU EC2 host** (`scripts/alpasim_ec2_setup.sh`) and uploads the genuine
results to `s3://<shared>/m7-reference/`; the M7 notebook (CPU) downloads and
visualizes them. Needs the admin HF token (NuRec dataset) **and an NGC API key**
(gated NuRec renderer image). One-time ~$30; participant cost $0. Full sequence,
instance choice, and GPU-placement details: [ALPASIM_M7.md](ALPASIM_M7.md).

### Admin: licenses to accept once (on the admin's HF account)
Accept **“Agree and access repository”** on each, then set `HF_TOKEN`:

| Repo | Used by | License |
|---|---|---|
| [nvidia/Cosmos-Reason1-7B](https://huggingface.co/nvidia/Cosmos-Reason1-7B) | M2, M4, M5 | NVIDIA Open Model |
| [nvidia/Cosmos-Guardrail1](https://huggingface.co/nvidia/Cosmos-Guardrail1) | M4, M5 | NVIDIA Open Model |
| [nvidia/Cosmos-Transfer2.5-2B](https://huggingface.co/nvidia/Cosmos-Transfer2.5-2B) | M4 | NVIDIA Open Model |
| [nvidia/Cosmos-Predict2.5-2B](https://huggingface.co/nvidia/Cosmos-Predict2.5-2B) | M5 | NVIDIA Open Model |
| [nvidia/Alpamayo-1.5-10B](https://huggingface.co/nvidia/Alpamayo-1.5-10B) | M6, M7 | **Non-commercial** |
| [nvidia/Cosmos-Reason2-8B](https://huggingface.co/nvidia/Cosmos-Reason2-8B) | M6, M7 (Alpamayo VLM backbone) | NVIDIA Open Model |
| [nvidia/PhysicalAI-Autonomous-Vehicles](https://huggingface.co/datasets/nvidia/PhysicalAI-Autonomous-Vehicles) | M6 (demo clip, dataset) | NVIDIA |
| [nvidia/PhysicalAI-Autonomous-Vehicles-NuRec](https://huggingface.co/datasets/nvidia/PhysicalAI-Autonomous-Vehicles-NuRec) | M7 (AlpaSim eval scenes) | NVIDIA AV NuRec Dataset License |

**M7 also needs NGC** (not HuggingFace): the AlpaSim NuRec renderer image
`nvcr.io/nvidia/nre/nre-ga:26.04` is pulled from NVIDIA NGC. Get an API key at
`https://org.ngc.nvidia.com/setup/api-key` and ensure access to that image. This
is admin-only (M7 runs on an EC2 host, see [ALPASIM_M7.md](ALPASIM_M7.md)).

> **Security:** the admin token is a secret — don't commit it, and revoke it
> after caching is done (the caches on S3 are all participants ever touch).

### Fallback (no S3 HF cache staged)
If `hf-cache/hub/` isn't in S3, M4/M5 fall back to **online** download and then a
participant *does* need an `HF_TOKEN` (paste it in the notebook's first cell) plus
accepted licenses. M6 additionally needs the demo `.pt` staged (its dataset can't
be read offline at all). Staging the cache + demo clip (§B) avoids all of this —
recommended.
