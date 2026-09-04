import type { Connection } from "../../api/types";
import { connectionKey } from "../../storage/connectionModel";

export function isValidPlatformEmail(value: string): boolean {
  return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value.trim());
}

export function platformConnectionKeysForLogout(
  connections: Connection[],
  activeConnection: Connection | null,
): string[] {
  const activeKey = activeConnection?.source === "platform"
    ? connectionKey(activeConnection)
    : null;
  const platformKeys = connections
    .filter((connection) => connection.source === "platform")
    .map(connectionKey);
  return [
    ...platformKeys.filter((key) => key !== activeKey),
    ...platformKeys.filter((key) => key === activeKey),
  ];
}

export function isValidPlatformPassword(value: string): boolean {
  return /^[A-Za-z]\S{7,}$/.test(value);
}

export function platformRegistrationError({
  account,
  confirmPassword,
  password,
  verifyCode,
}: {
  account: string;
  confirmPassword: string;
  password: string;
  verifyCode: string;
}): string | null {
  if (!isValidPlatformEmail(account)) return "请输入有效的邮箱地址";
  if (!isValidPlatformPassword(password)) {
    return "密码至少 8 位，且首位必须是字母";
  }
  if (password !== confirmPassword) return "两次输入的密码不一致";
  if (!verifyCode.trim()) return "请输入邮箱验证码";
  return null;
}
