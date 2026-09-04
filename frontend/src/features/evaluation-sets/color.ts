/**
 * Stable folder color derivation.
 *
 * The color is a pure function of the scene id — never persisted, never
 * randomized per render — so a folder keeps its color across reloads.
 */

const FOLDER_COLOR_VARS = [
  "var(--benchmark-folder-blue)",
  "var(--benchmark-folder-purple)",
  "var(--benchmark-folder-green)",
  "var(--benchmark-folder-yellow)",
  "var(--benchmark-folder-orange)",
  "var(--benchmark-folder-pink)",
  "var(--benchmark-folder-teal)",
  "var(--benchmark-folder-red)",
] as const;

/** FNV-1a — small, deterministic, and well-distributed for short ids. */
function fnv1a(value: string): number {
  let hash = 0x811c9dc5;
  for (let i = 0; i < value.length; i += 1) {
    hash ^= value.charCodeAt(i);
    hash = Math.imul(hash, 0x01000193) >>> 0;
  }
  return hash >>> 0;
}

export function sceneColorVar(sceneId: string): string {
  return FOLDER_COLOR_VARS[fnv1a(sceneId) % FOLDER_COLOR_VARS.length];
}
