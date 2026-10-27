interface ValidationIssue {
  loc?: unknown;
  msg?: unknown;
}

function validationIssueMessage(issue: ValidationIssue): string | null {
  if (typeof issue.msg !== "string" || !issue.msg) return null;
  if (!Array.isArray(issue.loc)) return issue.msg;
  const path = issue.loc
    .filter((part) => part !== "body")
    .filter((part): part is string | number =>
      ["string", "number"].includes(typeof part),
    )
    .join(".");
  return path ? `${path}: ${issue.msg}` : issue.msg;
}

export function formatApiError(payload: unknown, fallback: string): string {
  if (!payload || typeof payload !== "object") return fallback;
  const detail = (payload as { detail?: unknown }).detail;
  if (typeof detail === "string" && detail) return detail;
  if (Array.isArray(detail)) {
    const messages = detail
      .map((issue) =>
        issue && typeof issue === "object"
          ? validationIssueMessage(issue as ValidationIssue)
          : null,
      )
      .filter((message): message is string => Boolean(message));
    if (messages.length) return messages.join("; ");
  }
  if (detail && typeof detail === "object") {
    const error = detail as ValidationIssue & {
      message?: unknown;
      errors?: unknown;
    };
    const message =
      typeof error.message === "string" && error.message
        ? error.message
        : validationIssueMessage(error);
    const errors = Array.isArray(error.errors)
      ? error.errors.filter(
          (item): item is string =>
            typeof item === "string" &&
            Boolean(item) &&
            !message?.includes(item),
        )
      : [];
    const messages = [...new Set([message, ...errors].filter(Boolean))];
    if (messages.length) return messages.join("; ");
  }
  return fallback;
}

export async function responseErrorMessage(
  response: Response,
  fallback: string,
): Promise<string> {
  const payload: unknown = await response.json().catch(() => null);
  return formatApiError(payload, fallback);
}
