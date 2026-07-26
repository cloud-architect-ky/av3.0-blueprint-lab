import { useState, useEffect, useCallback, useContext } from "react";
import {
  Box,
  Button,
  CopyToClipboard,
  Header,
  Modal,
  Pagination,
  SpaceBetween,
  StatusIndicator,
  Table,
  TextFilter,
} from "@cloudscape-design/components";
import { apiClient, User } from "../api/client";
import { participantLink } from "../config";
import { useAuth } from "../auth/CognitoProvider";
import { FlashContext } from "../App";
import { ProvisionModal } from "../components/ProvisionModal";
import { BulkUploadModal } from "../components/BulkUploadModal";

const PAGE_SIZE = 20;

export function UsersPage() {
  const { idToken } = useAuth();
  const { addFlash } = useContext(FlashContext);
  const [users, setUsers] = useState<User[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [filterText, setFilterText] = useState("");
  const [currentPage, setCurrentPage] = useState(1);
  const [sortingColumn, setSortingColumn] = useState<string>("name");
  const [sortingDescending, setSortingDescending] = useState(false);
  const [showProvision, setShowProvision] = useState(false);
  const [showBulkUpload, setShowBulkUpload] = useState(false);
  const [resettingUserId, setResettingUserId] = useState<string | null>(null);
  const [confirmDeleteUser, setConfirmDeleteUser] = useState<User | null>(null);
  const [deletingUserId, setDeletingUserId] = useState<string | null>(null);

  const fetchUsers = useCallback(async () => {
    if (!idToken) return;
    try {
      const data = await apiClient.listUsers(idToken);
      setUsers(data);
    } catch (err) {
      const message = err instanceof Error ? err.message : "Unknown error";
      addFlash({ type: "error", content: `Failed to load users: ${message}` });
    } finally {
      setIsLoading(false);
    }
  }, [idToken, addFlash]);

  useEffect(() => {
    fetchUsers();
  }, [fetchUsers]);

  const handleReset = async (userId: string) => {
    if (!idToken) return;
    setResettingUserId(userId);
    try {
      await apiClient.resetWorkspace(idToken, userId);
      addFlash({ type: "success", content: "Workspace reset initiated." });
      await fetchUsers();
    } catch (err) {
      const message = err instanceof Error ? err.message : "Unknown error";
      addFlash({ type: "error", content: `Reset failed: ${message}` });
    } finally {
      setResettingUserId(null);
    }
  };

  const handleDelete = async (user: User) => {
    if (!idToken) return;
    setDeletingUserId(user.userId);
    try {
      await apiClient.deleteUser(idToken, user.userId);
      addFlash({ type: "success", content: `User ${user.name} deleted.` });
      setConfirmDeleteUser(null);
      await fetchUsers();
    } catch (err) {
      const message = err instanceof Error ? err.message : "Unknown error";
      addFlash({ type: "error", content: `Delete failed: ${message}` });
    } finally {
      setDeletingUserId(null);
    }
  };

  const statusType = (status: User["status"]) => {
    switch (status) {
      case "active":
        return "success";
      case "idle":
        return "warning";
      case "provisioning":
        return "in-progress";
      default:
        return "stopped";
    }
  };

  const filteredUsers = users.filter(
    (u) =>
      u.name.toLowerCase().includes(filterText.toLowerCase()) ||
      u.email.toLowerCase().includes(filterText.toLowerCase()) ||
      u.module.toLowerCase().includes(filterText.toLowerCase())
  );

  const sortedUsers = [...filteredUsers].sort((a, b) => {
    const key = sortingColumn as keyof User;
    const aVal = String(a[key] ?? "");
    const bVal = String(b[key] ?? "");
    const cmp = aVal.localeCompare(bVal);
    return sortingDescending ? -cmp : cmp;
  });

  const paginatedUsers = sortedUsers.slice(
    (currentPage - 1) * PAGE_SIZE,
    currentPage * PAGE_SIZE
  );

  return (
    <>
      <Table
        loading={isLoading}
        loadingText="Loading users..."
        items={paginatedUsers}
        trackBy="userId"
        sortingColumn={{ sortingField: sortingColumn }}
        sortingDescending={sortingDescending}
        onSortingChange={({ detail }) => {
          setSortingColumn(detail.sortingColumn.sortingField ?? "name");
          setSortingDescending(detail.isDescending ?? false);
        }}
        header={
          <Header
            counter={`(${filteredUsers.length})`}
            actions={
              <SpaceBetween direction="horizontal" size="xs">
                <Button onClick={() => setShowBulkUpload(true)}>
                  Bulk Upload
                </Button>
                <Button variant="primary" onClick={() => setShowProvision(true)}>
                  Add User
                </Button>
              </SpaceBetween>
            }
          >
            Users
          </Header>
        }
        filter={
          <TextFilter
            filteringText={filterText}
            onChange={({ detail }) => {
              setFilterText(detail.filteringText);
              setCurrentPage(1);
            }}
            filteringPlaceholder="Search by name, email, or module"
          />
        }
        pagination={
          <Pagination
            currentPageIndex={currentPage}
            pagesCount={Math.ceil(filteredUsers.length / PAGE_SIZE)}
            onChange={({ detail }) => setCurrentPage(detail.currentPageIndex)}
          />
        }
        columnDefinitions={[
          {
            id: "name",
            header: "Name",
            cell: (u) => u.name,
            sortingField: "name",
          },
          {
            id: "email",
            header: "Email",
            cell: (u) => u.email,
            sortingField: "email",
          },
          {
            id: "status",
            header: "Status",
            cell: (u) => (
              <StatusIndicator type={statusType(u.status)}>
                {u.status}
              </StatusIndicator>
            ),
            sortingField: "status",
          },
          {
            id: "module",
            header: "Module",
            cell: (u) => u.module || "-",
            sortingField: "module",
          },
          {
            id: "dashboardLink",
            header: "Dashboard Link",
            cell: (u) =>
              u.participantToken ? (
                <CopyToClipboard
                  copyButtonText="Copy link"
                  copySuccessText="Copied!"
                  copyErrorText="Failed to copy"
                  textToCopy={participantLink(u.userId, u.participantToken)}
                  variant="button"
                />
              ) : (
                "-"
              ),
          },
          {
            id: "actions",
            header: "Actions",
            cell: (u) => (
              <SpaceBetween direction="horizontal" size="xs">
                <Button
                  variant="inline-link"
                  loading={resettingUserId === u.userId}
                  disabled={deletingUserId === u.userId}
                  onClick={() => handleReset(u.userId)}
                >
                  Reset
                </Button>
                <Button
                  variant="inline-link"
                  loading={deletingUserId === u.userId}
                  disabled={resettingUserId === u.userId}
                  onClick={() => setConfirmDeleteUser(u)}
                >
                  Delete
                </Button>
              </SpaceBetween>
            ),
          },
        ]}
        empty={
          <Box textAlign="center" color="inherit">
            <b>No users</b>
            <Box variant="p" color="inherit">
              Add users to get started.
            </Box>
          </Box>
        }
      />

      <ProvisionModal
        visible={showProvision}
        onDismiss={() => setShowProvision(false)}
        onSuccess={fetchUsers}
      />
      <BulkUploadModal
        visible={showBulkUpload}
        onDismiss={() => setShowBulkUpload(false)}
        onSuccess={fetchUsers}
      />

      <Modal
        visible={confirmDeleteUser !== null}
        onDismiss={() => {
          if (deletingUserId === null) setConfirmDeleteUser(null);
        }}
        header="Delete user"
        footer={
          <Box float="right">
            <SpaceBetween direction="horizontal" size="xs">
              <Button
                variant="link"
                disabled={deletingUserId !== null}
                onClick={() => setConfirmDeleteUser(null)}
              >
                Cancel
              </Button>
              <Button
                variant="primary"
                loading={deletingUserId !== null}
                onClick={() => {
                  if (confirmDeleteUser) void handleDelete(confirmDeleteUser);
                }}
              >
                Delete
              </Button>
            </SpaceBetween>
          </Box>
        }
      >
        {confirmDeleteUser && (
          <SpaceBetween size="s">
            <Box>
              Permanently delete <strong>{confirmDeleteUser.name}</strong> (
              {confirmDeleteUser.email})?
            </Box>
            <Box color="text-status-error">
              This removes their SageMaker workspace, notebooks, and any generated
              output, and cannot be undone.
            </Box>
          </SpaceBetween>
        )}
      </Modal>
    </>
  );
}
