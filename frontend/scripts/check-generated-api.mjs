// Drift gate for the OpenAPI-generated API boundary.
//
// Regenerates the TypeScript types from ../backend/openapi.json into a temp
// file via the isolated api-gen package and compares it with the committed
// generated.ts. Fails when they differ, so contract changes always travel
// through `pnpm generate:api`.

import { execFileSync } from "node:child_process";
import { readFileSync, rmSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const generatedPath = path.join(root, "src", "lib", "api", "generated.ts");
const openapiPath = path.join(root, "..", "backend", "openapi.json");
const generatorPath = path.join(root, "tools", "api-gen", "generate.mjs");
const probePath = path.join(root, ".generated-api-probe.ts");

try {
  execFileSync(process.execPath, [generatorPath, openapiPath, probePath], {
    cwd: root,
    stdio: "pipe",
  });
  const committed = readFileSync(generatedPath, "utf-8");
  const regenerated = readFileSync(probePath, "utf-8");
  if (committed !== regenerated) {
    console.error(
      "generated API types drifted from backend/openapi.json; run `pnpm generate:api` and commit the result.",
    );
    process.exit(1);
  }
  console.log("generated API types match backend/openapi.json");
} finally {
  try {
    rmSync(probePath, { force: true });
  } catch {
    // probe cleanup is best-effort
  }
}
