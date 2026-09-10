export async function connectRelayWithRetry<T>(
  connect: () => Promise<T>,
  attempts = 2,
): Promise<T> {
  let lastError: unknown;
  for (let attempt = 0; attempt < attempts; attempt += 1) {
    try {
      return await connect();
    } catch (error) {
      lastError = error;
    }
  }
  throw lastError instanceof Error ? lastError : new Error("安全中转连接失败");
}
