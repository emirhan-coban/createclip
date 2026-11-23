import { describe, expect, it } from "vitest";
import { parseTime } from "./time";

describe("parseTime", () => {
  it("reads clock and spelled-out times", () => {
    expect(parseTime("1:44:50")).toBe(6290);
    expect(parseTime("44:50")).toBe(2690);
    expect(parseTime("45")).toBe(45);
    expect(parseTime(" 0:20:00 ")).toBe(1200);
    expect(parseTime("1sa44dk50sn")).toBe(6290);
    expect(parseTime("2dk")).toBe(120);
  });
  it("rejects anything else", () => {
    expect(parseTime("")).toBeNull();
    expect(parseTime("abc")).toBeNull();
    expect(parseTime("1:2:3:4")).toBeNull();
    expect(parseTime("-5")).toBeNull();
  });
});
