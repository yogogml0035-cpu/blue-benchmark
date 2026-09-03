import { describe, expect, it } from "vitest";
import type { QuestionListItem } from "./api";
import { applyListOps, filterBySearch, normalizeForSearch, sortByUpdatedDesc } from "./list-ops";

function item(partial: Partial<QuestionListItem>): QuestionListItem {
  return {
    id: "q1",
    scene_id: "s1",
    scene_name: "场景",
    client_case_id: "c1",
    title: "示例题目",
    status: "pending_review",
    rubric_criterion_count: null,
    criteria_confirmed: false,
    next_action: "review_criteria",
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    published_at: null,
    ...partial,
  };
}

describe("normalizeForSearch", () => {
  it("casefolds and NFC-normalizes", () => {
    expect(normalizeForSearch("ABC")).toBe("abc");
    // e + combining acute (NFD) folds to the same as precomposed é.
    expect(normalizeForSearch("e\u0301")).toBe(normalizeForSearch("\u00e9"));
  });
});

describe("filterBySearch", () => {
  const items = [item({ id: "a", title: "新闻稿改写" }), item({ id: "b", title: "会议纪要" })];

  it("matches by substring, case/accent-insensitive", () => {
    expect(filterBySearch(items, "新闻").map((i) => i.id)).toEqual(["a"]);
    expect(filterBySearch(items, "纪要").map((i) => i.id)).toEqual(["b"]);
  });

  it("returns all for empty query", () => {
    expect(filterBySearch(items, "  ")).toHaveLength(2);
  });

  it("returns empty when nothing matches", () => {
    expect(filterBySearch(items, "不存在")).toHaveLength(0);
  });
});

describe("sortByUpdatedDesc", () => {
  it("orders most recently updated first", () => {
    const items = [
      item({ id: "old", updated_at: "2026-01-01T00:00:00Z" }),
      item({ id: "new", updated_at: "2026-03-01T00:00:00Z" }),
      item({ id: "mid", updated_at: "2026-02-01T00:00:00Z" }),
    ];
    expect(sortByUpdatedDesc(items).map((i) => i.id)).toEqual(["new", "mid", "old"]);
  });

  it("breaks updated_at ties by id for stability", () => {
    const items = [
      item({ id: "b", updated_at: "2026-01-01T00:00:00Z" }),
      item({ id: "a", updated_at: "2026-01-01T00:00:00Z" }),
    ];
    expect(sortByUpdatedDesc(items).map((i) => i.id)).toEqual(["a", "b"]);
  });

  it("does not mutate the input", () => {
    const items = [
      item({ id: "b", updated_at: "2026-02-01T00:00:00Z" }),
      item({ id: "a", updated_at: "2026-01-01T00:00:00Z" }),
    ];
    sortByUpdatedDesc(items);
    expect(items.map((i) => i.id)).toEqual(["b", "a"]);
  });
});

describe("applyListOps", () => {
  const items = [
    item({ id: "a", title: "新闻稿改写", status: "published", updated_at: "2026-03-01T00:00:00Z" }),
    item({ id: "b", title: "会议纪要", status: "pending_review", updated_at: "2026-02-01T00:00:00Z" }),
    item({ id: "c", title: "新闻摘要", status: "pending_review", updated_at: "2026-01-01T00:00:00Z" }),
  ];

  it("combines search, status filter and sort", () => {
    const result = applyListOps(items, { query: "新闻", status: "pending_review" });
    expect(result.map((i) => i.id)).toEqual(["c"]);
  });

  it("filters by status only", () => {
    const result = applyListOps(items, { query: "", status: "published" });
    expect(result.map((i) => i.id)).toEqual(["a"]);
  });
});
