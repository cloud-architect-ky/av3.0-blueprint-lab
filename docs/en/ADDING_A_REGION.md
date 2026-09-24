# Adding a Region

How to stand up a **second, independent copy** of the lab in another AWS region, in the
same account, without disturbing the region you already run.

This is *not* a multi-region deployment. Each region is a self-contained lab: its own
Studio domain, buckets, API, Cognito pool, dashboards and budget. Nothing is shared
except the AWS account itself — and that is exactly where the sharp edges are, because a
handful of AWS namespaces are **account-global** rather than regional.

Everything below was measured in account `<aws-account-id>` while deploying
`ap-northeast-2` alongside a live `us-west-2`. Figures marked *(list price)* are from
AWS published pricing, not from an API call in that session.

---

## 0. Is the target region actually empty?

Do this first. "Empty region" was already false in this account — `ap-northeast-2` hosts
an unrelated `FAST-stack`.

```bash
export R=ap-northeast-2 ACCOUNT=<aws-account-id>

aws cloudformation describe-stacks --region $R --stack-name Av30BlueprintLabStack
aws s3api list-buckets --query "Buckets[?ends_with(Name,'$R')].Name"
aws sagemaker list-domains --region $R
aws sagemaker list-apps --region $R --query 'Apps[?Status==`InService`]'   # billing NOW
aws efs describe-file-systems --region $R --query 'FileSystems[].Name'     # orphan source
aws apigateway get-account --region $R --query cloudwatchRoleArn           # see §3
aws iam get-role --role-name av30-alpasim-m7                              # account-global
```

Why each matters:

- **S3 bucket names are global.** A leftover `av30lab-*-$ACCOUNT-$R` bucket from an
  abandoned attempt makes `cdk deploy` fail at bucket creation.
- **Studio creates an EFS filesystem per domain per region**, and it survives stack
  deletion on some paths. This account has orphaned filesystems from exactly that.
- **`ml.*` apps already `InService` are billing right now** — check before you assume
  the region is idle.
