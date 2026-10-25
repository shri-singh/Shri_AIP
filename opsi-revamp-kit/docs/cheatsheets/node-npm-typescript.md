# Node / npm / TypeScript

```bash
node -v; npm -v                                   # >= 20.18 / 10+
npm config set registry https://<internal-mirror>/  # corporate mirror
export SCARF_ANALYTICS=false                      # disable install-time analytics ping (CopilotKit dependency)
npm ci                                            # exact install from package-lock.json (commit the lockfile!)
npm i -E @copilotkit/react-core@1.79.1            # -E = exact pin, no ^
npm ls @ag-ui/client                              # must be ONE version (the runtime's dependency)
npm view @copilotkit/runtime@1.79.1 dependencies  # what the runtime expects
npm outdated
npm pack @copilotkit/runtime@1.79.1 && tar -xzf copilotkit-runtime-1.79.1.tgz   # read .d.ts without installing
npx tsc -p tsconfig.json --noEmit                 # type-check only
node --test "test/*.test.mjs"                     # Node's built-in test runner (glob, not a directory)
npm audit --omit=dev
```

## Kit checks
```bash
cd apps/copilot-runtime && npm ci && npm run build && npm test && npm run check:exports
cd apps/opsi-web && npm ci && npx tsc -p tsconfig.json --noEmit && node scripts/verify-copilotkit-v2.mjs src
```

## TypeScript settings that matter
- `"moduleResolution": "bundler"` (Vite/webpack 5 apps) or `"NodeNext"` (Node services) - both resolve package `exports`
  like `@copilotkit/react-core/v2`.
- `"jsx": "react-jsx"`, `"strict": true`, `"skipLibCheck": true` (vendor types).
- Duplicate-type errors across packages almost always mean two installed versions - `npm ls <pkg>`.
