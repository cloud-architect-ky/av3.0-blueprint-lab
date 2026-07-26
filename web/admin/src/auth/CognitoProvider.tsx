import React, {
  createContext,
  useContext,
  useState,
  useEffect,
  useCallback,
  useMemo,
} from "react";
import { getConfig } from "../config";

interface AuthState {
  isAuthenticated: boolean;
  isLoading: boolean;
  idToken: string | null;
  accessToken: string | null;
  userEmail: string | null;
  error: string | null;
}

interface AuthContextValue extends AuthState {
  login: () => void;
  logout: () => void;
}

const AuthContext = createContext<AuthContextValue | null>(null);

function parseJwt(token: string): Record<string, unknown> {
  const base64Url = token.split(".")[1];
  const base64 = base64Url.replace(/-/g, "+").replace(/_/g, "/");
  const jsonPayload = decodeURIComponent(
    atob(base64)
      .split("")
      .map((c) => "%" + ("00" + c.charCodeAt(0).toString(16)).slice(-2))
      .join("")
  );
  return JSON.parse(jsonPayload);
}

function isTokenExpired(token: string): boolean {
  try {
    const payload = parseJwt(token);
    const exp = payload.exp as number;
    return Date.now() >= exp * 1000;
  } catch {
    return true;
  }
}

export function CognitoAuthProvider({
  children,
}: {
  children: React.ReactNode;
}) {
  const [state, setState] = useState<AuthState>({
    isAuthenticated: false,
    isLoading: true,
    idToken: null,
    accessToken: null,
    userEmail: null,
    error: null,
  });

  const buildAuthUrl = useCallback((responseType: string): string => {
    const config = getConfig();
    const params = new URLSearchParams({
      response_type: responseType,
      client_id: config.cognitoClientId,
      redirect_uri: config.cognitoRedirectUri,
      scope: "openid email profile",
    });
    return `${config.cognitoDomain}/oauth2/authorize?${params.toString()}`;
  }, []);

  const extractTokensFromHash = useCallback((): {
    idToken: string;
    accessToken: string;
  } | null => {
    const hash = window.location.hash.substring(1);
    if (!hash) return null;

    const params = new URLSearchParams(hash);
    const idToken = params.get("id_token");
    const accessToken = params.get("access_token");

    if (idToken && accessToken) {
      // Clear the hash from URL without reload
      window.history.replaceState(null, "", window.location.pathname);
      return { idToken, accessToken };
    }
    return null;
  }, []);

  useEffect(() => {
    // Check for tokens in URL hash (redirect callback)
    const tokens = extractTokensFromHash();
    if (tokens) {
      const payload = parseJwt(tokens.idToken);
      sessionStorage.setItem("av30_id_token", tokens.idToken);
      sessionStorage.setItem("av30_access_token", tokens.accessToken);
      setState({
        isAuthenticated: true,
        isLoading: false,
        idToken: tokens.idToken,
        accessToken: tokens.accessToken,
        userEmail: (payload.email as string) ?? null,
        error: null,
      });
      return;
    }

    // Check sessionStorage for existing session
    const storedIdToken = sessionStorage.getItem("av30_id_token");
    const storedAccessToken = sessionStorage.getItem("av30_access_token");
    if (storedIdToken && storedAccessToken && !isTokenExpired(storedIdToken)) {
      const payload = parseJwt(storedIdToken);
      setState({
        isAuthenticated: true,
        isLoading: false,
        idToken: storedIdToken,
        accessToken: storedAccessToken,
        userEmail: (payload.email as string) ?? null,
        error: null,
      });
      return;
    }

    // Clear stale tokens
    sessionStorage.removeItem("av30_id_token");
    sessionStorage.removeItem("av30_access_token");

    // Check for error in URL params
    const urlParams = new URLSearchParams(window.location.search);
    const error = urlParams.get("error_description") ?? urlParams.get("error");
    if (error) {
      setState({
        isAuthenticated: false,
        isLoading: false,
        idToken: null,
        accessToken: null,
        userEmail: null,
        error,
      });
      window.history.replaceState(null, "", window.location.pathname);
      return;
    }

    // No tokens found — user needs to log in
    setState((prev) => ({ ...prev, isLoading: false }));
  }, [extractTokensFromHash]);

  // Auto-refresh: if token expires while tab is open, force re-login
  useEffect(() => {
    if (!state.idToken) return;

    const payload = parseJwt(state.idToken);
    const exp = (payload.exp as number) * 1000;
    const msUntilExpiry = exp - Date.now() - 60_000; // Refresh 1 min early

    if (msUntilExpiry <= 0) {
      // Already expired
      setState({
        isAuthenticated: false,
        isLoading: false,
        idToken: null,
        accessToken: null,
        userEmail: null,
        error: "Session expired. Please log in again.",
      });
      return;
    }

    const timer = setTimeout(() => {
      // Silent re-auth via hidden iframe or redirect
      window.location.href = buildAuthUrl("token");
    }, msUntilExpiry);

    return () => clearTimeout(timer);
  }, [state.idToken, buildAuthUrl]);

  const login = useCallback(() => {
    window.location.href = buildAuthUrl("token");
  }, [buildAuthUrl]);

  const logout = useCallback(() => {
    const config = getConfig();
    sessionStorage.removeItem("av30_id_token");
    sessionStorage.removeItem("av30_access_token");
    setState({
      isAuthenticated: false,
      isLoading: false,
      idToken: null,
      accessToken: null,
      userEmail: null,
      error: null,
    });
    const params = new URLSearchParams({
      client_id: config.cognitoClientId,
      logout_uri: config.cognitoRedirectUri,
    });
    window.location.href = `${config.cognitoDomain}/logout?${params.toString()}`;
  }, []);

  const contextValue = useMemo(
    () => ({
      ...state,
      login,
      logout,
    }),
    [state, login, logout]
  );

  return (
    <AuthContext.Provider value={contextValue}>{children}</AuthContext.Provider>
  );
}

export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error("useAuth must be used within CognitoAuthProvider");
  }
  return context;
}
