/** Called only for confirmed session creation/resolution, never navigation.
 * Keep another Agent's draft and existing destination preferences intact. */
export function migrateChatSessionPreferences(
  from: string,
  to: string,
  backend: string,
) {
  if (from === to) return;
  for (const prefix of ["approval_level-", `harness-approval-${backend}-`]) {
    const value = localStorage.getItem(prefix + from);
    if (value === null) continue;
    if (localStorage.getItem(prefix + to) === null)
      localStorage.setItem(prefix + to, value);
    localStorage.removeItem(prefix + from);
  }
}
