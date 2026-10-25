// Fails loudly if the installed CopilotKit runtime / AG-UI client no longer export what server.ts uses.
// Run after every `npm install` or version bump:  npm run check:exports
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const expected = {
  "@copilotkit/runtime/v2": ["CopilotRuntime", "createCopilotRuntimeHandler"],
  "@copilotkit/runtime/v2/node": ["createCopilotNodeHandler", "createCopilotNodeListener"],
  "@ag-ui/client": ["HttpAgent"],
};
let failed = false;
for (const [mod, names] of Object.entries(expected)) {
  const exports = await import(mod);
  for (const name of names) {
    const ok = name in exports;
    console.log(`${ok ? "OK     " : "MISSING"} ${mod} -> ${name}`);
    failed ||= !ok;
  }
}
for (const pkg of ["@copilotkit/runtime", "@ag-ui/client"]) {
  console.log(`version ${pkg}@${require(`${pkg}/package.json`).version}`);
}
process.exit(failed ? 1 : 0);
