// OpenAPI -> TypeScript generation, isolated from the app's TypeScript 7.
//
// openapi-typescript 7.x builds its output through the TypeScript 5 compiler
// API, which the app's pinned TypeScript 7 no longer exposes. This package
// owns the generator and its TypeScript 5 runtime; the app keeps TypeScript 7
// for typechecking. Run from anywhere: paths are resolved against the
// frontend package root (frontend/).

import { mkdirSync, writeFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import openapiTS, { astToString } from "openapi-typescript";

const packageRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..");
const openapiPath = process.argv[2] ?? path.join(packageRoot, "..", "backend", "openapi.json");
const outputPath = process.argv[3] ?? path.join(packageRoot, "src", "lib", "api", "generated.ts");

// openapi-typescript v7 treats a bare string as a remote URL; local files
// must be handed over as file:// URLs.
const ast = await openapiTS(pathToFileURL(path.resolve(openapiPath)));
const banner = [
  "/* eslint-disable */",
  "// Generated from backend/openapi.json via `pnpm generate:api`. Do not edit.",
  "",
].join("\n");
mkdirSync(path.dirname(path.resolve(outputPath)), { recursive: true });
writeFileSync(path.resolve(outputPath), banner + astToString(ast));
console.log(`generated ${path.relative(process.cwd(), path.resolve(outputPath))}`);
