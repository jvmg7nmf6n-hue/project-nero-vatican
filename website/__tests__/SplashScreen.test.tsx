import { act, fireEvent, render, screen } from "@testing-library/react";
import SplashScreen from "@/components/SplashScreen";

const SESSION_STORAGE_KEY = "vatican-splash-seen";

function mockMatchMedia(matches: boolean) {
  Object.defineProperty(window, "matchMedia", {
    writable: true,
    configurable: true,
    value: jest.fn().mockImplementation((query: string) => ({
      matches,
      media: query,
      onchange: null,
      addListener: jest.fn(),
      removeListener: jest.fn(),
      addEventListener: jest.fn(),
      removeEventListener: jest.fn(),
      dispatchEvent: jest.fn(),
    })),
  });
}

describe("SplashScreen", () => {
  beforeEach(() => {
    window.sessionStorage.clear();
    mockMatchMedia(false);
    jest.useFakeTimers();
  });

  afterEach(() => {
    jest.useRealTimers();
  });

  it("renders on first load of a session", () => {
    render(<SplashScreen />);
    expect(screen.getByTestId("splash-screen")).toBeInTheDocument();
  });

  it("marks the session as seen, so mounting again in the same session skips it", () => {
    const { unmount } = render(<SplashScreen />);
    expect(screen.getByTestId("splash-screen")).toBeInTheDocument();
    unmount();

    render(<SplashScreen />);
    expect(screen.queryByTestId("splash-screen")).not.toBeInTheDocument();
  });

  it("skips immediately when the sessionStorage flag is already present", () => {
    window.sessionStorage.setItem(SESSION_STORAGE_KEY, "true");
    render(<SplashScreen />);
    expect(screen.queryByTestId("splash-screen")).not.toBeInTheDocument();
  });

  it("stays fully visible for at least 4 seconds so the logo's animation actually plays", () => {
    render(<SplashScreen />);

    act(() => {
      jest.advanceTimersByTime(4000);
    });
    // Still present AND not yet fading -- a viewer must see the full ~4s+
    // lap of the orbiting spark / V-flash / burst, not a truncated fragment.
    const splash = screen.getByTestId("splash-screen");
    expect(splash).toBeInTheDocument();
    expect(splash).not.toHaveClass("opacity-0");
  });

  it("auto-dismisses (fades out, then unmounts) after the timeout elapses", () => {
    render(<SplashScreen />);
    expect(screen.getByTestId("splash-screen")).toBeInTheDocument();

    // Fires the auto-dismiss timer (starts the fade).
    act(() => {
      jest.advanceTimersByTime(4500);
    });
    expect(screen.getByTestId("splash-screen")).toHaveClass("opacity-0");

    // Fires the fade-out completion timer (removes it from the DOM).
    act(() => {
      jest.advanceTimersByTime(600);
    });
    expect(screen.queryByTestId("splash-screen")).not.toBeInTheDocument();
  });

  it("dismisses on click without waiting for the full auto-dismiss timeout", () => {
    render(<SplashScreen />);
    const splash = screen.getByTestId("splash-screen");

    act(() => {
      fireEvent.click(splash);
    });
    expect(splash).toHaveClass("opacity-0");

    act(() => {
      jest.advanceTimersByTime(600);
    });
    expect(screen.queryByTestId("splash-screen")).not.toBeInTheDocument();
  });

  it("dismisses on Enter/Space for keyboard users", () => {
    render(<SplashScreen />);
    const splash = screen.getByTestId("splash-screen");

    act(() => {
      fireEvent.keyDown(splash, { key: "Enter" });
    });
    act(() => {
      jest.advanceTimersByTime(600);
    });
    expect(screen.queryByTestId("splash-screen")).not.toBeInTheDocument();
  });

  it("respects prefers-reduced-motion: shows a static version that clears in under 1 second, with no fade", () => {
    mockMatchMedia(true);
    render(<SplashScreen />);
    const splash = screen.getByTestId("splash-screen");
    expect(splash).toBeInTheDocument();

    act(() => {
      jest.advanceTimersByTime(999);
    });
    expect(screen.queryByTestId("splash-screen")).not.toBeInTheDocument();
  });

  it("skips the fade transition on manual dismissal too when reduced motion is set", () => {
    mockMatchMedia(true);
    render(<SplashScreen />);
    const splash = screen.getByTestId("splash-screen");

    act(() => {
      fireEvent.click(splash);
    });
    // No opacity-0 fade step -- gone immediately, synchronously.
    expect(screen.queryByTestId("splash-screen")).not.toBeInTheDocument();
  });
});
