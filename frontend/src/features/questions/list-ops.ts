/**
 * Pure list operations for the question list: case/Unicode-insensitive title
 * search, single-status filter, and stable most-recent-first ordering.
 * Kept free of React so they can be unit-tested directly.
 */

import type { QuestionListItem, QuestionStatus } from "./api";

/** Normalize for search: Unicode NFC + casefold so matching is accent/case-insensitive. */
export function normalizeForSearch(value: string): string {
  return value.normalize("NFC").toLowerCase();
}

export function filterBySearch(items: QuestionListItem[], query: string): QuestionListItem[] {
  const needle = normalizeForSearch(query.trim());
  if (!needle) return items;
  return items.filter((item) => normalizeForSearch(item.title).includes(needle));
}

export function filterByStatus(
  items: QuestionListItem[],
  status: QuestionStatus | null,
): QuestionListItem[] {
  if (!status) return items;
  return items.filter((item) => item.status === status);
}

/**
 * Most recently updated first; ties broken by id so the order is stable
 * regardless of the backend's own ordering.
 */
export function sortByUpdatedDesc(items: QuestionListItem[]): QuestionListItem[] {
  return [...items].sort((a, b) => {
    const ta = Date.parse(a.updated_at);
    const tb = Date.parse(b.updated_at);
    if (tb !== ta) return tb - ta;
    return a.id < b.id ? -1 : a.id > b.id ? 1 : 0;
  });
}

export function applyListOps(
  items: QuestionListItem[],
  opts: { query: string; status: QuestionStatus | null },
): QuestionListItem[] {
  return sortByUpdatedDesc(filterByStatus(filterBySearch(items, opts.query), opts.status));
}
