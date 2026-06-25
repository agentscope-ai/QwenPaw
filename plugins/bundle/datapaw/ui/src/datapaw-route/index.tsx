/**
 * DataPaw plugin in-host route shell.
 *
 * The host registers two exact-match routes via `QwenPaw.route.add`:
 *   - /plugin/datapaw/datapaw/data-connection
 *   - /plugin/datapaw/datapaw/data-connection/add
 * Both render this component (see patches/datapaw-navigation.ts). MainLayout
 * then mounts each registered path as <Route path={r.path} element={...} />
 * (no `/*` wildcard), so this component must NOT use a nested <Routes> with
 * absolute paths — react-router-dom v7 rejects that pattern. Instead we
 * inspect window.location.pathname directly and render the matching page.
 *
 * NOTE: do NOT import `@/App` here — that would pull the whole console fork
 * (Login/Settings/Control/Agent/...) into the plugin bundle.
 */
import DataConnectionPage from "@/pages/Datapaw/DataConnection";
import AddDataSourcePage from "@/pages/Datapaw/DataConnection/Add";
import { useDataConnectionPathname } from "@/pages/Datapaw/DataConnection/navigation";
import KGDocsPage from "@/pages/Datapaw/KGDocs";

const DATA_CONNECTION_BASE = "/plugin/datapaw/datapaw/data-connection";
const KG_DOCS_BASE = "/plugin/datapaw/datapaw/kg-docs";

export function DataPawRoute() {
  const pathname = useDataConnectionPathname();
  if (pathname === KG_DOCS_BASE) {
    return <KGDocsPage />;
  }
  if (pathname === `${DATA_CONNECTION_BASE}/add`) {
    return <AddDataSourcePage />;
  }
  return <DataConnectionPage />;
}
