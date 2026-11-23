// The preview (this file's maths) and the export (autoshorts/editor.py) must agree. The expected numbers below come
// from editor.stack_heights / editor.cell_rect; if you change one side, change the other and these numbers.
import { describe, expect, it } from "vitest";
import { cellRect, defaultProject, plan, stackHeights } from "./layout";

const near = (a: number, b: number) => expect(a).toBeCloseTo(b, 2);

describe("layout geometry", () => {
  it("splits the canvas into even window heights, clamped to 25-75 %", () => {
    expect(stackHeights(0.5)).toEqual([960, 960]);
    expect(stackHeights(0.4)).toEqual([768, 1152]);
    expect(stackHeights(0.1)).toEqual([480, 1440]);
    expect(stackHeights(0.9)).toEqual([1440, 480]);
  });

  it("cellRect matches the Python cell_rect", () => {
    const a = cellRect(1920, 1080, { cx: 0.5, cy: 0.5, zoom: 1 }, 1080, 768);
    [a.x, a.y, a.w, a.h].forEach((v, i) => near(v, [200.625, 0, 1518.75, 1080][i]));
    const b = cellRect(1920, 1080, { cx: 0.9, cy: 0.85, zoom: 3 }, 1080, 768);
    [b.x, b.y, b.w, b.h].forEach((v, i) => near(v, [1413.75, 720, 506.25, 360][i]));
    const c = cellRect(1280, 720, { cx: 0.2, cy: 0.5, zoom: 1.5 }, 1080, 768);
    [c.x, c.y, c.w, c.h].forEach((v, i) => near(v, [0, 120, 675, 480][i]));
  });

  it("stack layers fill the canvas with the chosen split", () => {
    const p = defaultProject(10);
    p.layout.mode = "stack";
    p.layout.split = 0.4;
    const [top, bottom] = plan(p, 1920, 1080);
    expect(top.box).toEqual({ x: 0, y: 0, w: 1080, h: 768 });
    expect(bottom.box).toEqual({ x: 0, y: 768, w: 1080, h: 1152 });
    near(top.video.w, 1920 * (1080 / 1518.75));          // the whole frame, scaled so the window fills the box
  });
});
