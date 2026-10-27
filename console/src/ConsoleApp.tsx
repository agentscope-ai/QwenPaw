import App from "./App";
import { installHostExternals } from "./plugins/hostExternals";
import "./layouts/registry/builtinMenu";
import "./layouts/registry/builtinRoutes";

installHostExternals();

export default App;
