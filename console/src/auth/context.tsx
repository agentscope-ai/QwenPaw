import {
  useCallback,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { clearAuthState, loadAuthState, saveAuthState } from "./storage";
import {
  logoutRequest,
  registerBySmsCode,
  sendRegisterSmsCode,
} from "./service";
import {
  consoleApi,
  type AuthDebugEventPayload,
} from "../api/modules/console";
import type { AuthState } from "./types";
import { AuthContext, type AuthContextValue } from "./AuthContext";
import type { ProBoostAuthData } from "./proboost/types";

function maskPhone(phone: string) {
  const normalizedPhone = phone.trim();

  if (!normalizedPhone) {
    return "<empty>";
  }

  if (normalizedPhone.length <= 4) {
    return normalizedPhone;
  }

  return `${"*".repeat(Math.max(normalizedPhone.length - 4, 0))}${normalizedPhone.slice(-4)}`;
}

function getErrorMessage(error: unknown) {
  if (error instanceof Error) {
    return error.message;
  }

  return String(error);
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [authState, setAuthState] = useState<AuthState>(() => loadAuthState());

  const reportAuthDebugEvent = useCallback((payload: AuthDebugEventPayload) => {
    // Logging transport should never block auth flow.
    void consoleApi.reportAuthDebugEvent(payload).catch(() => undefined);
  }, []);

  const applyAuthSuccess = useCallback((data: ProBoostAuthData) => {
    const nextState: AuthState = {
      token: data.token,
      user: {
        name: data.name,
        userId: data.userId,
        status: data.status,
        lyUser: data.lyUser,
        grantSignRewardStatus: data.grantSignRewardStatus,
      },
    };

    setAuthState(nextState);
    saveAuthState(nextState);
  }, []);


  const register = useCallback(
    async (phone: string, smsCode: string, countryCode?: string) => {
      const maskedPhone = maskPhone(phone);

      console.debug("[auth] register start", {
        phone: maskedPhone,
        countryCode,
      });
      reportAuthDebugEvent({
        event: "register",
        stage: "start",
        phone: maskedPhone,
        countryCode,
      });

      try {
        const response = await registerBySmsCode(phone, smsCode, countryCode);

        applyAuthSuccess(response.data);
        console.debug("[auth] register success", {
          phone: maskedPhone,
          userId: response.data.userId,
          status: response.data.status,
        });
        reportAuthDebugEvent({
          event: "register",
          stage: "success",
          phone: maskedPhone,
          countryCode,
          userId: response.data.userId,
          status: response.data.status,
        });
      } catch (error) {
        console.debug("[auth] register failed", {
          phone: maskedPhone,
          countryCode,
          error: getErrorMessage(error),
        });
        reportAuthDebugEvent({
          event: "register",
          stage: "failed",
          phone: maskedPhone,
          countryCode,
          error: getErrorMessage(error),
        });
        throw error;
      }
    },
    [applyAuthSuccess, reportAuthDebugEvent],
  );

  const sendSmsCode = useCallback(
    async (phone: string, countryCode?: string) => {
      await sendRegisterSmsCode(phone, countryCode);
    },
    [],
  );

  const logout = useCallback(async () => {
    try {
      await logoutRequest();
    } catch {
      // Logout should still clear local auth state if backend call fails.
    }

    setAuthState({ token: "", user: null });
    clearAuthState();
  }, []);

  const value = useMemo<AuthContextValue>(
    () => ({
      token: authState.token,
      isAuthenticated: Boolean(authState.token),
      userName: authState.user?.name || "",
      register,
      sendSmsCode,
      logout,
    }),
    [authState.token, authState.user?.name, logout, register, sendSmsCode],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}





