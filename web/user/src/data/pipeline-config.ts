export type ModuleStatus = "completed" | "in-progress" | "locked";

// Blog-aligned pipeline phases (columns in the map). The AWS+NVIDIA AV 3.0 blog
// groups its 8 stages; here we group the 11 lab modules into 5 balanced columns.
export type Phase = "ingest" | "curate" | "augment" | "train" | "validate";

export interface ModuleConfig {
  id: string;
  title: string;
  phase: Phase;
  tool: string;
  version: string;
  status: ModuleStatus;
  license: string;
  sourceUrl: string;
  // IMPORTANT: instance names MUST be SageMaker-prefixed ("ml.<family>.<size>")
  // and MUST exist in the backend INSTANCE_RATES table (infra/lambda/shared/
  // config.py). The change-instance Lambda rejects any type not in that table,
  // and the GPU-image auto-selection keys off the "ml.g*/ml.p*" prefix.
  recommendedInstance: string;
  alternatives: string[];
  storageGB: number;
  estimatedMinutes: number;
  awsAdvantage: string;
  inputPath: string;
  outputPath: string;
  feedsModules: string[];
  errorHints: Record<string, string>;
  // Optional: for a module whose heavy compute runs OUTSIDE the SageMaker
  // workspace (e.g. M7's AlpaSim on a GPU EC2 host reached over SSM). When set,
  // the detail panel renders a callout with the steps + a cost warning + a link
  // to the runbook. The SageMaker instance for such a module is CPU (this
  // notebook only visualizes the results the external host produced).
  externalExecution?: {
    label: string;
    summary: string;
    steps: string[];
    costWarning: string;
    guideHref: string;
  };
}

export const PHASE_COLORS: Record<Phase, string> = {
  ingest: "#0972d3",
  curate: "#7d56c2",
  augment: "#d97706",
  train: "#037f0c",
  validate: "#b91c1c",
};

export const STATUS_COLORS: Record<ModuleStatus, string> = {
  completed: "#037f0c",
  "in-progress": "#d97706",
  locked: "#5f6b7a",
};

