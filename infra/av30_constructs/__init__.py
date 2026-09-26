"""Shared constants for the lab's CDK constructs.

Values here are ones that MUST be identical in two places that cannot see each other:
the CloudFormation resource that creates something, and the Lambda environment that later
reasons about it. Duplicating such a value as two literals is how the storage display came
to disagree with the actual volume — the domain created 5 GB while
`expand_storage` assumed 5 and `pipeline-config.ts` displayed 20/50/100/200.
"""

# EBS volume size, in GB, that a participant's JupyterLab space is created with.
#
# Consumed in exactly two places, which is the point:
#   * infra/av30_constructs/sagemaker.py — the domain's DefaultEbsVolumeSizeInGb, i.e. what
#     create_space() inherits.
#   * infra/av30_constructs/api.py — injected as the DEFAULT_SPACE_STORAGE_GB env var so
#     infra/lambda/shared/config.py reads the same number.
#
# 200 GB matches the largest per-module recommendation in
# web/user/src/data/pipeline-config.ts, so no module needs a mid-lab resize. gp3 in
# ap-northeast-2 is $0.0912/GB-month => ~$18.24 per participant per month. AWS does not
# allow SHRINKING a space's EBS volume, so raising this is a one-way decision for every
# space created afterwards; growing later is available to participants via +50/+200
# (expand_storage, ceiling MAX_STORAGE_GB = 500).
DEFAULT_SPACE_STORAGE_GB = 200

# NOTE for whoever adds the next one: SMD_IMAGE_VERSION_ALIAS ("4.2.1") is currently a
# literal in BOTH infra/av30_constructs/api.py and infra/lambda/shared/config.py. It has the
# same drift hazard and belongs here too; left alone here only to keep this change scoped.
