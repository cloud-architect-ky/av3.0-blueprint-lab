# AV 3.0 Blueprint Lab — Participant Pre-Learning Guide

**Read this before the workshop.** It teaches the *concepts* behind the lab so the
hands-on modules make sense. It is **not** the click-by-click runbook — that's
[PARTICIPANT_GUIDE.md](PARTICIPANT_GUIDE.md), which you'll use on the day.

- ⏱️ **Core reading (do this): ~45–60 min.** Sections 1–4 + the module you'll start with.
- 📚 **Optional deeper dive: as much as you like.** Section 6 links papers, repos, and docs.
- You do **not** need to install anything or have an AWS/Hugging Face account to
  prepare — the core reading is conceptual. (The admin pre-caches everything.)

---

## 1. The big picture — what is "AV 3.0 / Physical AI"?

Autonomous-vehicle development has moved through three broad eras:

- **AV 1.0** — hand-written rules + classical robotics. Brittle in the long tail.
- **AV 2.0** — deep learning on large labeled datasets. Better, but data-hungry and
  still modular (separate perception → prediction → planning stacks).
- **AV 3.0** — **end-to-end, foundation-model-driven**. Large multimodal models
  (vision-language, world models, vision-language-**action** policies) trained on
  huge amounts of real *and synthetic* driving data, evaluated in simulation before
  the road. "**Physical AI**" is NVIDIA's umbrella term for AI that perceives and
  acts in the physical world (robots, AVs).

