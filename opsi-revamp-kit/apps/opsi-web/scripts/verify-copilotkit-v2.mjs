#!/usr/bin/env node
// Verifies (1) the installed @copilotkit/react-core exposes the V2 API this code relies on and
// (2) no source file uses the V1 API. Run from a directory where @copilotkit/react-core is installed:
//   node scripts/verify-copilotkit-v2.mjs [srcDir]
// Exit 1 on any problem. Run it in CI and after every CopilotKit upgrade.
import { readFileSync, readdirSync, statSync } from "node:fs";
import { createRequire } from "node:module";
import { join, resolve } from "node:path";

const require = createRequire(join(process.cwd(), "noop.js"));
const pkgJson = require("@copilotkit/react-core/package.json");
const REQUIRED = [
  "CopilotKitProvider", "CopilotChat", "CopilotSidebar", "CopilotPopup",
  "useAgent", "useAgentContext", "useFrontendTool", "useHumanInTheLoop", "useRenderTool", "useDefaultRenderTool",
];
let failed = false;

// 1) exports present in the V2 type declarations (no React runtime needed to check names)
const dtsPath = require.resolve("@copilotkit/react-core/package.json").replace(/package\.json$/, "dist/v2/index.d.mts");
const dts = readFileSync(dtsPath, "utf8");
for (const name of REQUIRED) {
  const ok = new RegExp(`\\b${name}\\b`).test(dts);
  console.log(`${ok ? "OK     " : "MISSING"} @copilotkit/react-core/v2 -> ${name}`);
  failed ||= !ok;
}
if (!pkgJson.exports?.["./v2"] || !pkgJson.exports?.["./v2/styles.css"]) {
  console.log("MISSING package export ./v2 or ./v2/styles.css");
  failed = true;
}

// 2) V1 usage in source
const srcDir = resolve(process.argv[2] ?? join(process.cwd(), "src"));
const V1_PATTERNS = [
  [/from\s+["']@copilotkit\/react-core["']/, "import from @copilotkit/react-core (V1 entry) - use /v2"],
  [/from\s+["']@copilotkit\/react-ui["']/, "@copilotkit/react-ui is the V1 UI package"],
  [/<CopilotKit[\s>]/, "<CopilotKit> V1 compatibility wrapper - use <CopilotKitProvider>"],
  [/\buseCopilotAction\b|\buseCopilotReadable\b|\buseCopilotChat\b/, "V1 hook"],
];
function walk(dir) {
  for (const entry of readdirSync(dir)) {
    const p = join(dir, entry);
    if (entry === "node_modules" || entry.startsWith(".")) continue;
    if (statSync(p).isDirectory()) walk(p);
    else if (/\.(t|j)sx?$/.test(entry)) {
      // strip comments so documentation that *mentions* V1 names is not flagged
      const text = readFileSync(p, "utf8").replace(/\/\*[\s\S]*?\*\//g, "").replace(/(^|[^:])\/\/.*$/gm, "$1");
      for (const [re, why] of V1_PATTERNS) {
        if (re.test(text)) {
          console.log(`V1 USAGE ${p}: ${why}`);
          failed = true;
        }
      }
    }
  }
}
walk(srcDir);
console.log(`@copilotkit/react-core@${pkgJson.version} - ${failed ? "FAILED" : "all V2 checks passed"}`);
process.exit(failed ? 1 : 0);
