// Imported FIRST by server.ts so these defaults exist before @copilotkit/runtime is evaluated.
// The runtime ships an anonymous telemetry client (Segment); corporate deployments must opt out.
// Both variables are read by the runtime (verified in @copilotkit/runtime 1.79.1 dist).
process.env.COPILOTKIT_TELEMETRY_DISABLED ??= "true";
process.env.DO_NOT_TRACK ??= "1";

export const TELEMETRY_DISABLED = process.env.COPILOTKIT_TELEMETRY_DISABLED === "true";
