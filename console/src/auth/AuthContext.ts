import { createContext } from "react";

export interface AuthContextValue {
  token: string;
  isAuthenticated: boolean;
  userName: string;
  register: (
    phone: string,
    smsCode: string,
    countryCode?: string,
  ) => Promise<void>;
  sendSmsCode: (phone: string, countryCode?: string) => Promise<void>;
  logout: () => Promise<void>;
}

export const AuthContext = createContext<AuthContextValue | null>(null);
