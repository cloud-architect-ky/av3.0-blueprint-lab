#!/usr/bin/env python3
"""Regenerate infra/lambda/shared/instance_rates.py from the AWS Price List API.

WHY THIS EXISTS
---------------
`INSTANCE_RATES` used to be a hand-maintained us-west-2 price snapshot that ALSO served as
the participant-facing instance allowlist. Two things went wrong with that, both measured:

  1. Prices drifted and disagreed across five separate copies of the table (config.py,
     grab_gpu_instance.py, and three notebook `_RATES` dicts), and every one of them was
     wrong for any region other than us-west-2. ap-northeast-2 is ~+23% across the board,
     so every cost shown to a participant or admin read ~23% LOW — the wrong direction for
     a lab whose documented failure mode is unnoticed spend.

  2. Because the allowlist was the table's keys, a region was offered instance types it
     cannot run. The whole ml.g6/g6e family has no Studio quota in ap-northeast-2, and
     eu-west-1 has no Studio-JupyterLab product for ml.g6.24xlarge at all — the participant
     picked it and their app failed to start.

So the table is now GENERATED per region from the authoritative source, and a region that
has not been generated fails LOUDLY at import rather than silently quoting another region's
prices.

WHAT IT RECORDS
---------------
Only types in CANDIDATE_TYPES (the curated set the lab's modules and docs actually
reference) AND that the target region really prices for Studio-JupyterLab. A type the
region does not offer is simply absent, which is what removes it from the dropdown.

Prices come from `platoinstancetype=Studio-JupyterLab`, which is the dimension a Studio
JupyterLab space is billed under. Do NOT substitute Studio-Notebook / Training / Hosting:
they can differ per type, and mixing them is how a table becomes quietly wrong.

QUOTA IS NOT PRICE
------------------
A price existing does NOT mean the account can launch it — quota is a separate,
per-(account x region) fact that changes over time, so it is deliberately NOT baked in
here. `instance_options` resolves live quota at request time instead.

USAGE
-----
    ./scripts/refresh_instance_rates.py --region us-west-2 --region ap-northeast-2
    ./scripts/refresh_instance_rates.py --region <new-region> --merge   # keep existing

Needs `pricing:GetProducts` (the Price List API lives in us-east-1 / eu-central-1 only;
this script always calls us-east-1 and passes the target region as a FILTER).
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import pathlib
import re
import sys

try:
    import boto3
except ImportError:  # pragma: no cover
    sys.exit("boto3 is required: pip install boto3")

OUT_PATH = (
    pathlib.Path(__file__).resolve().parent.parent
    / "infra" / "lambda" / "shared" / "instance_rates.py"
)

# The curated set. Deliberately NOT "everything the region prices" (that is ~148 types per
# region, which is noise for a participant dropdown). Keep in step with the module defaults
# in MODULE_CONFIG and with what the docs tell participants to pick.
CANDIDATE_TYPES = [
    # CPU
    "ml.t3.medium", "ml.t3.large", "ml.t3.xlarge", "ml.t3.2xlarge",
    "ml.m5.large", "ml.m5.xlarge", "ml.m5.2xlarge", "ml.m5.4xlarge",
    "ml.c5.large", "ml.c5.xlarge", "ml.c5.2xlarge",
    # g4dn — 1x T4 16 GB
    "ml.g4dn.xlarge", "ml.g4dn.2xlarge",
    # g5 — A10G 24 GB/card; 1 GPU to 8xlarge, 4 on 12/24xlarge, 8 on 48xlarge
    "ml.g5.xlarge", "ml.g5.2xlarge", "ml.g5.4xlarge", "ml.g5.8xlarge",
    "ml.g5.12xlarge", "ml.g5.24xlarge", "ml.g5.48xlarge",
    # g6 — L4 24 GB/card (NOT L40S; that is g6e). Same per-GPU VRAM tier as g5.
    "ml.g6.xlarge", "ml.g6.2xlarge", "ml.g6.4xlarge",
    "ml.g6.12xlarge", "ml.g6.24xlarge", "ml.g6.48xlarge",
    # g7e — RTX PRO 6000 Blackwell 96 GB/card. GPU count is NOT the size:
    # 2xl/4xl/8xl = 1 GPU, 12xl = 2, 24xl = 4, 48xl = 8.
    "ml.g7e.2xlarge", "ml.g7e.4xlarge", "ml.g7e.8xlarge",
    "ml.g7e.12xlarge", "ml.g7e.24xlarge", "ml.g7e.48xlarge",
    # p-family — 40 GB and 80 GB per-GPU tiers
    "ml.p3.2xlarge", "ml.p4d.24xlarge", "ml.p5.48xlarge",
]

_GPU_RE = re.compile(r"^ml\.(g\d|p\d|inf\d?|trn\d?)")


def fetch_region_rates(region: str) -> dict[str, float]:
    """All Studio-JupyterLab on-demand rates the region publishes, keyed by instance type."""
    pricing = boto3.client("pricing", region_name="us-east-1")
    rates: dict[str, float] = {}
    pages = pricing.get_paginator("get_products").paginate(
        ServiceCode="AmazonSageMaker",
        Filters=[
            {"Type": "TERM_MATCH", "Field": "regionCode", "Value": region},
            {"Type": "TERM_MATCH", "Field": "platoinstancetype", "Value": "Studio-JupyterLab"},
        ],
    )
    for page in pages:
        for raw in page["PriceList"]:
            doc = json.loads(raw)
            attrs = doc["product"]["attributes"]
            itype = attrs.get("instanceType") or attrs.get("instancename")
            if not itype:
                continue
            for term in doc["terms"].get("OnDemand", {}).values():
                for dim in term["priceDimensions"].values():
                    price = float(dim["pricePerUnit"].get("USD", 0) or 0)
                    # A $0 entry is a free-tier/placeholder row, not a real rate.
                    if price > 0:
                        rates[itype] = price
    return rates


def load_existing() -> dict[str, dict[str, float]]:
    """Read the currently generated table so --merge can keep other regions."""
    if not OUT_PATH.exists():
        return {}
    ns: dict = {}
    try:
        exec(compile(OUT_PATH.read_text(), str(OUT_PATH), "exec"), ns)  # noqa: S102
    except Exception:  # noqa: BLE001 — a corrupt file must not block regeneration
        return {}
    return ns.get("RATES_BY_REGION", {})


def render(by_region: dict[str, dict[str, float]], stamp: str) -> str:
    lines = [
        '"""AUTO-GENERATED by scripts/refresh_instance_rates.py — DO NOT EDIT BY HAND.',
        "",
        "Studio-JupyterLab on-demand rates (USD/hour), keyed by REGION then instance type.",
        "",
        "Source : AWS Price List API, ServiceCode=AmazonSageMaker,",
        "         platoinstancetype=Studio-JupyterLab",
        f"Fetched: {stamp}",
        "",
        "A type absent from a region's dict is NOT offered for Studio-JupyterLab there, which",
        "is what keeps it out of the participant dropdown. A REGION absent from this file makes",
        "config.py raise at import rather than quote another region's prices — regenerate with:",
        "",
        "    ./scripts/refresh_instance_rates.py --region <region> --merge",
        "",
        "Prices are NOT quotas. A rate here only means the region sells the type; whether this",
        "account may launch it is a separate per-(account x region) fact resolved at runtime.",
        '"""',
        "",
        "RATES_BY_REGION = {",
    ]
    for region in sorted(by_region):
        rates = by_region[region]
        lines.append(f'    "{region}": {{')
        cpu = {k: v for k, v in rates.items() if not _GPU_RE.match(k)}
        gpu = {k: v for k, v in rates.items() if _GPU_RE.match(k)}
        for label, group in (("CPU", cpu), ("GPU", gpu)):
            if not group:
                continue
            lines.append(f"        # --- {label} ---")
            for itype in sorted(group, key=lambda k: (group[k], k)):
                lines.append(f'        "{itype}": {group[itype]},')
        lines.append("    },")
    lines += ["}", ""]
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--region", action="append", required=True, dest="regions",
                    help="target region (repeatable)")
    ap.add_argument("--merge", action="store_true",
                    help="keep regions already in the file instead of replacing it")
    args = ap.parse_args()

    by_region = load_existing() if args.merge else {}

    for region in args.regions:
        published = fetch_region_rates(region)
        if not published:
            print(f"  {region}: NO Studio-JupyterLab products returned — refusing to write "
                  f"an empty region (wrong credentials, or the region has no Studio?)",
                  file=sys.stderr)
            return 2
        kept = {t: published[t] for t in CANDIDATE_TYPES if t in published}
        missing = [t for t in CANDIDATE_TYPES if t not in published]
        by_region[region] = kept
        print(f"  {region}: {len(kept)}/{len(CANDIDATE_TYPES)} candidate types priced")
        if missing:
            print(f"     not offered for Studio-JupyterLab here: {', '.join(missing)}")

    stamp = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%d")
    OUT_PATH.write_text(render(by_region, stamp))
    print(f"  wrote {OUT_PATH.relative_to(pathlib.Path.cwd())} "
          f"({len(by_region)} region(s): {', '.join(sorted(by_region))})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
