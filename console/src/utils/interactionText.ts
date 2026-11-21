import i18n from "i18next";

const CHINESE_MESSAGES: Record<string, string> = {
  "Invalid username or password": "用户名或密码不正确",
  "Account temporarily locked. Please try again later":
    "账号暂时锁定，请稍后重试或联系管理员解锁",
  "Too many login attempts. Please try again later":
    "登录尝试过于频繁，请稍后重试",
  "Too many requests. Please slow down": "操作过于频繁，请稍后重试",
  "Username already exists": "该用户名已存在，请使用其他用户名",
  "Not authenticated": "登录已失效，请重新登录",
  "Session renewed; retry the request": "登录已续期，请重试本次操作",
  "Login failed": "登录失败，请检查用户名和密码后重试",
  "Registration failed": "注册失败，请检查填写内容后重试",
  "Failed to check auth status": "暂时无法检查登录状态，请稍后重试",
  "Verification failed": "登录验证失败，请重新登录",
  "Failed to fetch": "网络连接失败，请检查网络后重试",
  "Network Error": "网络连接失败，请检查网络后重试",
  "Access denied": "权限不足，无法执行此操作",
  private_runtime_requires_owned_access:
    "此目录包含按用户隔离的运行数据，请从自己的对话或文件中心查看",
  Forbidden: "权限不足，无法执行此操作",
  "Not Found": "内容不存在或已被移除，请刷新后重试",
  "Operation failed": "操作未完成，请稍后重试",
};

export function usesChineseInteractions(): boolean {
  return (i18n.resolvedLanguage || i18n.language || "zh").startsWith("zh");
}

/** Keep backend diagnostics on the Error, never in a user-facing toast. */
export function interactionErrorText(raw: string, status = 0): string {
  if (!usesChineseInteractions()) return raw;
  const text = raw.trim().split(" - {")[0];
  if (CHINESE_MESSAGES[text]) return CHINESE_MESSAGES[text];
  if (/^Request timeout after /i.test(text))
    return "请求超时，请稍后重试；耗时任务可在任务列表中查看进度";
  if (/[\u3400-\u9fff]/.test(text) && !text.startsWith("{")) return text;
  if (status === 401) return "登录已失效，请重新登录";
  if (status === 403) return "权限不足，无法执行此操作";
  if (status === 404) return "内容不存在或已被移除，请刷新后重试";
  if (status === 409) return "内容已发生变化或存在冲突，请刷新后重试";
  if (status === 413) return "文件过大，请缩小文件后重试";
  if (status === 422 || status === 400)
    return "提交的信息有误，请检查填写内容后重试";
  if (status === 429) return "操作过于频繁，请稍后重试";
  if (status >= 500)
    return "服务暂时不可用，请稍后重试；如仍失败，请联系管理员";
  return "操作未完成，请稍后重试；如仍失败，请联系管理员";
}

export function errorDetailMessage(detail: unknown, fallback: string): string {
  if (typeof detail === "string" && detail) return detail;
  if (
    detail &&
    typeof detail === "object" &&
    "message" in detail &&
    typeof detail.message === "string"
  )
    return detail.message;
  return fallback;
}
