// Draft answers rating column: latest average, average of the kept runs, and a question that fell since the previous run in red.
import * as React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { RatingCell, ratingTitle } from "../components/DraftLane";
import type { DraftRating } from "../types";
// eslint-disable-next-line @typescript-eslint/no-require-imports
const { it, expect } = (await import("vitest" as any)) as { it: (n: string, f: () => void) => void; expect: (a: unknown) => { toBe: (e: unknown) => void; toContain: (e: string) => void } };

const rating: DraftRating = {
  latest: 7.0, average: 7.5, worse: ["B1"],
  runs: [{ at: "2026-11-02T01:00:00Z", average: 8, blocks: { B1: 8, B2: 8 } }, { at: "2026-11-03T01:00:00Z", average: 7, blocks: { B1: 7, B2: 7.5 } }],
  reasons: { B1: "thin table", B2: "clear" },
};

it("shows the latest score, the average and marks the worse question red", () => {
  const html = renderToStaticMarkup(<RatingCell rating={rating} />);
  expect(html).toContain("7.0");
  expect(html).toContain("avg 7.5 of last 2");
  expect(html).toContain('<span class="draft-worse">B1 7.0</span>');
  expect(html.includes('<span class="">B2 7.5</span>')).toBe(true);
});

it("shows a dash when there is no rating and lists the runs in the hover text", () => {
  expect(renderToStaticMarkup(<RatingCell rating={null} />)).toBe("—");
  expect(ratingTitle(rating)).toContain("2026-11-02  avg 8");
  expect(ratingTitle(rating)).toContain("B1: thin table");
});

it("lists the suggested improvements in the hover text", () => {
  expect(ratingTitle({ ...rating, improve: { B1: ["restore the ClearSCADA row"] } })).toContain("B1: restore the ClearSCADA row");
});
