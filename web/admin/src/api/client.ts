import { getConfig } from "../config";

export interface User {
  userId: string;
  name: string;
  email: string;
  status: "active" | "idle" | "offline" | "provisioning";
  module: string;
  workspaceUrl: string;
  createdAt: string;
  // Durable participant token used to build the user dashboard link. Optional
  // because rows provisioned before this field was added won't have it.
  participantToken?: string;
  /**
   * Region of this user's SageMaker Studio domain. "" for rows provisioned before the
   * attribute existed. Read-only — see CreateUserRequest.region for why it cannot change.
   */
  region?: string;
}

export interface Session {
  sessionId: string;
  userId: string;
  userName: string;
  instanceType: string;
  status: "active" | "idle" | "offline";
  startedAt: string;
  gpuType: string | null;
  costToday: number;
  /** Region this session's instance actually runs in. "" for pre-existing rows. */
  region?: string;
}

export interface DailyCost {
  date: string;
  cost: number;
}

export interface BulkProvisionResult {
  succeeded: Array<{ email: string; name: string; workspaceUrl: string }>;
  failed: Array<{ email: string; name: string; error: string }>;
}

export interface CreateUserRequest {
  name: string;
  email: string;
  module?: string;
  /**
   * AWS region for this participant's SageMaker Studio domain. Optional; the backend
   * defaults to the control-plane region and rejects a region it does not manage.
   *
   * IMMUTABLE once provisioned: a UserProfile belongs to exactly one Domain and a
   * Domain is regional, so there is no "move this participant" operation — only
   * delete and re-provision. There is deliberately no PATCH route for it.
   */
  region?: string;
}

/** Body of DELETE /users/{id}. */
export interface DeleteUserResult {
  deleted: boolean;
  userId: string;
  filesDeleted: number;
  /**
   * OpenSearch Serverless teardown, which is deliberately best-effort so an AOSS
   * hiccup cannot block the SageMaker/S3/DynamoDB teardown. `complete: false` means a
   * collection or policy may still exist — and an orphaned AOSS collection bills at a
   * 2-OCU floor indefinitely, so this must be shown to the admin, not swallowed.
   * `reasons` carries AWS error CODES (e.g. "AccessDeniedException",
   * "ConflictException"); ConflictException is expected right after a delete, while
   * the collection is still DELETING, and the teardown.sh sweep reaps it later.
   *
   * "Not found" is deliberately NOT reported: most participants never reach M4, so no
   * collection or policy was ever created and every delete would come back
   * ResourceNotFoundException. Treating that as incomplete made this warning fire on
   * every single deletion, which trains admins to ignore it. So `complete: false` now
   * means a resource plausibly still exists.
   */
  aoss?: {
    collection: string;
    collectionFound: boolean;
    collectionDeleted: boolean;
    policiesDeleted: string[];
    complete: boolean;
    reasons: string[];
  };
}

class AdminApiClient {
  private getHeaders(idToken: string): HeadersInit {
    return {
      "Content-Type": "application/json",
      Authorization: `Bearer ${idToken}`,
    };
  }

  private getBaseUrl(): string {
    return getConfig().apiBaseUrl;
  }

  private async request<T>(
    method: string,
    path: string,
    idToken: string,
    body?: unknown
  ): Promise<T> {
    const url = `${this.getBaseUrl()}${path}`;
    const options: RequestInit = {
      method,
      headers: this.getHeaders(idToken),
    };

    if (body) {
      options.body = JSON.stringify(body);
    }

    const response = await fetch(url, options);

    if (!response.ok) {
      const errorBody = await response.text();
      let message: string;
      try {
        const parsed = JSON.parse(errorBody);
        message = parsed.message ?? parsed.error ?? errorBody;
      } catch {
        message = errorBody || `HTTP ${response.status}`;
      }
      throw new ApiError(message, response.status);
    }

    if (response.status === 204) {
      return undefined as T;
    }

    return response.json() as Promise<T>;
  }

  async createUser(
    idToken: string,
    data: CreateUserRequest
  ): Promise<User> {
    return this.request<User>("POST", "/users", idToken, data);
  }

  async bulkProvision(
    idToken: string,
    users: Array<{ name: string; email: string; module?: string; region?: string }>,
    region?: string
  ): Promise<BulkProvisionResult> {
    // `region` is the batch-wide default; a per-row region still wins. The backend
    // validates both against the managed set and rejects the whole upload on a typo,
    // rather than provisioning half a room into the wrong region.
    return this.request<BulkProvisionResult>(
      "POST",
      "/users/bulk",
      idToken,
      region ? { users, region } : { users }
    );
  }

  async listUsers(idToken: string): Promise<User[]> {
    const data = await this.request<User[] | { users: User[] }>("GET", "/users", idToken);
    return Array.isArray(data) ? data : (data?.users ?? []);
  }

  async listSessions(idToken: string): Promise<Session[]> {
    const data = await this.request<Session[] | { sessions: Session[] }>("GET", "/sessions", idToken);
    return Array.isArray(data) ? data : (data?.sessions ?? []);
  }

  async terminateSession(
    idToken: string,
    sessionId: string
  ): Promise<void> {
    return this.request<void>(
      "DELETE",
      `/sessions/${sessionId}`,
      idToken
    );
  }

  async getDailyCosts(idToken: string, days: number = 14): Promise<DailyCost[]> {
    const data = await this.request<DailyCost[] | { costs: DailyCost[] }>(
      "GET",
      `/costs/daily?days=${days}`,
      idToken
    );
    return Array.isArray(data) ? data : (data?.costs ?? []);
  }

  async resetWorkspace(
    idToken: string,
    userId: string
  ): Promise<void> {
    return this.request<void>(
      "POST",
      `/users/${userId}/reset`,
      idToken
    );
  }

  /**
   * Permanently delete a user and all their resources (SageMaker app/space/
   * profile, S3 workspace files, DynamoDB row). Backend: DELETE /users/{id}
   * (Cognito auth). Not reversible.
   *
   * Returns the body rather than void: the handler's OpenSearch Serverless teardown
   * is best-effort and reports `aoss.complete === false` when a collection may still
   * exist. An orphaned AOSS collection bills at a 2-OCU floor indefinitely, so that
   * signal must reach the admin instead of being thrown away.
   */
  async deleteUser(idToken: string, userId: string): Promise<DeleteUserResult> {
    return this.request<DeleteUserResult>("DELETE", `/users/${userId}`, idToken);
  }
}

export class ApiError extends Error {
  constructor(
    message: string,
    public readonly statusCode: number
  ) {
    super(message);
    this.name = "ApiError";
  }
}

export const apiClient = new AdminApiClient();
