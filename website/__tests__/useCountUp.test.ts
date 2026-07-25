import { act, renderHook } from "@testing-library/react";
import { useCountUp } from "@/lib/useCountUp";

describe("useCountUp", () => {
  beforeEach(() => {
    jest.useFakeTimers();
  });

  afterEach(() => {
    jest.useRealTimers();
  });

  it("starts at 0 for a positive target", () => {
    const { result } = renderHook(() => useCountUp(100));
    expect(result.current).toBe(0);
  });

  it("reaches the target once the animation duration elapses", () => {
    const { result } = renderHook(() => useCountUp(100));
    act(() => {
      jest.advanceTimersByTime(1500);
    });
    expect(result.current).toBe(100);
  });

  it("renders a zero target immediately with no animation", () => {
    const { result } = renderHook(() => useCountUp(0));
    expect(result.current).toBe(0);
  });
});
