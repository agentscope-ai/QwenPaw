import { toast } from "sonner";

type ToastContent =
  | string
  | { content: string; key?: string; duration?: number };

function resolveContent(content: ToastContent): string {
  if (typeof content === "string") return content;
  return content.content;
}

const messageAdapter = {
  success: (content: ToastContent) => toast.success(resolveContent(content)),
  error: (content: ToastContent) => toast.error(resolveContent(content)),
  warning: (content: ToastContent) => toast.warning(resolveContent(content)),
  info: (content: ToastContent) => toast.info(resolveContent(content)),
  loading: (content: ToastContent) => toast.loading(resolveContent(content)),
  destroy: (_key?: string) => toast.dismiss(),
  open: (config: { type?: string; content: string }) => {
    const msg = config.content;
    switch (config.type) {
      case "success":
        return toast.success(msg);
      case "error":
        return toast.error(msg);
      case "warning":
        return toast.warning(msg);
      default:
        return toast.info(msg);
    }
  },
};

/**
 * Drop-in replacement for antd App.useApp() message interface.
 * Routes all calls through sonner toast.
 */
export function useAppMessage() {
  return { message: messageAdapter };
}
