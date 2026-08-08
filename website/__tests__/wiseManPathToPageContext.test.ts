import { resolvePathToPageContext } from "@/lib/wiseMan/pathToPageContext";

describe("resolvePathToPageContext (Sec 5, zero-extra-user-action page detection)", () => {
  it("maps / to home", () => {
    expect(resolvePathToPageContext("/")).toEqual({ page: "home" });
  });

  it("maps /strategy/[id] to strategy with the real id, URL-decoded", () => {
    expect(resolvePathToPageContext("/strategy/RC-CHANNEL_LOW_PULLBACK")).toEqual({
      page: "strategy",
      id: "RC-CHANNEL_LOW_PULLBACK",
    });
    expect(resolvePathToPageContext("/strategy/BTC%20TEST")).toEqual({ page: "strategy", id: "BTC TEST" });
  });

  it.each([
    "agents", "factory-loop", "graveyard", "heatmap", "lab", "ledger",
    "macro", "methodology", "pricing", "quant", "signals",
  ])("maps /%s to the matching page identifier", (route) => {
    expect(resolvePathToPageContext(`/${route}`)).toEqual({ page: route });
  });

  it("falls back to home for an unrecognized route rather than throwing", () => {
    expect(resolvePathToPageContext("/some-future-page-not-yet-wired-up")).toEqual({ page: "home" });
  });

  it("handles a trailing slash", () => {
    expect(resolvePathToPageContext("/agents/")).toEqual({ page: "agents" });
  });
});
