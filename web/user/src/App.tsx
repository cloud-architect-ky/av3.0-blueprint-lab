import React, { useState, useCallback, useEffect, useMemo } from "react";
import {
  AppLayout,
  BreadcrumbGroup,
  Header,
  SpaceBetween,
  Box,
  Badge,
  Button,
  Flashbar,
  ProgressBar,
} from "@cloudscape-design/components";
import { TokenAuthProvider, useTokenAuth } from "./auth/TokenProvider";
import { loadConfig } from "./config";
import { PipelineMap } from "./components/PipelineMap";
import { ModuleDetailPanel } from "./components/ModuleDetailPanel";
import { PIPELINE_MODULES, type ModuleConfig, type ModuleStatus } from "./data/pipeline-config";

// B2: how often the dashboard re-fetches live module progress so a module
// completing in the notebook flips its node without a manual refresh.
const POLL_MS = 20_000;

// Normalize the backend's stored form ("in_progress") to the frontend enum
// ("in-progress"). Returns null for anything unrecognized (ignored -> static).
function normalizeStatus(raw: string): ModuleStatus | null {
  switch (raw) {
    case "completed":
      return "completed";
    case "in_progress":
    case "in-progress":
      return "in-progress";
    case "locked":
      return "locked";
    default:
      return null;
  }
}