// Real AV 3.0 Blueprint Lab pipeline (NVIDIA Cosmos + AWS). Instance types match
// the notebook headers (notebooks/M*.ipynb) and the backend rate table. GPU
// modules (ml.g5/ml.g6/ml.p4d) get the SageMaker Distribution GPU image
// automatically when selected — the participant only picks the instance.
export const PIPELINE_MODULES: ModuleConfig[] = [
  {
    id: "m01-data-exploration",
    title: "Data Exploration",
    phase: "ingest",
    tool: "nuScenes devkit + S3",
    version: "1.1",
    status: "completed",
    license: "CC BY-NC-SA 4.0",
    sourceUrl: "https://www.nuscenes.org/",
    recommendedInstance: "ml.t3.medium",
    alternatives: ["ml.t3.large", "ml.t3.xlarge", "ml.m5.large"],
    storageGB: 20,
    estimatedMinutes: 15,
    awsAdvantage:
      "nuScenes-mini is pre-staged in a shared S3 bucket, so exploration starts instantly with no download — CPU-only, a few cents per hour.",
    inputPath: "s3://av30lab-shared-data/datasets/nuscenes-mini/",
    outputPath: "s3://av30lab-user-workspace/users/{userId}/m1/",
    feedsModules: ["m02-cosmos-reason"],
    errorHints: {
      CalledProcessError:
        "Bucket/prefix mismatch. SHARED_BUCKET and USER_BUCKET env vars are injected by the notebook-sync lifecycle config — restart the app if they are missing.",
      EmptyManifest:
        "nuScenes sample_data has no `channel` field. Join calibrated_sensor → sensor to resolve CAM_FRONT keyframes.",
    },
  },
  {
    id: "m02-cosmos-reason",
    title: "Cosmos Reason Captioning",
    phase: "curate",
    tool: "NVIDIA Cosmos Reason 1 (7B VLM)",
    version: "1.0",
    status: "in-progress",
    license: "NVIDIA Open Model License",
    sourceUrl: "https://github.com/NVIDIA/Cosmos",
    // Stage 3 — Cosmos Reason 1 (Qwen2.5-VL) needs ~96 GB VRAM.
    recommendedInstance: "ml.g5.12xlarge",
    // ml.g6.12xlarge (L40S) is the capacity fallback when g5 is unavailable.
    alternatives: ["ml.g6.12xlarge", "ml.g6.24xlarge", "ml.g5.24xlarge", "ml.g5.48xlarge", "ml.p4d.24xlarge"],
    storageGB: 100,
    estimatedMinutes: 45,
    awsAdvantage:
      "ml.g5.12xlarge (4× A10G, 96 GB VRAM) runs the 7B VLM without model sharding; the SageMaker Distribution GPU image is selected automatically.",
    inputPath: "s3://av30lab-user-workspace/users/{userId}/m1/",
    outputPath: "s3://av30lab-user-workspace/users/{userId}/m2/",
    feedsModules: ["m03-cosmos-curator", "m08-opensearch"],
    errorHints: {
      "No GPU detected":
        "You are on a CPU instance. Open Instance Options and switch to ml.g5.12xlarge (or ml.g6.12xlarge). The GPU image is applied automatically — reopen the workspace after it restarts.",
      "EC2InsufficientCapacity":
        "ml.g5.12xlarge capacity is tight in the region. Pick the ml.g6.12xlarge alternative (4× L40S, 192 GB) instead.",
    },
  },
  {
    id: "m03-cosmos-curator",
    title: "Cosmos Curator",
    phase: "curate",
    tool: "NVIDIA NeMo Curator",
    version: "0.8",
    status: "locked",
    license: "Apache-2.0",
    sourceUrl: "https://github.com/NVIDIA/NeMo-Curator",
    recommendedInstance: "ml.g5.12xlarge",
    alternatives: ["ml.g6.12xlarge", "ml.g6.24xlarge", "ml.g5.24xlarge", "ml.g5.48xlarge", "ml.p4d.24xlarge"],
    storageGB: 100,
    estimatedMinutes: 40,
    awsAdvantage:
      "GPU-accelerated semantic dedup and quality filtering process the captioned clips in minutes rather than hours of CPU work.",
    inputPath: "s3://av30lab-user-workspace/users/{userId}/m2/",
    outputPath: "s3://av30lab-user-workspace/users/{userId}/m3/",
    feedsModules: [
      "m04-cosmos-transfer",
      "m05-cosmos-predict",
      "m06-alpamayo-vla",
      "m09-hyperpod",
    ],
    errorHints: {
      OutOfMemory:
        "Reduce the curation batch size, or step up to ml.g5.24xlarge / ml.p4d.24xlarge.",
    },
  },
  {
    id: "m04-cosmos-transfer",
    title: "Cosmos Transfer — Weather Aug",
    phase: "augment",
    tool: "NVIDIA Cosmos Transfer 2.5",
    version: "2.5",
    status: "locked",
    license: "NVIDIA Open Model License",
    sourceUrl: "https://github.com/NVIDIA/Cosmos",
    // Stage 5 — diffusion world model; shards across a multi-GPU box. g6.24xlarge
    // (4× L4, 96 GB) is the verified workshop default at 480p; p4d/p5 give 720p.
    recommendedInstance: "ml.g6.24xlarge",
    alternatives: ["ml.p4d.24xlarge", "ml.p5.48xlarge", "ml.g5.24xlarge", "ml.g5.48xlarge", "ml.g6.48xlarge"],
    storageGB: 200,
    estimatedMinutes: 60,
    awsAdvantage:
      "ml.g6.24xlarge (4× L4, 96 GB) generates weather-augmented driving clips at 480p by sharding across GPUs; EBS-backed scratch keeps large intermediate frames off S3. Step up to ml.p4d.24xlarge (8× A100) for full 720p.",
    inputPath: "s3://av30lab-user-workspace/users/{userId}/m3/",
    outputPath: "s3://av30lab-user-workspace/users/{userId}/m4/",
    feedsModules: [],
    errorHints: {
      CUDAOutOfMemory:
        "On 24 GB cards the notebook runs 480p sharded across all GPUs — first close any OTHER open notebooks (their kernels hold GPU memory), then re-run. For full 720p, move to ml.p4d.24xlarge (A100) or ml.p5.48xlarge (H100).",
    },
  },
  {
    id: "m05-cosmos-predict",
    title: "Cosmos Predict — Scenario Gen",
    phase: "augment",
    tool: "NVIDIA Cosmos Predict 2.5",
    version: "2.5",
    status: "locked",
    license: "NVIDIA Open Model License",
    sourceUrl: "https://github.com/NVIDIA/Cosmos",
    recommendedInstance: "ml.g6.24xlarge",
    alternatives: ["ml.p4d.24xlarge", "ml.p5.48xlarge", "ml.g5.24xlarge", "ml.g5.48xlarge", "ml.g6.48xlarge"],
    storageGB: 200,
    estimatedMinutes: 60,
    awsAdvantage:
      "Synthetic traffic scenarios extend the dataset beyond what was collected — an AWS-native alternative to physical re-drives. ml.g6.24xlarge (4× L4) runs it at 480×832 by sharding across GPUs; p4d/p5 give native resolution.",
    inputPath: "s3://av30lab-user-workspace/users/{userId}/m3/",
    outputPath: "s3://av30lab-user-workspace/users/{userId}/m5/",
    feedsModules: [],
    errorHints: {
      CUDAOutOfMemory:
        "On 24 GB cards the notebook runs 480×832 sharded across all GPUs — first close any OTHER open notebooks (their kernels hold GPU memory), then re-run. For native resolution, step up to ml.p4d.24xlarge or ml.p5.48xlarge.",
    },
  },
  {
    id: "m06-alpamayo-vla",
    title: "Alpamayo VLA Inference",
    phase: "train",
    tool: "NVIDIA Alpamayo 1.5 (VLA)",
    version: "1.5",
    status: "locked",
    license: "NVIDIA Open Model License",
    sourceUrl: "https://github.com/NVlabs/alpamayo1.5",
    // Stage 7 — Vision-Language-Action policy. Balanced-expert placement shards
    // the VLM across GPUs and pins the action stack to cuda:0, so 4× L4 fits.
    recommendedInstance: "ml.g6.24xlarge",
    alternatives: ["ml.p4d.24xlarge", "ml.p5.48xlarge", "ml.g5.24xlarge", "ml.g5.48xlarge", "ml.g6.48xlarge"],
    storageGB: 200,
    estimatedMinutes: 60,
    awsAdvantage:
      "ml.g6.24xlarge (4× L4, 96 GB) runs the 10B VLA policy for driving-action inference via balanced-expert GPU placement; results feed directly into closed-loop simulation. p4d/p5 also work if you have the quota.",
    inputPath: "s3://av30lab-user-workspace/users/{userId}/m3/",
    outputPath: "s3://av30lab-user-workspace/users/{userId}/m6/",
    feedsModules: ["m07-alpasim"],
    errorHints: {
      CUDAOutOfMemory:
        "The VLA policy is large and shards across all GPUs — first close any OTHER open notebooks (their kernels hold GPU memory), then re-run. Use a multi-GPU box (g6.24xlarge / p4d.24xlarge / p5.48xlarge), not a single-GPU one.",
    },
  },
  {
    id: "m07-alpasim",
    title: "AlpaSim Closed-Loop Eval",
    phase: "validate",
    tool: "NVIDIA AlpaSim",
    version: "0.96.0",
    status: "locked",
    license: "Apache-2.0 (sim) · Alpamayo weights non-commercial",
    sourceUrl: "https://github.com/NVlabs/alpasim",
    // Stage 8 — closed-loop evaluation. This SageMaker notebook is CPU: it only
    // downloads + visualizes the genuine AlpaSim results. The real simulation
    // (Docker-Compose gRPC microservices, >=40 GB GPU) runs on a GPU EC2 host
    // reached over SSM — see externalExecution below and the participant runbook.
    recommendedInstance: "ml.t3.medium",
    alternatives: ["ml.t3.large", "ml.m5.large"],
    storageGB: 20,
    estimatedMinutes: 10,
    awsAdvantage:
      "Closed-loop, software-in-the-loop testing scores the policy before any road test — the final validation gate.",
    inputPath: "s3://av30lab-user-workspace/users/{userId}/m6/",
    outputPath: "s3://av30lab-user-workspace/users/{userId}/m7/",
    feedsModules: [],
    errorHints: {
      "reference eval not found":
        "Run AlpaSim on your GPU host first (see the SSM runbook), or ask the admin to stage the shared reference run.",
    },
    externalExecution: {
      label: "Runs on a GPU EC2 host (over SSM), not in this workspace",
      summary:
        "AlpaSim is a Docker-Compose gRPC microservice fleet needing a ≥40 GB GPU, which a SageMaker notebook can't host. Your admin pre-provisions a GPU host for you; you SSH in via SSM, run the sim, then visualize the results here (CPU). This path needs your OWN Hugging Face token (the NuRec scene is gated and not in the shared cache).",
      steps: [
        "Prepare a Hugging Face token and accept the nvidia/PhysicalAI-Autonomous-Vehicles-NuRec dataset license (see Prerequisites).",
        "Get your AWS access key + GPU instance ID from the workshop admin.",
        "aws ssm start-session --target <instance-id> --region us-west-2",
        "In the session, export PARTICIPANT_ID / M7_OUTPUT_PREFIX / OUTPUT_BUCKET / HF_TOKEN (one per line), then run alpasim_ec2_setup.sh (first build tens of minutes to ~2–3 h).",
        "When it prints DONE, tell the admin so they terminate the host.",
        "Back here: open this notebook (CPU) and Run All — it auto-loads your results.",
      ],
      costWarning:
        "⚠️ The GPU host bills ~$10.5/hr while running. You cannot terminate it yourself — notify the admin the moment you are done.",
      guideHref: "https://github.com/NVlabs/alpasim",
    },
  },
  {
    id: "m08-opensearch",
    title: "OpenSearch Semantic Search",
    phase: "curate",
    tool: "Amazon OpenSearch Serverless",
    version: "2.x",
    status: "locked",
    license: "Apache-2.0",
    sourceUrl: "https://opensearch.org/",
    // Stage 4 — search & indexing runs client-side on CPU; the vector store is
    // OpenSearch Serverless (separate managed service).
    recommendedInstance: "ml.t3.medium",
    alternatives: ["ml.t3.large", "ml.m5.large", "ml.m5.xlarge"],
    storageGB: 50,
    estimatedMinutes: 20,
    awsAdvantage:
      "OpenSearch Serverless provides managed k-NN vector search — the AWS-native replacement for Cosmos Dataset Search; the notebook itself only needs CPU.",
    inputPath: "s3://av30lab-user-workspace/users/{userId}/m2/",
    outputPath: "s3://av30lab-user-workspace/users/{userId}/m8/",
    feedsModules: [],
    errorHints: {
      AccessDenied:
        "The execution role needs aoss (OpenSearch Serverless) data-access permissions on the collection.",
    },
  },
  {
    id: "m09-hyperpod",
    title: "HyperPod Distributed Training",
    phase: "train",
    tool: "SageMaker HyperPod",
    version: "1.0",
    status: "locked",
    license: "AWS Service",
    sourceUrl: "https://aws.amazon.com/sagemaker/hyperpod/",
    // Extension — the notebook is CPU: it submits a real 2-node torch.distributed
    // DDP training job (ml.m5.xlarge x2, gloo) on M3's captions and visualizes the
    // measured metrics. True HyperPod (p4d cluster, Slurm/EKS/FSx/EFA) is separate
    // infrastructure a notebook can't provision — covered conceptually. See
    // docs/HYPERPOD_M9.md.
    recommendedInstance: "ml.t3.medium",
    alternatives: ["ml.t3.large", "ml.m5.large"],
    storageGB: 20,
    estimatedMinutes: 20,
    awsAdvantage:
      "HyperPod manages resilient multi-node clusters with automatic node replacement — training continues through hardware failures. This module demonstrates the distributed-training pattern it scales.",
    inputPath: "s3://av30lab-user-workspace/users/{userId}/m3/",
    outputPath: "s3://av30lab-user-workspace/users/{userId}/m9/",
    feedsModules: [],
    errorHints: {
      ResourceLimitExceeded:
        "The training job (ml.m5.xlarge x2) needs SageMaker training quota. CPU training quota is usually available; if not, ask the admin. GPU (g5) is optional — see docs/HYPERPOD_M9.md.",
    },
  },
  {
    id: "m10-nerfstudio",
    title: "Nerfstudio 3D Reconstruction",
    phase: "augment",
    tool: "Nerfstudio",
    version: "1.1",
    status: "locked",
    license: "Apache-2.0",
    sourceUrl: "https://github.com/nerfstudio-project/nerfstudio",
    // Stage 6 — neural reconstruction from CAM_FRONT frames; single-GPU is fine.
    recommendedInstance: "ml.g5.xlarge",
    alternatives: ["ml.g5.2xlarge", "ml.g5.4xlarge", "ml.g6.xlarge", "ml.g6.2xlarge", "ml.g6.4xlarge"],
    storageGB: 100,
    estimatedMinutes: 90,
    awsAdvantage:
      "A single A10G reconstructs neural radiance fields from nuScenes CAM_FRONT images — an independent branch reading the dataset directly.",
    inputPath: "s3://av30lab-shared-data/datasets/nuscenes-mini/ (CAM_FRONT)",
    outputPath: "s3://av30lab-user-workspace/users/{userId}/m10/",
    feedsModules: [],
    errorHints: {
      "No GPU detected":
        "Nerfstudio needs a GPU — select ml.g5.xlarge in Instance Options.",
    },
  },
  {
    id: "m11-orchestration",
    title: "Pipeline Automation",
    phase: "validate",
    tool: "SageMaker Pipelines",
    version: "2.x",
    status: "locked",
    license: "AWS Service",
    sourceUrl: "https://aws.amazon.com/sagemaker/pipelines/",
    // Extension — orchestrates M1→M4 as one SageMaker Pipeline. Notebook + all 3
    // steps run on CPU (steps are pure Python over M1 metadata); the pipeline
    // pattern is identical to a GPU production run. See docs/PIPELINE_M11.md.
    recommendedInstance: "ml.t3.medium",
    alternatives: ["ml.t3.large", "ml.m5.large"],
    storageGB: 20,
    estimatedMinutes: 15,
    awsAdvantage:
      "SageMaker Pipelines turns the manual M1→M4 notebook steps into one repeatable, parameterized DAG — authoring runs on CPU, steps auto start/stop.",
    inputPath: "s3://av30lab-user-workspace/users/{userId}/m1/",
    outputPath: "s3://av30lab-user-workspace/users/{userId}/m11/",
    feedsModules: [],
    errorHints: {
      "ModuleNotFoundError sagemaker":
        "Run cell-1 first — it pins SageMaker SDK v2 and auto-restarts the kernel; then Run All again.",
      "Step failed / 0 captions":
        "Run M1 first so users/<id>/m1/selected_scenes.json exists — Step 1 captions those scenes.",
      "Unsupported image scope":
        "sklearn has no 'processing' image scope — call image_uris.retrieve without image_scope (already fixed in the current notebook; re-sync from notebook-templates if you still see this).",
    },
  },
];
