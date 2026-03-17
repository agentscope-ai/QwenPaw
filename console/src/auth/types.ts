export type AuthMode = "login" | "register";

export interface AuthUser {
  name: string;
  userId: string | number | null;
  status: boolean | null;
  lyUser: unknown;
  grantSignRewardStatus: number;
}

export interface AuthState {
  token: string;
  user: AuthUser | null;
}


