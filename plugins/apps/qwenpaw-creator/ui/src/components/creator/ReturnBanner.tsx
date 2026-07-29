import { useEffect, useRef } from "react";
import { usePathname } from "@/routing/navigation";
import { ArrowLeft, X } from "lucide-react";
import { useNavigationStore } from "@/store/navigationStore";
import { returnToSavedLocation } from "@/routing/locators";

/**
 * Return banner for cross-context jumps (design doc 3.2, iteration plan 1.5).
 * Appears at the top of the main workspace after a navigateToRef jump; when the
 * user navigates on their own (route change that doesn't match the controlled
 * jump target) the stack is cleared and the banner disappears.
 */
export default function ReturnBanner() {
  const pathname = usePathname();
  const stack = useNavigationStore((s) => s.stack);
  const expectedPath = useNavigationStore((s) => s.expectedPath);
  const clear = useNavigationStore((s) => s.clear);
  const lastPathRef = useRef(pathname);

  useEffect(() => {
    if (pathname === lastPathRef.current) return;
    lastPathRef.current = pathname;
    const state = useNavigationStore.getState();
    if (state.stack.length === 0) return;
    // Route changed but not via navigateToRef / the return banner → the user
    // navigated on their own, so clear the stack.
    if (state.expectedPath !== pathname) {
      state.clear();
    } else {
      state.setExpectedPath(null);
    }
  }, [pathname]);

  if (stack.length === 0) return null;
  // A controlled jump was just triggered but the route hasn't taken effect yet;
  // hold off rendering until it does (avoids a flicker).
  if (expectedPath && expectedPath !== pathname) return null;

  const top = stack[stack.length - 1];
  const sourceDescription =
    top.description === "决策中心" ? "审阅/决策" : top.description;

  return (
    <div className="flex items-center justify-between gap-3 border-b border-blue-200 bg-blue-50 px-4 py-2 text-sm text-blue-900 dark:border-blue-900/40 dark:bg-blue-950/40 dark:text-blue-200">
      <span className="min-w-0 truncate">
        已跳转到新上下文，来自{" "}
        <b className="font-semibold">{sourceDescription}</b>
      </span>
      <div className="flex shrink-0 items-center gap-2">
        <button
          type="button"
          onClick={() => returnToSavedLocation()}
          className="inline-flex items-center gap-1.5 rounded-md border border-blue-300 bg-white px-2.5 py-1 text-xs font-medium text-blue-700 transition-colors hover:bg-blue-100 dark:border-blue-800 dark:bg-transparent dark:text-blue-300 dark:hover:bg-blue-900/40"
        >
          <ArrowLeft className="h-3 w-3" />
          返回刚刚的位置
        </button>
        <button
          type="button"
          onClick={() => clear()}
          aria-label="关闭返回条"
          className="inline-flex h-6 w-6 items-center justify-center rounded-md text-blue-500 transition-colors hover:bg-blue-100 dark:hover:bg-blue-900/40"
        >
          <X className="h-3.5 w-3.5" />
        </button>
      </div>
    </div>
  );
}
