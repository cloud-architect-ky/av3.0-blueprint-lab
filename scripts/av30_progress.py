"""AV 3.0 Blueprint Lab — participant progress ping (shared helper).

Each pipeline notebook's FINAL cell calls mark_complete("<canonical-module-id>")
to flip that module's node on the participant dashboard. Best-effort and
NON-FATAL: a failed ping must NEVER fail the module (the notebook already did the
real work by the time this runs). Skips silently when run outside a provisioned
workspace (e.g. locally), where the env vars below are absent.

Env vars are injected by the JupyterLab notebook-sync lifecycle config at app
launch, sourced from the participant's own users/<id>/.av30-progress.env:
  AV30_API_URL         e.g. https://<api>.execute-api.us-west-2.amazonaws.com/prod
  AV30_PROGRESS_TOKEN  the participant's X-Api-Key token
  USER_PROFILE         the participant userId (== the {id} path segment)

Canonical module ids (must match web/user/src/data/pipeline-config.ts):
  M1 -> m01-data-exploration   M2 -> m02-cosmos-reason   M3 -> m03-cosmos-curator
  M4 -> m04-cosmos-transfer     M5 -> m05-cosmos-predict  M6 -> m06-alpamayo-vla
  M7 -> m07-alpasim             M8 -> m08-opensearch      M9 -> m09-hyperpod
  M10 -> m10-nerfstudio         M11 -> m11-orchestration
"""
import os


def mark_complete(module_id, timeout=5.0):
    """POST {moduleId, status:"completed"} for this participant. Returns True on
    success, False otherwise (never raises). Re-running a notebook re-POSTs the
    same value — idempotent, harmless."""
    api = os.environ.get("AV30_API_URL", "").strip().rstrip("/")
    token = os.environ.get("AV30_PROGRESS_TOKEN", "").strip()
    profile = os.environ.get("USER_PROFILE", "").strip()
    if not (api and token and profile):
        print(f"[progress] skipped — not in a provisioned workspace; "
              f"'{module_id}' not marked on the dashboard.")
        return False
    try:
        import requests
        resp = requests.post(
            f"{api}/sessions/{profile}/progress",
            json={"moduleId": module_id, "status": "completed"},
            headers={"X-Api-Key": token},
            timeout=timeout,
        )
        if resp.status_code < 300:
            print(f"[progress] '{module_id}' marked complete on your dashboard.")
            return True
        print(f"[progress] dashboard update skipped (HTTP {resp.status_code}) — "
              f"the module still completed successfully.")
        return False
    except Exception as e:  # noqa: BLE001 — best-effort; never fail the module
        print(f"[progress] dashboard update skipped ({type(e).__name__}) — "
              f"the module still completed successfully.")
        return False
