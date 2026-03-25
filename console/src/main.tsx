import { createRoot } from "react-dom/client";

if (typeof window !== "undefined") {
  const originalError = console.error;
  const originalWarn = console.warn;

  const shouldIgnoreConsoleNoise = (msg: string) => {
    return (
      msg.includes(":first-child") ||
      msg.includes("pseudo class") ||
      msg.includes("Warning: [antd: Tooltip] `overlayClassName` is deprecated") ||
      msg.includes("Warning: findDOMNode is deprecated and will be removed in the next major release") ||
      msg.includes(
        "Warning: forwardRef render functions accept exactly two parameters",
      ) ||
      msg.includes(
        'Warning: Each child in a list should have a unique "key" prop.',
      )
    );
  };

  console.error = function (...args: any[]) {
    const msg = args[0]?.toString() || "";
    if (shouldIgnoreConsoleNoise(msg)) {
      return;
    }
    originalError.apply(console, args);
  };

  console.warn = function (...args: any[]) {
    const msg = args[0]?.toString() || "";
    if (
      shouldIgnoreConsoleNoise(msg) ||
      msg.includes("potentially unsafe")
    ) {
      return;
    }
    originalWarn.apply(console, args);
  };
}

void (async () => {
  await import("./i18n");
  const { default: App } = await import("./App.tsx");
  createRoot(document.getElementById("root")!).render(<App />);
})();
