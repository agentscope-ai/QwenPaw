export const CONNECTION_ATTEMPT_TIMEOUT_MS = 10_000;

export interface ConnectionAttempt {
  cancel: () => void;
  didTimeout: () => boolean;
  dispose: () => void;
  signal: AbortSignal;
}

export function startConnectionAttempt(
  timeoutMs = CONNECTION_ATTEMPT_TIMEOUT_MS,
): ConnectionAttempt {
  const controller = new AbortController();
  let timedOut = false;
  const timer = setTimeout(() => {
    timedOut = true;
    controller.abort();
  }, timeoutMs);
  return {
    cancel: () => controller.abort(),
    didTimeout: () => timedOut,
    dispose: () => clearTimeout(timer),
    signal: controller.signal,
  };
}

export function connectionTimeoutMessage(rawUrl: string): string {
  const host = parseHost(rawUrl);
  if (host === "127.0.0.1" || host === "localhost" || host === "::1") {
    return "连接超时。手机上的 127.0.0.1 指向手机自身；Android 模拟器请使用 10.0.2.2，真机请填写电脑的局域网 IP。";
  }
  return "连接超时。请确认手机与 QwenPaw 在同一网络、地址和端口正确，并使用 --host 0.0.0.0 启动服务。";
}

function parseHost(rawUrl: string): string {
  try {
    return new URL(rawUrl.trim()).hostname.toLowerCase();
  } catch {
    return "";
  }
}
