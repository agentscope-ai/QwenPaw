import { config } from "zod/v4/core";

// Run before OpenUI creates its schemas. This bundled Zod instance belongs to
// the plugin; interpreted validation works with CSP without unsafe-eval.
config({ jitless: true });
