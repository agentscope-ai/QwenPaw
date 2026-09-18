import { EmbeddedDataConsole } from "./EmbeddedDataConsole";

/**
 * The embedded engine console owns the entire app surface: navigation,
 * branding, language, model setup (Agent Configuration), channels, and
 * the DataBridge service configuration. The shell only mounts it.
 */
export function App() {
  return (
    <div className="qwenpaw-data-app">
      <main className="qwenpaw-data-main">
        <EmbeddedDataConsole route="/console" active />
      </main>
    </div>
  );
}
