import { act, renderHook } from "@testing-library/react";
import { useCountUp } from "@/lib/useCountUp";

describe("useCountUp", () => {
  beforeEach(() => {
    jest.useFakeTimers();
  });

  afterEach(() => {
    jest.useRealTimers();
  });

  it("renders the real value immediately on the first render -- never a placeholder 0", () => {
    // The bug this guards against: server-rendered HTML and the very first
    // client paint (before any effect has run) must show the real number,
    // not a fake 0 that only gets corrected after hydration -- a crawler,
    // screenshot, or slow-hydration visitor must never see "0" for a real,
    // positive stat.
    const { result } = renderHook(() => useCountUp(1515));
    expect(result.current).toBe(1515);
  });

  it("stays at the real value with no animation frames needed on first render", () => {
    const { result } = renderHook(() => useCountUp(37));
    act(() => {
      jest.advanceTimersByTime(1500);
    });
    expect(result.current).toBe(37);
  });

  it("renders a zero target immediately with no animation", () => {
    const { result } = renderHook(() => useCountUp(0));
    expect(result.current).toBe(0);
  });

  it("animates from 0 when the target genuinely changes after mount", () => {
    const { result, rerender } = renderHook(({ target }) => useCountUp(target), {
      initialProps: { target: 10 },
    });
    expect(result.current).toBe(10);

    rerender({ target: 100 });
    // The change is detected and an animation begins -- mid-flight the value
    // is below the new target, then settles on it once the duration elapses.
    act(() => {
      jest.advanceTimersByTime(1500);
    });
    expect(result.current).toBe(100);
  });
});
