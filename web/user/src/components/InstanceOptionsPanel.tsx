import React, { useState, useEffect, useRef, useCallback } from "react";
import {
  Box,
  Button,
  ColumnLayout,
  Flashbar,
  Header,
  Modal,
  RadioGroup,
  SpaceBetween,
  type RadioGroupProps,
  type FlashbarProps,
} from "@cloudscape-design/components";
import { type ModuleConfig } from "../data/pipeline-config";
import { useTokenAuth } from "../auth/TokenProvider";
import { ApiError, type AppStatusResponse } from "../api/client";

interface InstanceOptionsPanelProps {
  module: ModuleConfig;
  onClose: () => void;
}

export function InstanceOptionsPanel({
  module,
  onClose,
}: InstanceOptionsPanelProps): React.JSX.Element {
  const { userId, apiClient } = useTokenAuth();
  const [selectedInstance, setSelectedInstance] = useState(module.recommendedInstance);
  const [storageGB, setStorageGB] = useState(module.storageGB);
  const [applying, setApplying] = useState(false);
  const [applyError, setApplyError] = useState<string | null>(null);
  // Live app status after Apply — polled from the backend so the participant
  // sees Pending/InService/Failed instead of a static label. null = not polling.
  const [appStatus, setAppStatus] = useState<AppStatusResponse | null>(null);
  const [polling, setPolling] = useState(false);
  const pollTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Poll getAppStatus until the app reaches a terminal state (InService / Failed
  // / NotFound). Started after Apply. Cleared on unmount.
  const pollAppStatus = useCallback(() => {
    if (!userId || !apiClient) return;
    let cancelled = false;

    const tick = async () => {
      try {
        const s = await apiClient.getAppStatus(userId);
        if (cancelled) return;
        // B1 fix: after a capacity failure on instance A, the participant picks
        // instance B and re-applies. The just-Failed app for A may not have been
        // torn down yet, so the FIRST poll can read that stale Failed app —
        // carrying A's capacityError — and (previously) latch the terminal gate,
        // showing last cycle's error against the wrong instance. Ignore a
        // terminal status whose instanceType doesn't match what we just applied:
        // treat it as the old app still deleting and keep polling until the new
        // app (selectedInstance) appears.
        const isStaleTerminal =
          (s.status === "InService" || s.status === "Failed") &&
          !!s.instanceType &&
          s.instanceType !== selectedInstance;
        if (!isStaleTerminal) {
          setAppStatus(s);
          // Terminal states stop the poll; Pending/Deleting keep going.
          if (s.status === "InService" || s.status === "Failed") {
            setPolling(false);
            return;
          }
        }
      } catch {
        // Transient (e.g. API GW hiccup) — keep polling; don't surface noise.
      }
      if (!cancelled) {
        pollTimer.current = setTimeout(() => void tick(), 8000);
      }
    };

    setPolling(true);
    void tick();
    return () => {
      cancelled = true;
      if (pollTimer.current) clearTimeout(pollTimer.current);
    };
  }, [userId, apiClient, selectedInstance]);

  useEffect(() => {
    return () => {
      if (pollTimer.current) clearTimeout(pollTimer.current);
    };
  }, []);

  const instanceOptions: RadioGroupProps.RadioButtonDefinition[] = [
    {
      value: module.recommendedInstance,
      label: module.recommendedInstance,
      description: "Recommended — optimized for this module",
    },
    ...module.alternatives.map((alt) => ({
      value: alt,
      label: alt,
      description: getInstanceDescription(alt),
    })),
  ];

  // Storage the user has chosen to add on top of the module default.
  const storageAdded = storageGB - module.storageGB;

  const firstErrorKey = Object.keys(module.errorHints)[0];
  const firstErrorHint = firstErrorKey ? module.errorHints[firstErrorKey] : null;

  function handleInstanceChange(detail: RadioGroupProps.ChangeDetail): void {
    setSelectedInstance(detail.value);
  }

  function handleAddStorage(amount: number): void {
    setStorageGB((prev) => prev + amount);
  }

  function handleRevert(): void {
    setSelectedInstance(module.recommendedInstance);
    setStorageGB(module.storageGB);
  }

  async function handleApply(): Promise<void> {
    if (!userId || !apiClient) {
      setApplyError(
        "Not authenticated. Open this dashboard via the participant link " +
          "(?userId=...&token=...)."
      );
      return;
    }
    setApplying(true);
    setApplyError(null);
    setAppStatus(null);
    try {
      // Always apply the selected instance. We do NOT assume the workspace is
      // already on the recommended instance — a freshly-provisioned user starts
      // on ml.t3.medium (CPU), so selecting the recommended GPU instance and
      // clicking Apply must actually switch it. The backend returns 409 when the
      // workspace is already on the requested type; treat that as a no-op.
      //
      // The change can take minutes (delete app -> resize -> recreate), which can
      // exceed the API Gateway 29s timeout and surface as a 502/504 even though
      // the change is proceeding server-side. So a gateway timeout is NOT fatal:
      // we fall through to polling getAppStatus, which reflects the real outcome.
      try {
        await apiClient.changeInstance(userId, selectedInstance);
      } catch (e) {
        const isAlreadySet = e instanceof ApiError && e.status === 409;
        const isGatewayTimeout =
          e instanceof ApiError && (e.status === 502 || e.status === 504);
        if (!isAlreadySet && !isGatewayTimeout) {
          throw e;
        }
      }
      if (storageAdded > 0) {
        try {
          await apiClient.expandStorage(userId, storageAdded);
        } catch (e) {
          // Same gateway-timeout tolerance for the storage resize.
          if (!(e instanceof ApiError && (e.status === 502 || e.status === 504))) {
            throw e;
          }
        }
      }
      // Do not close — start polling so the user watches the workspace come up
      // (and sees a capacity failure with an actionable hint if it happens).
      pollAppStatus();
    } catch (e) {
      setApplyError(
        e instanceof Error ? e.message : "Failed to apply changes. Try again."
      );
    } finally {
      setApplying(false);
    }
  }

  const isGpuInstance = /^ml\.(g4dn|g5|g6|p3|p4d|p5)\./.test(selectedInstance);
  const canRevert =
    selectedInstance !== module.recommendedInstance || storageAdded !== 0;

  return (
    <Modal
      visible
      onDismiss={onClose}
      header={<Header variant="h2">Instance Options — {module.title}</Header>}
      size="medium"
      footer={
        <Box float="right">
          <SpaceBetween direction="horizontal" size="xs">
            <Button
              variant="link"
              onClick={handleRevert}
              disabled={!canRevert || applying || polling}
            >
              Revert to Default
            </Button>
            <Button variant="normal" onClick={onClose} disabled={applying}>
              {polling || appStatus ? "Close" : "Cancel"}
            </Button>
            <Button
              variant="primary"
              onClick={() => void handleApply()}
              disabled={applying || polling}
              loading={applying}
            >
              Apply &amp; Restart
            </Button>
          </SpaceBetween>
        </Box>
      }
    >
      <SpaceBetween size="l">
        {/* Apply error */}
        {applyError && (
          <Flashbar
            items={[
              {
                type: "error",
                content: applyError,
                dismissible: true,
                onDismiss: () => setApplyError(null),
                id: "apply-error",
              },
            ]}
          />
        )}

        {/* Live app status after Apply (Pending / InService / Failed+capacity) */}
        {(polling || appStatus) && (
          <Flashbar items={[buildStatusFlash(appStatus, polling)]} />
        )}

        {/* Restart notice — applying an instance change always recreates the app */}
        <Flashbar
          items={[
            {
              type: "info",
              header: "Applying restarts your workspace",
              content:
                `“Apply & Restart” switches your workspace to ${selectedInstance}` +
                (isGpuInstance
                  ? " and loads the GPU software image automatically."
                  : ".") +
                " This recreates JupyterLab (a few minutes). When it finishes, " +
                "click “Open Workspace” again to get a fresh link.",
              dismissible: false,
              id: "restart-notice",
            },
          ]}
        />

        {/* Error Hints Banner */}
        {firstErrorHint && (
          <Flashbar
            items={[
              {
                type: "warning",
                header: `Common issue: ${firstErrorKey}`,
                content: firstErrorHint,
                dismissible: false,
                id: "error-hint",
              },
            ]}
          />
        )}

        {/* Recommended Instance */}
        <Box>
          <Box variant="awsui-key-label" margin={{ bottom: "xxs" }}>
            Recommended Instance
          </Box>
          <Box fontSize="heading-m" fontWeight="bold">
            {module.recommendedInstance}
          </Box>
          <Box color="text-body-secondary" fontSize="body-s">
            Optimized instance for this module — selected by default
          </Box>
        </Box>

        {/* Instance Selection */}
        <Box>
          <Box variant="awsui-key-label" margin={{ bottom: "xs" }}>
            Select Instance Type
          </Box>
          <RadioGroup
            value={selectedInstance}
            onChange={({ detail }) => handleInstanceChange(detail)}
            items={instanceOptions}
          />
        </Box>

        {/* Storage Options */}
        <Box>
          <Box variant="awsui-key-label" margin={{ bottom: "xs" }}>
            Storage (EBS gp3)
          </Box>
          <Box fontSize="heading-m" fontWeight="bold" margin={{ bottom: "s" }}>
            {storageGB} GB
          </Box>
          <ColumnLayout columns={2}>
            <Button
              onClick={() => handleAddStorage(50)}
              iconName="add-plus"
            >
              +50 GB
            </Button>
            <Button
              onClick={() => handleAddStorage(200)}
              iconName="add-plus"
            >
              +200 GB
            </Button>
          </ColumnLayout>
          <Box color="text-body-secondary" fontSize="body-s" margin={{ top: "xs" }}>
            Additional storage is provisioned as gp3 EBS volumes and attached automatically.
          </Box>
        </Box>

        {/* Change Summary */}
        {canRevert && (
          <Flashbar
            items={[
              {
                type: "warning",
                content: `Will apply: Instance → ${selectedInstance}${
                  storageAdded > 0 ? `, Storage +${storageAdded} GB` : ""
                }.`,
                dismissible: false,
                id: "changes-pending",
              },
            ]}
          />
        )}
      </SpaceBetween>
    </Modal>
  );
}

/**
 * Map the live app status into a Flashbar item shown after Apply. The capacity
 * error gets an actionable hint pointing at the alternative instances (which are
 * already offered in this same panel's radio list).
 */
function buildStatusFlash(
  status: AppStatusResponse | null,
  polling: boolean
): FlashbarProps.MessageDefinition {
  const id = "app-status";

  // Still waiting for the first status, or app is coming up.
  if (!status || status.status === "Pending" || status.status === "Deleting") {
    return {
      id,
      type: "in-progress",
      loading: true,
      dismissible: false,
      header: "Workspace starting…",
      content:
        `Your workspace (${status?.instanceType ?? "GPU instance"}) is launching. ` +
        "This takes a few minutes. When it shows “running”, click “Open Workspace”.",
    };
  }

  if (status.status === "InService") {
    return {
      id,
      type: "success",
      dismissible: false,
      header: "Workspace running",
      content:
        `Your workspace is running on ${status.instanceType}. ` +
        "Close this dialog and click “Open Workspace” to launch JupyterLab.",
    };
  }

  if (status.status === "Failed") {
    if (status.capacityError) {
      return {
        id,
        type: "error",
        dismissible: false,
        header: `${status.instanceType} is temporarily unavailable (capacity)`,
        content:
          "AWS is temporarily out of this instance type in the region. " +
          "Pick an alternative above (e.g. ml.g6.12xlarge) and click " +
          "“Apply & Restart” again — it usually launches right away.",
      };
    }
    return {
      id,
      type: "error",
      dismissible: false,
      header: "Workspace failed to start",
      content:
        status.failureReason ??
        "The workspace failed to launch. Try applying again, or pick a different instance.",
    };
  }

  // NotFound / Deleted — no live app yet.
  return {
    id,
    type: "info",
    dismissible: false,
    header: "No running workspace",
    content: polling
      ? "Waiting for the workspace to be created…"
      : "Apply & Restart to launch your workspace on the selected instance.",
  };
}

function getInstanceDescription(instanceType: string): string {
  const descriptions: Record<string, string> = {
    "ml.t3.medium": "2 vCPU, 4 GiB — Burstable CPU",
    "ml.t3.large": "2 vCPU, 8 GiB — Burstable CPU",
    "ml.t3.xlarge": "4 vCPU, 16 GiB — Burstable CPU",
    "ml.t3.2xlarge": "8 vCPU, 32 GiB — Burstable CPU",
    "ml.m5.large": "2 vCPU, 8 GiB — General purpose CPU",
    "ml.m5.xlarge": "4 vCPU, 16 GiB — General purpose CPU",
    "ml.m5.2xlarge": "8 vCPU, 32 GiB — General purpose CPU",
    "ml.m5.4xlarge": "16 vCPU, 64 GiB — General purpose CPU",
    "ml.c5.large": "2 vCPU, 4 GiB — Compute optimized CPU",
    "ml.c5.xlarge": "4 vCPU, 8 GiB — Compute optimized CPU",
    "ml.c5.2xlarge": "8 vCPU, 16 GiB — Compute optimized CPU",
    "ml.g4dn.xlarge": "4 vCPU, 16 GiB, 1× T4 (16 GB) — GPU inference",
    "ml.g4dn.2xlarge": "8 vCPU, 32 GiB, 1× T4 (16 GB) — GPU inference",
    "ml.g5.xlarge": "4 vCPU, 16 GiB, 1× A10G (24 GB) — GPU compute",
    "ml.g5.2xlarge": "8 vCPU, 32 GiB, 1× A10G (24 GB) — GPU compute",
    "ml.g5.4xlarge": "16 vCPU, 64 GiB, 1× A10G (24 GB) — GPU compute",
    "ml.g5.12xlarge": "48 vCPU, 192 GiB, 4× A10G (96 GB) — multi-GPU",
    "ml.g5.24xlarge": "96 vCPU, 384 GiB, 4× A10G (96 GB) — multi-GPU",
    "ml.g5.48xlarge": "192 vCPU, 768 GiB, 8× A10G (192 GB) — multi-GPU",
    "ml.g6.xlarge": "4 vCPU, 16 GiB, 1× L4 (24 GB) — GPU compute",
    "ml.g6.2xlarge": "8 vCPU, 32 GiB, 1× L4 (24 GB) — GPU compute",
    "ml.g6.4xlarge": "16 vCPU, 64 GiB, 1× L4 (24 GB) — GPU compute",
    "ml.g6.12xlarge": "48 vCPU, 192 GiB, 4× L4 (96 GB) — g5.12xl fallback",
    "ml.g6.24xlarge": "96 vCPU, 384 GiB, 4× L4 (96 GB) — multi-GPU",
    "ml.g6.48xlarge": "192 vCPU, 768 GiB, 8× L4 (192 GB) — multi-GPU",
    "ml.p3.2xlarge": "8 vCPU, 61 GiB, 1× V100 (16 GB) — ML training",
    "ml.p4d.24xlarge": "96 vCPU, 1152 GiB, 8× A100 (320 GB) — large-scale ML",
    "ml.p5.48xlarge": "192 vCPU, 2 TiB, 8× H100 (640 GB) — frontier training",
  };

  return descriptions[instanceType] ?? "Custom configuration";
}
