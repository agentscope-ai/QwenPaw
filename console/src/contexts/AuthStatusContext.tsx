import { createContext, useContext, type ReactNode } from "react";

import type { AuthStatusResponse } from "../api/modules/auth";

const AuthStatusContext = createContext<AuthStatusResponse | null>(null);

export function AuthStatusProvider({
  value,
  children,
}: {
  value: AuthStatusResponse;
  children: ReactNode;
}) {
  return (
    <AuthStatusContext.Provider value={value}>
      {children}
    </AuthStatusContext.Provider>
  );
}

// eslint-disable-next-line react-refresh/only-export-components
export function useAuthStatus(): AuthStatusResponse {
  const status = useContext(AuthStatusContext);
  if (!status) {
    throw new Error("AuthStatusProvider is missing");
  }
  return status;
}