**The core problem this lab is about: data.** A modern AV model needs enormous,
*diverse*, *well-labeled* driving data — including rare/dangerous situations you
can't safely collect on real roads (a child running out, a whiteout, a wrong-way
driver). The AV 3.0 answer is a **data pipeline** that:
1. starts from real sensor data,
2. **captions and curates** it with AI (so it's searchable and high-quality),
3. **synthesizes** more data — new weather, new scenarios — with generative "world
   models,"
4. trains a driving **policy**, and
5. **evaluates it in closed-loop simulation** before anything touches a car.

This lab is a hands-on, end-to-end walk through exactly that pipeline, on AWS, using
NVIDIA's open models. **You will run the real pipeline** (not a toy) on a small
dataset.

**Start here:** the one blog post this entire lab implements —
[Building an end-to-end Physical AI data pipeline for AV 3.0 on AWS with NVIDIA](https://aws.amazon.com/blogs/industries/building-an-end-to-end-physical-ai-data-pipeline-for-autonomous-vehicle-3-0-on-aws-with-nvidia/).
Read it once now; everything below is a map of it.

---

<a id="the-8-stage-pipeline"></a>
## 2. The 8-stage pipeline (and how the modules map to it)

The blog defines an **8-stage** pipeline. This lab implements each stage as one or
more notebook modules (M1–M11), plus a few **supplementary** modules that extend it
(M5, M9, M11). Data flows module → module through **S3** (each module reads the
previous one's output folder and writes its own).

```
 real data          AI labeling            synthetic data          policy + eval
 ─────────          ───────────            ──────────────          ────────────
 nuScenes ─▶ M1 ─▶ M2 caption ─▶ M3 curate ─┬─▶ M4 weather aug
 (Stage 1-2 explore) (Stage 3)   (Stage 3)   ├─▶ M5 scenario gen (Stage 5)
                        │                     ├─▶ M6 VLA inference ─▶ M7 closed-loop eval
                        │                     └─▶ M9 distributed-training scale-up
                        └─▶ M8 semantic search (Stage 4)
 nuScenes CAM ─▶ M10 3D reconstruction (Stage 6)     M1 ─▶ M11 orchestration
```

| Stage (blog) | Module | Concept in one line |
|---|---|---|
| 1–2 Data collection & exploration | **M1** | Load and browse the raw driving dataset (nuScenes-mini). |
| 3 Captioning | **M2** | A vision-language model writes a text description of each clip. |
| 3 Curation | **M3** | Filter/dedup/quality-score the captions to build a clean training set. |
| 4 Search | **M8** | Turn clips into embeddings so you can *semantically* search them ("find left turns in rain"). |
| 5 Augmentation | **M4** | A "world model" restyles real clips into new **weather/lighting** without re-driving. |
| 5 (ext) Scenario generation | **M5** | A world model **generates new synthetic driving video** from a prompt/seed. |
| 6 Neural reconstruction | **M10** | Rebuild a 3D scene from camera images (NeRF / Gaussian Splatting). *(known-limited — see §5.)* |
| 7 VLA inference | **M6** | A Vision-Language-**Action** model predicts the driving trajectory + its reasoning. |
| 8 Closed-loop eval | **M7** | Put that policy in a **simulator** and score it (collisions, off-road, etc.). |
| — Training scale-up (ext) | **M9** | The *pattern* for distributed multi-node training (HyperPod). |
| — Orchestration (ext) | **M11** | Wire M1→M4 into one automated, repeatable **SageMaker Pipeline**. |

> **Mental model to hold onto:** *real data → label it → search & clean it →
> multiply it with synthetic generation → train a policy → prove it in sim.*

---

## 3. Key concepts to understand before you start

You don't need to master these — just recognize the words when a notebook uses them.

### 3.1 Foundation models & the NVIDIA Cosmos family
A **foundation model** is a large model pre-trained on broad data that you adapt to
many tasks. This lab uses NVIDIA's **Cosmos** family of *world foundation models* and
the **Alpamayo** driving policy:

| Model (used in) | Type | What it does here |
|---|---|---|
| **Cosmos Reason 1** (M2) | Vision-Language Model (VLM) | "Reasons" about a video clip and captions it. |
| **Cosmos Transfer 2.5** (M4) | World model (video→video) | Restyles a real clip into new weather/conditions. |
| **Cosmos Predict 2.5** (M5) | World model (generation) | Generates new synthetic driving video. |
| **Alpamayo 1.5** (M6, M7) | Vision-Language-**Action** (VLA) | Predicts an ego trajectory + chain-of-reasoning; the "driver." |
| **Cosmos Reason 2** (hidden, M6/M7) | VLM backbone | Alpamayo's internal vision backbone. |

- **VLM vs. VLA:** a VLM outputs *text/understanding*; a **VLA** additionally outputs
  an *action* (here: a future trajectory). VLA is the AV 3.0 "end-to-end driver."
- **World model:** a generative model that predicts/produces *future frames* of a
  scene — the engine behind synthetic data (M4/M5).
- **License note:** Alpamayo (M6/M7) is **non-commercial** (research/eval only). You
  don't download it; running M6/M7 acknowledges that license.

### 3.2 The dataset — nuScenes
[**nuScenes**](https://www.nuscenes.org/) is a widely used open AV dataset (Motional):
multi-camera + LiDAR + radar driving scenes with rich annotations. The lab uses
**nuScenes-mini** (a small subset) so everything runs cheaply. A **scene** is a
~20-second clip; **CAM_FRONT** is the front camera stream M4/M10 use.

### 3.3 Synthetic data & why it matters
Real data can't cover the long tail safely. **Augmentation** (M4: same scene, new
weather) and **scenario generation** (M5: brand-new synthetic clips) multiply
diversity without re-driving. This is the heart of AV 3.0's data strategy.

### 3.4 Embeddings & semantic search (M8)
An **embedding** turns a clip/caption into a vector so that *similar meaning →
nearby vectors*. Store them in a vector index (here **Amazon OpenSearch
Serverless**) and you can search by meaning ("night, pedestrians, crosswalk")
instead of filenames — **k-NN** finds the nearest vectors.

### 3.5 Closed-loop vs. open-loop evaluation (M6 → M7)
- **Open-loop (M6):** feed logged data to the policy, compare its predicted
  trajectory to what actually happened (metric: minADE — average trajectory error).
- **Closed-loop (M7):** put the policy *in a simulator* where its own actions change
  what it sees next — the realistic test. Metrics: collisions, off-road, distance to
  the ground-truth path. The simulator here is **AlpaSim**.

### 3.6 Distributed training (M9) & orchestration (M11) — the "production" concepts
- **Distributed training (M9):** real models are too big for one GPU, so training is
  split across many nodes that sync gradients (**DDP** / `torch.distributed`).
  **SageMaker HyperPod** is AWS's managed cluster for this at scale. *(In the lab M9
  demonstrates the multi-node pattern on small CPU instances — see §5.)*
- **Orchestration (M11):** instead of running notebooks by hand, define the steps as
  a **SageMaker Pipeline** — a repeatable, parameterized DAG (directed acyclic graph)
  where each step starts/stops its own compute and the lineage is tracked.

### 3.7 The AWS platform you'll touch
- **Amazon SageMaker Studio / JupyterLab** — your notebook environment in the browser.
- **Instances & GPUs** — CPU (`ml.t3.medium`) for light work; GPU (`ml.g5.*`,
  `ml.p4d.*`) for the models. You pick the instance from the dashboard; the platform
  loads the matching GPU software image. **GPU time costs real money** — switch back
  to CPU between GPU modules.
- **S3** — where every module reads inputs and writes outputs (this is how data flows
  between modules, and why your results survive an instance change).

---

## 4. What you actually need to know how to do (skills check)

The lab is approachable if you're comfortable with:
- **Basic Python & Jupyter** — running cells top-to-bottom, reading output/errors.
  (You will *run* code, not write much.)
- **Reading a notebook** — following markdown explanations between code cells.
- **Very basic ML vocabulary** — model, inference, training, dataset, GPU.

You do **not** need: deep learning math, CUDA, AWS administration, or prior AV
experience. Anything AWS-specific (picking an instance, opening the workspace) is in
the operational [PARTICIPANT_GUIDE.md](PARTICIPANT_GUIDE.md).

**New to Jupyter?** Skim the 10-minute
[JupyterLab interface tour](https://jupyterlab.readthedocs.io/en/stable/user/interface.html) —
just enough to know "Run cell = Shift+Enter" and "Run ▸ Run All Cells".

---

## 5. Two things to know so you're not surprised on the day

- **M7 and M9 notebooks are CPU** even though they're about GPU-scale ideas. M7
  *visualizes* a closed-loop simulation the admin ran on a GPU host; M9 *submits* a
  real 2-node training job that runs on separate managed instances. This is by
  design — the notebook orchestrates; the heavy compute happens elsewhere.
- **M10 (3D reconstruction) is known-limited.** Its GPU check and data-prep cells
  run and illustrate the stage, but the final 3D-training cell does **not** run on
  the current workshop image (a CUDA build-tooling gap). Treat M10 as an
  optional/demo module; don't be alarmed if the last cell errors.

Suggested path on the day: **M0 (overview) → M1 → M2 → M3**, then branch to whatever
interests you (M4/M5 synthetic data, M6/M7 policy + sim, M8 search, M9/M11
production patterns).

---

## 6. Optional deeper dive (by interest)

Pick the rows that match what you want to understand more deeply. None of this is
required for the workshop.

### The pipeline & the platform
- 📄 **AWS + NVIDIA AV 3.0 blog** (the source of this whole lab) —
  [aws.amazon.com/blogs/industries/…av-3-0…](https://aws.amazon.com/blogs/industries/building-an-end-to-end-physical-ai-data-pipeline-for-autonomous-vehicle-3-0-on-aws-with-nvidia/)
- 📘 **Amazon SageMaker Studio** docs —
  [docs.aws.amazon.com/sagemaker/latest/dg/studio.html](https://docs.aws.amazon.com/sagemaker/latest/dg/studio.html)
- 📘 **SageMaker Pipelines** (M11) —
  [docs.aws.amazon.com/sagemaker/latest/dg/pipelines.html](https://docs.aws.amazon.com/sagemaker/latest/dg/pipelines.html)
- 📘 **SageMaker HyperPod** (M9) —
  [docs.aws.amazon.com/sagemaker/latest/dg/sagemaker-hyperpod.html](https://docs.aws.amazon.com/sagemaker/latest/dg/sagemaker-hyperpod.html)

### The models (NVIDIA Cosmos & Alpamayo)
- 🧩 **NVIDIA Cosmos** — models + the *Cosmos Cookbook* the lab draws from:
  [github.com/NVIDIA/Cosmos](https://github.com/NVIDIA/Cosmos)
- 🧩 **Cosmos Reason 1** (captioning, M2) —
  [huggingface.co/nvidia/Cosmos-Reason1-7B](https://huggingface.co/nvidia/Cosmos-Reason1-7B)
- 🧩 **Cosmos Transfer 2.5** (weather aug, M4) —
  [huggingface.co/nvidia/Cosmos-Transfer2.5-2B](https://huggingface.co/nvidia/Cosmos-Transfer2.5-2B)
- 🧩 **Cosmos Predict 2.5** (scenario gen, M5) —
  [huggingface.co/nvidia/Cosmos-Predict2.5-2B](https://huggingface.co/nvidia/Cosmos-Predict2.5-2B)
- 🧩 **Alpamayo 1.5** (VLA policy, M6/M7) —
  [huggingface.co/nvidia/Alpamayo-1.5-10B](https://huggingface.co/nvidia/Alpamayo-1.5-10B)
  (non-commercial)

### Data, simulation, reconstruction
- 🚗 **nuScenes** dataset — [nuscenes.org](https://www.nuscenes.org/)
- 🕹️ **AlpaSim** simulator (M7) — [github.com/NVlabs/alpasim](https://github.com/NVlabs/alpasim)
- 🧊 **Nerfstudio** (M10, 3D reconstruction) — [docs.nerf.studio](https://docs.nerf.studio/)
- 🔎 **Amazon OpenSearch Serverless** vector search (M8) —
  [docs.aws.amazon.com/opensearch-service/latest/developerguide/serverless.html](https://docs.aws.amazon.com/opensearch-service/latest/developerguide/serverless.html)

### Concepts, if the terms were new
- **Foundation / world models**, **VLM**, **VLA** — see the Cosmos and Alpamayo model
  cards above (each explains its task).
- **Distributed data-parallel training (DDP)** — PyTorch
  [Distributed Overview](https://docs.pytorch.org/tutorials/beginner/dist_overview.html).
- **Vector embeddings & k-NN search** — the OpenSearch vector-search guide above.

### The deepest dive: the module docs in this repo
Each hard module has an engineering write-up explaining exactly how it runs and why:
[COSMOS_M4_M5.md](COSMOS_M4_M5.md) · [ALPAMAYO_M6.md](ALPAMAYO_M6.md) ·
[ALPASIM_M7.md](ALPASIM_M7.md) · [HYPERPOD_M9.md](HYPERPOD_M9.md) ·
[PIPELINE_M11.md](PIPELINE_M11.md). Read these *after* you've run a module and want
the internals.

---

## 7. "Am I ready?" checklist

You're ready for the workshop if you can answer these from Sections 1–3:

- [ ] In one sentence, what is the AV 3.0 data pipeline *for*?
- [ ] Name the five phases: real data → ? → ? → ? → ?
- [ ] What's the difference between a **VLM** (M2) and a **VLA** (M6)?
- [ ] Why does the lab **generate synthetic data** (M4/M5) instead of just using real clips?
- [ ] What's the difference between **open-loop** (M6) and **closed-loop** (M7) evaluation?
- [ ] Why do modules pass data through **S3** rather than in memory?
- [ ] Which module is **known-limited**, and what should you expect? *(M10 — training cell doesn't run.)*

If a question is fuzzy, re-skim that concept in §3 (or the blog in §1). That's all
the preparation you need — see you in [PARTICIPANT_GUIDE.md](PARTICIPANT_GUIDE.md) on
the day.