function Dashboard(): React.JSX.Element {
  const { userId, isAuthenticated, apiClient } = useTokenAuth();
  const [selectedModule, setSelectedModule] = useState<ModuleConfig | null>(null);
  const [openingWorkspace, setOpeningWorkspace] = useState(false);
  const [workspaceError, setWorkspaceError] = useState<string | null>(null);
  // B3: the participant's display name, fetched from app-status. Falls back to
  // the userId slug when the row predates stored names.
  const [displayName, setDisplayName] = useState<string | null>(null);
  // B2: live per-module status from the DDB session row (canonical long ids).
  const [liveProgress, setLiveProgress] = useState<Record<string, ModuleStatus>>({});

  // Fetch identity + live module progress on mount, then poll (and on window
  // focus) so a module completing in the notebook flips its node without a
  // manual refresh. Non-fatal: on any error we keep the last-known/static view.
  useEffect(() => {
    if (!userId || !apiClient) return;
    let active = true;

    const refresh = async () => {
      try {
        const s = await apiClient.getAppStatus(userId);
        if (!active) return;
        setDisplayName(s.name || userId);
        const merged: Record<string, ModuleStatus> = {};
        for (const [id, raw] of Object.entries(s.moduleProgress ?? {})) {
          const norm = normalizeStatus(String(raw));
          if (norm) merged[id] = norm;
        }
        setLiveProgress(merged);
      } catch {
        if (active) setDisplayName((prev) => prev ?? userId);
      }
    };

    void refresh();
    const timer = window.setInterval(() => void refresh(), POLL_MS);
    const onFocus = () => void refresh();
    window.addEventListener("focus", onFocus);
    return () => {
      active = false;
      window.clearInterval(timer);
      window.removeEventListener("focus", onFocus);
    };
  }, [userId, apiClient]);

  // Merge live progress over each module's static default; derive counts from it.
  const mergedModules = useMemo(
    () => PIPELINE_MODULES.map((m) => ({ ...m, status: liveProgress[m.id] ?? m.status })),
    [liveProgress]
  );
  const completedCount = mergedModules.filter((m) => m.status === "completed").length;
  const inProgressCount = mergedModules.filter((m) => m.status === "in-progress").length;
  const totalCount = mergedModules.length;
  const progressPercent = Math.round((completedCount / totalCount) * 100);

  const handleModuleSelect = useCallback((module: ModuleConfig) => {
    setSelectedModule(module);
  }, []);

  const handleClosePanel = useCallback(() => {
    setSelectedModule(null);
  }, []);

  // Open the JupyterLab workspace via a FRESH presigned URL generated at click
  // time — avoids the 5-minute redeem-window problem entirely. One JupyterLab
  // space serves all modules, so this is not module-specific.
  const handleOpenWorkspace = useCallback(async () => {
    if (!userId || !apiClient) return;
    setOpeningWorkspace(true);
    setWorkspaceError(null);
    try {
      const { presignedUrl } = await apiClient.getWorkspaceUrl(userId);
      window.open(presignedUrl, "_blank", "noopener,noreferrer");
    } catch (e) {
      setWorkspaceError(
        e instanceof Error ? e.message : "Failed to open workspace. Try again."
      );
    } finally {
      setOpeningWorkspace(false);
    }
  }, [userId, apiClient]);

  // Per-module "Start Lab" routes to the same fresh-URL flow (moduleId unused
  // because a single JupyterLab space serves every module).
  const handleStartLab = useCallback(
    (_moduleId: string) => {
      void handleOpenWorkspace();
    },
    [handleOpenWorkspace]
  );

  return (
    <>
      <AppLayout
        navigationHide
        toolsHide
        breadcrumbs={
          <BreadcrumbGroup
            items={[
              { text: "AV 3.0 Blueprint Lab", href: "/" },
              { text: "Pipeline Map", href: "#" },
            ]}
          />
        }
        content={
          <SpaceBetween size="l">
            {/* Header */}
            <Header
              variant="h1"
              description={
                (displayName ? `${displayName} — ` : "") +
                "Autonomous Vehicle Perception Pipeline — complete each module sequentially to build your AV perception stack."
              }
              actions={
                <SpaceBetween direction="horizontal" size="s">
                  <Badge color="green">{completedCount} Completed</Badge>
                  <Badge color="blue">{inProgressCount} In Progress</Badge>
                  <Badge color="grey">
                    {totalCount - completedCount - inProgressCount} Locked
                  </Badge>
                  <Button
                    variant="primary"
                    iconName="external"
                    loading={openingWorkspace}
                    disabled={!isAuthenticated || openingWorkspace}
                    onClick={() => void handleOpenWorkspace()}
                  >
                    Open Workspace
                  </Button>
                </SpaceBetween>
              }
            >
              Pipeline Map
            </Header>

            {/* Workspace open error */}
            {workspaceError && (
              <Box padding={{ horizontal: "l" }}>
                <Flashbar
                  items={[
                    {
                      type: "error",
                      dismissible: true,
                      onDismiss: () => setWorkspaceError(null),
                      content: workspaceError,
                    },
                  ]}
                />
              </Box>
            )}

            {/* Progress Bar */}
            <Box padding={{ horizontal: "l" }}>
              <ProgressBar
                value={progressPercent}
                additionalInfo={`${completedCount} of ${totalCount} modules completed`}
                label="Overall Progress"
                variant="standalone"
              />
            </Box>

            {/* Auth Warning */}
            {!isAuthenticated && (
              <Box
                padding="m"
                margin={{ horizontal: "l" }}
                color="text-status-warning"
                fontSize="body-s"
              >
                <strong>Demo Mode</strong> — Add{" "}
                <code>?userId=YOUR_ID&amp;token=YOUR_TOKEN</code> to the URL to connect to
                your lab environment.
              </Box>
            )}

            {/* Pipeline Visualization */}
            <Box padding={{ horizontal: "l" }}>
              <div
                style={{
                  backgroundColor: "#fafafa",
                  border: "1px solid #e9ebed",
                  borderRadius: "12px",
                  padding: "20px",
                }}
              >
                <PipelineMap
                  modules={mergedModules}
                  onModuleSelect={handleModuleSelect}
                  selectedModuleId={selectedModule?.id ?? null}
                />
              </div>
            </Box>

            {/* Legend */}
            <Box padding={{ horizontal: "l", bottom: "l" }}>
              <SpaceBetween direction="horizontal" size="l">
                <LegendItem color="#037f0c" label="Completed" />
                <LegendItem color="#d97706" label="In Progress" />
                <LegendItem color="#5f6b7a" label="Locked" />
                <span
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: "6px",
                    fontSize: "13px",
                    color: "#5f6b7a",
                  }}
                >
                  <svg width="24" height="10">
                    <line
                      x1="0"
                      y1="5"
                      x2="18"
                      y2="5"
                      stroke="#adb5bd"
                      strokeWidth="2"
                      strokeDasharray="3,3"
                    />
                  </svg>
                  Locked path
                </span>
                <span
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: "6px",
                    fontSize: "13px",
                    color: "#5f6b7a",
                  }}
                >
                  <svg width="24" height="10">
                    <line x1="0" y1="5" x2="16" y2="5" stroke="#adb5bd" strokeWidth="2" />
                    <polygon points="16,2 22,5 16,8" fill="#adb5bd" />
                  </svg>
                  Data flow
                </span>
              </SpaceBetween>
            </Box>
          </SpaceBetween>
        }
      />

      {/* Detail Panel Overlay */}
      {selectedModule && (
        <ModuleDetailPanel
          module={selectedModule}
          onClose={handleClosePanel}
          onStartLab={handleStartLab}
        />
      )}
    </>
  );
}

function LegendItem({ color, label }: { color: string; label: string }): React.JSX.Element {
  return (
    <span style={{ display: "flex", alignItems: "center", gap: "6px", fontSize: "13px" }}>
      <span
        style={{
          width: "12px",
          height: "12px",
          borderRadius: "50%",
          backgroundColor: color,
          display: "inline-block",
        }}
      />
      {label}
    </span>
  );
}

export function App(): React.JSX.Element {
  const [configLoaded, setConfigLoaded] = useState(false);
  const [configError, setConfigError] = useState<string | null>(null);

  useEffect(() => {
    loadConfig()
      .then(() => setConfigLoaded(true))
      .catch((err: Error) => setConfigError(err.message));
  }, []);

  if (configError) {
    return (
      <div style={{ padding: "40px", textAlign: "center", color: "#d91515" }}>
        <h2>Configuration Error</h2>
        <p>{configError}</p>
        <p>Ensure /config.json is available.</p>
      </div>
    );
  }

  if (!configLoaded) {
    return <div style={{ padding: "40px", textAlign: "center" }}>Initializing...</div>;
  }

  return (
    <TokenAuthProvider>
      <Dashboard />
    </TokenAuthProvider>
  );
}