- **`av30-alpasim-m7`** (M10's IAM role + instance profile) is **account-global and
  un-suffixed**. See "Known sharp edges" below before running M10 anywhere.

---

## 1. Bootstrap CDK

```bash
aws cloudformation describe-stacks --region $R --stack-name CDKToolkit >/dev/null 2>&1 \
  || npx cdk bootstrap aws://$ACCOUNT/$R
```

Collision-free: every bootstrap role name carries `-{account}-{region}`.

---

## 2. Quotas (do this ~a week ahead)

**Scope: a quota is `(account × region)`.** The console's "Applied **account-level** quota
value" column and "Adjustability: **Account level**" read like "one value for the whole
account" — they do not mean that. Those labels render a **different field** from the one
that answers the region question, and the API makes the two explicit:

| Field | Question it answers | Value here |
|---|---|---|
| `QuotaAppliedAtLevel` | account **vs resource** — what the console labels | `ACCOUNT` |
| `GlobalQuota` | account-global **vs per-region** | `false` |

`list-service-quotas --quota-applied-at-level` takes the enum `[ALL, ACCOUNT, RESOURCE]`
and its own help says it "filters the response to return applied quota values for the
ACCOUNT, RESOURCE, or ALL levels". So *account-level* is the opposite of *resource-level*
(adjusted for the account rather than per individual resource) **within whichever region
the console is currently showing**. It says nothing about cross-region sharing.

Three independent proofs of the region scope:

- **`GlobalQuota`** is `false` for all **2,258** SageMaker quotas (full paginated count).
  For contrast: IAM 23/23 and Route 53 9/9 are `true`, and S3 is mixed — `General purpose
  buckets` is `true` while its replication quotas are `false`.
- The `QuotaArn` embeds the region, so they are distinct resources:
  `arn:aws:servicequotas:us-west-2:…:sagemaker/L-8ACE1754` vs
  `arn:aws:servicequotas:ap-northeast-2:…:sagemaker/L-8ACE1754`.
- Same account, same code, **different applied values** (2 vs 0), with two entirely
  separate `list-requested-service-quota-change-history` streams — increases are filed and
  approved per region.

So an increase granted in region A does nothing for region B. Quota **codes** are shared;
**values, requests and even which quotas exist** are not — `ml.g6.24xlarge for notebook
instance usage` exists in us-west-2 and does not exist in ap-northeast-2 at all (10 vs 9
search hits for "g6.24xlarge").

### Measured for the instance types this lab actually offers

| Quota (Studio JupyterLab apps) | Code | us-west-2 | ap-northeast-2 | Used by |
|---|---|---|---|---|
| `ml.t3.medium` | `L-71FAF417` | 2500 | 2500 | default workspace |
| `ml.g5.xlarge` | `L-988CE6C5` | 5 | 5 | M7 (Nerfstudio) |
| `ml.g5.12xlarge` | `L-8D2ED7BF` | 5 | 5 | M2, M3 |
| `ml.g5.24xlarge` | `L-F087CCFC` | 2 | 2 | M5, M6, M8, M9 (24 GB tier) |
| `ml.g5.48xlarge` | `L-83AB5D73` | 2 | 2 | M6/M9 sharded |
| `ml.p4d.24xlarge` | `L-AD63F1D2` | 2 | **2** | 40 GB tier — 720p, guardrails ON |
| **`ml.g6.12xlarge`** | `L-962247BA` | 2 | **0** ⚠ | M2/M3 alternative |
| **`ml.g6.24xlarge`** | `L-8ACE1754` | 2 | **0** ⚠ | dashboard default for M5, M6, M8, M9 |
| `ml.p5.48xlarge` | `L-B41FBF28` | 1 | **0** | 80 GB tier |
| `ml.m5.xlarge` *training* | `L-CCE2AFA6` | 30 | 30 | M12 |
| `ml.m5.xlarge` *processing* | `L-0307F515` | 16 | 16 | M11 |

**The whole `g6` and `g6e` family is 0 in ap-northeast-2** — not just the 24xlarge. `g7e`
is 0 in *both* regions.

**But Seoul is not GPU-blocked.** `g5` is available across the full range and
`p4d.24xlarge` is already approved at 2, so the lab runs there today with **no quota
request at all**. The module-to-instance mapping, read from
`web/user/src/data/pipeline-config.ts` rather than from module numbers:

| Instance | Seoul quota | Modules |
|---|---|---|
| `ml.t3.medium` | 2500 | M1, **M4** (OpenSearch is CPU-only), M10 viz, M11, M12 |
| `ml.g5.xlarge` | 5 | M7 |
| `ml.g5.12xlarge` | 5 | M2, M3 |
| `ml.g5.24xlarge` | **2** | M5, M6, M8, M9 — the four that default to the quota-0 g6.24xlarge |
| `ml.p4d.24xlarge` | 2 | same four, at the 40 GB tier |

So only the `ml.g5.24xlarge` row is contended: **2 concurrent participants** on M5/M6/M8/M9
(6 if you also steer people onto `g5.48xlarge` and `p4d.24xlarge`). `ml.g5.24xlarge` is the
same ~22.5 GB-per-GPU tier as the g6 default and ~22% dearer; `ml.p4d.24xlarge` is the
quality option.

An earlier version of this table put CPU-only M4 on the 24 GB tier and M10 on `g5.xlarge`,
because it used pre-renumbering module numbers. Request `g6` only if you want the documented default — and note the price
there is ~23% above us-west-2 either way.

Rather than reading that table, run the pre-flight — it resolves live quota, cross-checks
the generated rate table, and names the modules each shortfall affects:

```bash
./scripts/check_quotas.py --region $R --participants 10
```

It exits non-zero if any type the participant dashboard recommends cannot run. `deploy.sh`
also runs it at the end of a deployment. Measured for this account at 10 participants:
**neither** region passes as configured — `ml.g6.24xlarge` is wanted by four modules and
allows 2 concurrent in us-west-2 and 0 in ap-northeast-2, and `ml.g5.12xlarge` /
`ml.g5.xlarge` allow 5. Plan the cohort around that, or raise quota:

```bash
# Must be filed IN the target region. The script prints the exact code for each shortfall.
aws service-quotas request-service-quota-increase --region $R \
  --service-code sagemaker --quota-code L-8ACE1754 --desired-value 10
```

**Before requesting, check the instance is offered for Studio in that region at all.**
Availability is per-region *and per-usage-type* — "is the family in the region" is the
wrong question and will mislead you:

```bash
aws pricing get-products --region us-east-1 --service-code AmazonSageMaker \
  --filters Type=TERM_MATCH,Field=instanceType,Value=ml.g6.24xlarge \
            Type=TERM_MATCH,Field=regionCode,Value=$R \
            Type=TERM_MATCH,Field=platoinstancetype,Value=Studio-JupyterLab \
  --query 'length(PriceList)'
```

Measured: `ap-northeast-2` returns a real `APN2-Studio:JupyterLab-ml.g6.24xlarge`
product, so its quota of 0 is worth raising. **`eu-west-1` returns zero Studio products
for that type** — a quota request there would be futile; steer to the `g5` path instead.

---

## 3. Deploy

```bash
export EXPECTED_ACCOUNT_ID=$ACCOUNT
export ADMIN_EMAIL=you@example.com
export ADMIN_IP_ALLOWLIST=1.2.3.4/32          # omit to allow all
./scripts/deploy.sh --region $R
```

`deploy.sh` sets the `admin_email`, `admin_ip_allowlist` and `region` contexts for you,
and pins `--context region=$R` so `infra/app.py` cannot resolve a different region than
the shell guards just checked. Observed runtime **~3 minutes**, 176 resources.

**Leave these unset for a new region:**

| Context / env | Why not |
|---|---|
| `OWNER_TAG` | Only for updating a stack whose `Owner` tag differs from the default. SageMaker treats domain **tags** as replacement-requiring, so a mismatch replaces the Studio domain and orphans its EFS. Needed *only* in us-west-2, which is tagged `kkyoung`. |
| `HOSTED_UI_DOMAIN_EXISTS` | The most dangerous lever here. It skips declaring the Cognito hosted-UI domain, producing a pool with **no sign-in endpoint**. It exists solely for the one pre-existing unmanaged domain in us-west-2. |
| `APIGW_ACCOUNT_ROLE` | `AWS::ApiGateway::Account` is an unnamed **per-account-per-region singleton** implemented as an unconditional `PATCH /account`. If the region already has a CloudWatch role (Seoul has one belonging to `FAST-stack`), opting in **hijacks another stack's role**. Only set it if `aws apigateway get-account --region $R --query cloudwatchRoleArn` returns `None`. `deploy.sh` refuses when the existing role isn't ours. |

> **Use `deploy.sh`, not bare `cdk deploy`.** `admin_email` defaults to
> `placeholder@example.com`, so a `cdk deploy` that omits `-c admin_email=...` **replaces
> your alert email with the placeholder and deletes the real subscription** — including a
> *confirmed* one. Observed exactly that while iterating on this region. Recovery costs a
> fresh confirmation click, because the recreated subscription comes back
> `PendingConfirmation`. The placeholder subscription cannot even be cleaned up
> (`Cannot delete a subscription which is pending confirmation. Detaching subscription
> from stack.`) — it lingers until SNS discards it after ~3 days. If you must call `cdk`
> directly, always pass `-c admin_email=` (and, for us-west-2, `-c owner_tag=` and
> `-c hosted_ui_domain_exists=true`).

**You do not need a new Cognito prefix.** The hosted-UI prefix is unique per **region**,
not globally — the region is inside the hostname
(`<prefix>.auth.<region>.amazoncognito.com`). `av30lab-admin` is ACTIVE in *both*
us-west-2 and ap-northeast-2 of this account, fronting different pools. Only override
`-c hosted_ui_prefix=...` if the probe below says another account owns it there:

```bash
aws cognito-idp describe-user-pool-domain --domain av30lab-admin --region $R
```

| Response | Meaning |
|---|---|
| 200, populated `DomainDescription` | already yours |
| 200, **empty** `DomainDescription` | free — use it |
| `ResourceNotFoundException` | taken by **another account** in that region → pick a new prefix |

---

## 4. Seed the shared bucket

**Always pass `AWS_REGION` explicitly.** The seeding scripts now refuse to run without
it, because a default silently re-seeds the *first* region (they resolve the destination
bucket from the CloudFormation stack in `$REGION`).

Notebook templates are **required** — provisioning deliberately fails with
`HTTP 500 "Notebook templates are not staged in this region"` rather than handing
participants an empty workspace:

```bash
SHARED=av30lab-shared-data-$ACCOUNT-$R
aws s3 sync notebooks/ "s3://$SHARED/notebook-templates/"        --region $R
aws s3 sync scripts/   "s3://$SHARED/notebook-templates/scripts/" --region $R
```

### Then the data — BUCKET-TO-BUCKET, not by re-downloading

`cache_models.sh` pulls from Hugging Face (needs `HF_TOKEN` plus accepted licences on every
gated repo) and only then uploads. For a SECOND region that is the wrong direction: the
bytes already exist in the first region's bucket. Copy them across instead — no token, no
licence step, and S3-to-S3 rather than internet-to-you-to-S3:

```bash
SRC=av30lab-shared-data-$ACCOUNT-us-west-2     # the region that is already seeded
DST=av30lab-shared-data-$ACCOUNT-$R

# Largest first, so the long pole starts immediately. Each is resumable — re-run to finish.
aws s3 sync "s3://$SRC/model-cache/"   "s3://$DST/model-cache/"   --source-region us-west-2 --region $R
aws s3 sync "s3://$SRC/hf-cache/"      "s3://$DST/hf-cache/"      --source-region us-west-2 --region $R
aws s3 sync "s3://$SRC/datasets/"      "s3://$DST/datasets/"      --source-region us-west-2 --region $R
aws s3 sync "s3://$SRC/m10-reference/" "s3://$DST/m10-reference/" --source-region us-west-2 --region $R
```

Only use `stage_nuscenes.sh` / `cache_models.sh` when there is no seeded region to copy from:

```bash
AWS_REGION=$R ./scripts/stage_nuscenes.sh                      # public mirror, no token
AWS_REGION=$R HF_TOKEN=hf_... ./scripts/cache_models.sh        # re-downloads ~157 GiB
```

Measured from the us-west-2 source bucket:

| Prefix | Size | Objects | Modules that break without it |
|---|---|---|---|
| `notebook-templates/` | 0.55 MiB | 31 | **all** — provisioning hard-fails |
| `datasets/` (nuScenes-mini) | 5.01 GiB | 31,225 | M1, M2, M3, M5, M6, M7, M8, M9 |
| `model-cache/` | 157.45 GiB | 1,707 | M2, M8, M9 |
| `hf-cache/` | 115.00 GiB | 481 | M5, M6, M9 |
| `m10-reference/` | 0.03 GiB | 16 | M10 visualisation |
| `m8-lora-probe/` | 3 KiB | 1 | no notebook reads it — staged for completeness |
| **total** | **277.49 GiB** | **33,457** | |

Verified by reading the notebooks, not assumed: M5 and M6 reach `hf-cache/hub/` indirectly
through `scripts/setup_cosmos_env.sh`, so a grep for the prefix in those two notebooks finds
nothing. **Their failure mode without it is not an error** — `setup_cosmos_env.sh` logs
`WARNING: restore failed; will fall back to online/token download`, and that fallback needs an
`HF_TOKEN` and accepted gated licences which participants do not have. So an unseeded
`hf-cache/` turns M5/M6/M9 into a per-participant token hunt, not a clean failure.

Cost: roughly **$5.73 one-time** (transfer + requests) and **$6.94/month** storage in
ap-northeast-2 *(transfer/request unit prices are list price; the $0.025/GB-mo Seoul
storage rate is API-verified)*.

`stage_nuscenes.sh` pulls from the public `s3://motional-nuscenes` in `ap-northeast-1` with
`--no-sign-request`; that is correct and region-independent.

> `aws s3 ls` reports **current objects only**. If the new buckets have versioning, the
> real billed footprint is larger — this account has already seen 298 GB reported
> against 441.7 GB actually billed.

---

## 5. Verification checklist

1. `aws cloudformation describe-stacks --region $R --stack-name Av30BlueprintLabStack`
   → `CREATE_COMPLETE`.
2. **The budget measures the region, not $0.00.** This is the one check that has already
   caught a silent regression:
   ```bash
   aws budgets describe-budget --account-id $ACCOUNT \
     --budget-name av30lab-daily-budget-$R \
     --query 'Budget.[CostFilters,CalculatedSpend.ActualSpend.Amount]'
   ```
   `CostFilters` must be `{"Region": ["<region-code>"]}`. A **display name** there
   (`"Asia Pacific (Seoul)"`) is not rejected — it matches nothing, so the budget reads
   `0.0` for ever and never alarms. Cross-check against Cost Explorer:
   ```bash
   aws ce get-cost-and-usage --time-period Start=$YDAY,End=$TODAY --granularity DAILY \
     --metrics UnblendedCost \
     --filter "{\"Dimensions\":{\"Key\":\"REGION\",\"Values\":[\"$R\"]}}"
   ```
   Budget `0.0` while CE is `> 0` ⇒ broken filter.
3. **The budget alert can actually be delivered.** A new region means a new SNS topic and
   therefore a **new unconfirmed email subscription**. CloudFormation reports
   `CREATE_COMPLETE` for the *request*, never retries, and SNS discards unconfirmed
   subscriptions after ~3 days. `deploy.sh` warns — do not ignore it.
   ```bash
   aws sns list-subscriptions-by-topic --region $R --topic-arn <topic> \
     --query 'Subscriptions[?Protocol==`email`].[Endpoint,SubscriptionArn]'
   ```
   A `SubscriptionArn` of `PendingConfirmation` means the alarm has nowhere to go.
4. SPA config is region-local:
   `aws s3 cp s3://av30lab-admin-dashboard-$ACCOUNT-$R/config.json -` must mention only
   `$R`.
5. `aws cognito-idp describe-user-pool-domain --domain av30lab-admin --region $R` →
   `ACTIVE`, pool id prefixed `$R`.
6. **Instance rates exist for this region.** The Lambdas raise at import without them, so
   a missing table shows up as 500s on the instance endpoints rather than wrong prices:
   ```bash
   ./scripts/refresh_instance_rates.py --region $R --merge   # if not already generated
   ./scripts/check_quotas.py --region $R --participants <cohort>
   ```
7. Create a Cognito admin, sign in through the hosted UI, provision **one** participant,
   and confirm the workspace is **not empty** (measured: **32** objects — 31 staged
   templates + `.av30-progress.env`).
8. `aws apigateway get-account --region $R --query cloudwatchRoleArn` unchanged from its
   value in §0.
9. **The region you already had is untouched:** its stack still `UPDATE_COMPLETE`, its
   budget still present, its `apigateway get-account` unchanged.

### A cheap honest smoke test (well under $1)

Deploy (§3), seed **`notebook-templates/` only** (0.55 MiB ≈ $0.00), provision one
participant, start **one `ml.t3.medium`** app (quota is already 2500), run the checklist,
delete the app, then `./scripts/teardown.sh --region $R`.

That proves: all 176 resources create alongside the existing region; the Cognito prefix
genuinely coexists; the budget name and filter; `ApiGateway::Account` left alone; the
SageMaker image account mapping resolves to a real image (the app actually starts);
sign-in end-to-end; the empty-bucket guard; and that region 1 is undisturbed.

It does **not** prove: GPU capacity or quota (a `t3.medium` says nothing about
`ml.g6.24xlarge`, which is quota 0 in Seoul); that the 272 GiB you skipped is present, so
M2/M3/M5/M6/M9 will fail at model load; concurrency (one user is not ten); or that a
budget alert is actually delivered.

---

## Known sharp edges

**`INSTANCE_RATES` is a us-west-2 price snapshot — and doubles as the instance
allowlist.** `infra/lambda/shared/config.py` is not keyed by region, and
`change_instance` derives `VALID_INSTANCE_TYPES` from its keys while `instance_options`
builds the participant dropdown from them. Two consequences:

| Studio-JupyterLab | us-west-2 | ap-northeast-2 | reported |
|---|---|---|---|
| `ml.t3.medium` | $0.0500 | $0.0620 | −24% |
| `ml.g5.12xlarge` | $7.0900 | $8.7180 | −23% |
| `ml.g6.24xlarge` | $8.3440 | $10.2600 | −23% |

1. Every cost shown to participants and admins reads ~23% **low** in Seoul — the wrong
   direction for a lab whose documented failure mode is unnoticed spend.
2. The dropdown is unfiltered by region, so a region can be offered an instance it does
   not have for Studio (e.g. `ml.g6.24xlarge` in `eu-west-1`), failing per-participant
   at app start.

The uniform ~23% Seoul delta is coincidence, not a rule — do not "fix" this with a
multiplier; key the table by region.

**`av30-alpasim-m7` (M10) is account-global and un-suffixed.** IAM role and
instance-profile names are account-global, so a second region's M10 run fails
`EntityAlreadyExists`. Worse, the M10 runbook's teardown deletes both *unconditionally*
"to prevent name collisions on the next run" — so tearing down M10 in **either** region
destroys the role the other region's running GPU host is using. Suffix both names with
the region at create *and* teardown before running M10 in more than one region. The live
role's inline policies also name buckets with no region segment at all, so they no longer
match the current bucket names.

**Keep `REGION_CONFIG` / `TARGET_REGIONS` unset.** `infra/lambda/shared/config.py`
defines a dormant cross-region control plane, and `create_user` / `bulk_provision`
already accept a `region` field in the request body. Neither env var is set by the CDK,
so today everything collapses to the single deploy region — which is the independent-copy
model this document describes. Setting them would silently convert two independent labs
into one control plane managing both.

**CloudFront distributions are an account-global quota.** Each region adds 2 (plus 2
Cognito-managed ones that don't count). The default limit is 200, so there is no
practical risk, but the check is
`aws service-quotas get-service-quota --service-code cloudfront --quota-code L-24B04930`.

---

## Teardown

```bash
./scripts/teardown.sh --region $R      # or AWS_REGION=$R ./scripts/teardown.sh
```

The region is explicit and confirmation requires typing `<account>/<region>` — the script
used to default to `us-west-2`, which meant running it to reclaim region B could delete
region A instead (the old prompt only asked for the account id, which is identical for
every region). Afterwards verify the known orphan sources, none of which
CloudFormation tracks:

```bash
aws efs describe-file-systems --region $R          # Studio's per-domain filesystem
aws ec2 describe-security-groups --region $R \
  --filters "Name=group-name,Values=security-group-for-*-nfs-*"
aws s3api list-buckets --query "Buckets[?ends_with(Name,'$R')].Name"
aws budgets describe-budgets --account-id $ACCOUNT --query "Budgets[].BudgetName"
```

Deletion order for a Studio domain is apps → spaces → **user profiles** (created at
runtime, so the stack does not own them) → stack. After that, the retained EFS **mount
targets** pin the subnets and SageMaker's auto-created NFS security groups
(`security-group-for-{inbound,outbound}-nfs-<domainId>`, which reference each other on
tcp/988) pin the VPC. Revoke the cross-references before deleting the groups.
