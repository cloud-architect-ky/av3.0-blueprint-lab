# M7 (Nerfstudio) — the splatfacto training cell

This is the document the notebook and `scripts/setup_gsplat_env.sh` point at when the
3D-training step fails. Read the first section before you spend time debugging: the
repository itself does not agree on whether this cell is expected to work.

---

## 1. The repo states two contradictory things. Neither is measured.

| Where | Claim |
|---|---|
| `notebooks/M7_Nerfstudio_3D_Reconstruction.ipynb` cell 0 | "The **splatfacto training cell (cell 5) does NOT run** on the current SageMaker Distribution GPU image … Real training needs a **custom image with the full CUDA toolkit**." |
| the same notebook, cell 5 | "**`scripts/setup_gsplat_env.sh` … fixes all of it** the durable way … so training runs end-to-end (a genuine Gaussian-Splatting pipeline)." |
| `docs/en/ADMIN_GUIDE.md` | "**M7 now trains** — the `splatfacto` cell works after a one-time gsplat CUDA build." |
| `docs/en/PARTICIPANT_GUIDE.md` | M7 is "known-limited"; "Don't be surprised if that last cell fails." |

Both notebook claims were introduced in the **same commit** (`7260cf8`), so the history
cannot arbitrate between them. The ADMIN_GUIDE's optimistic line is *older* than the
script it credits.

**The execution record does not settle it either.** In
`examples/notebooks-with-outputs.tar.gz`, the Nerfstudio notebook has output cells for
**2 of 9** cells — setup and the GPU check. Every cell from the install onward executed
with **no retained output**. So nobody has a captured run of this cell either passing or
failing.

**Status: UNVERIFIED.** Treat M7 as optional until someone runs it.

---

## 2. How to settle it — ~$0.25, about 15 minutes

M7's recommended instance is `ml.g5.xlarge` (1× A10G 24 GB, ~$1.41/hr in us-west-2,
~$1.73 in ap-northeast-2). One Run-All answers the question.

1. Provision one throwaway participant, set the instance to `ml.g5.xlarge`.
2. **Restart & Run All.** Do not skip the install cell — see the ephemerality note below.
3. Record what actually happens at cell 5, then delete two of the three claims above so
   only the true one survives, and replace this section with the result.

Tear the profile down afterwards: `scripts/teardown.sh --user <id>`.

---

## 3. What the failure looks like, and what the script already does about it

`splatfacto` needs **gsplat**, whose PyPI distribution is pure-Python: the CUDA kernels
are JIT-compiled from source on first use. The SageMaker Distribution image ships the CUDA
*runtime* and `nvcc`, but its conda CUDA **dev** packages are incomplete and split across
non-standard paths. A naive build therefore fails on:

- missing headers — `cuda_runtime.h`, `fatbinary_section.h`
- an `nvvm` mismatch, so `nvcc` cannot find `cicc`
- and critically, `ns-train` re-compiles in a **fresh subprocess** that ignores any
  `CPATH` you exported in the shell

`scripts/setup_gsplat_env.sh` addresses all three: it installs the missing dev headers,
symlinks `nvvm` so `nvcc` finds `cicc`, and symlinks the real CUDA headers and libs into
the standard `$CUDA_HOME/include` + `lib64` paths that torch hard-codes — so the build
works with no environment variables, in a terminal or inside `ns-train`'s subprocess. It
also adds version-matched TensorFlow-bundled nvcc headers as a gap-filler.

It builds for both architectures the lab uses: `setup_gsplat_env.sh:54`
`ARCH="${GSPLAT_ARCH:-8.6;8.9}"` covers sm_86 (A10G, `ml.g5.*`) and sm_89 (L4,
`ml.g6.*`). Note the script's own header records verification on **g6/L4 only**, while
notebook cell 3 claims "g6/L4 + g5/A10G" — another unresolved claim, and `ml.g5.xlarge`
is the recommended instance, i.e. the *unverified* arch.

### This is a per-SESSION bootstrap, not an install

`/opt/conda` is an image layer. Stopping and restarting the JupyterLab app wipes the dev
headers and symlinks — the gsplat *Python package* survives, the CUDA *build inputs* do
not. **Re-run the install cell at the start of every session** before the training cell.
It is idempotent: ~3–5 min cold, seconds when already built.

If you hit a build error, this is the first thing to check. An app that idle-shut-down
(90 min default) and was reopened is the common case.

---

## 4. If it does not work: the demo path

M7 is explicitly optional. Cells 1–4 — setup, GPU check, Nerfstudio install, nuScenes
multi-camera data prep — run and demonstrate the reconstruction *pipeline*: loading real
nuScenes camera images, building camera poses and intrinsics, and writing the
`transforms.json` a Gaussian-Splatting trainer consumes. That is a legitimate walkthrough
of blog Stage 6 without the training step.

Present it that way rather than as a failure, and move on to M8/M9.

---

## 5. A separate limitation that survives even if training works

The camera poses written in the data-prep cell are a **synthetic sin-wave trajectory**,
not real nuScenes calibration. So even a clean `splatfacto` run is a **smoke test** of the
pipeline, not a metrically correct reconstruction.

Making it real means wiring nuScenes `calibrated_sensor` + `ego_pose` into
`transforms.json`. The tables are already staged — `scripts/stage_nuscenes.sh` copies the
whole `v1.0-mini/*.json` set — so this is a data-plumbing task, not a missing-data one.

Note also that the blog's canonical Stage 6 uses NVIDIA Omniverse **NuRec** (commercial);
Nerfstudio is the open-source stand-in here, so exact parity with the blog was never the
goal.
