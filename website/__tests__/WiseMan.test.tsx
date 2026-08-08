import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import WiseMan from "@/components/WiseMan";

jest.mock("next/navigation", () => ({
  usePathname: () => "/methodology",
}));

function mockFetchOnce(body: unknown, status = 200) {
  (global.fetch as jest.Mock).mockResolvedValueOnce({
    status,
    json: async () => body,
  });
}

beforeEach(() => {
  global.fetch = jest.fn();
  window.sessionStorage.clear();
  // No SpeechRecognition / speechSynthesis by default -- most browsers in
  // the real compatibility matrix (see docs/investigations/
  // wise_man_voice_compat.md) don't support both; graceful degradation is
  // the default case, not the exception.
  delete (window as unknown as Record<string, unknown>).SpeechRecognition;
  delete (window as unknown as Record<string, unknown>).webkitSpeechRecognition;
  delete (window as unknown as Record<string, unknown>).speechSynthesis;
});

describe("WiseMan widget (Sec 7, 8.6, 9)", () => {
  it("renders closed by default, as a floating button in the bottom-left", () => {
    render(<WiseMan />);
    const widget = screen.getByTestId("wise-man-widget");
    expect(widget.className).toContain("bottom-6");
    expect(widget.className).toContain("left-6");
    expect(screen.getByRole("button", { name: /open wise man/i })).toBeInTheDocument();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("opens on click and shows the persistent bilingual disclaimer", () => {
    render(<WiseMan />);
    fireEvent.click(screen.getByRole("button", { name: /open wise man/i }));
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(screen.getAllByText(/TODO\(human\)/).length).toBeGreaterThan(0); // EN persistent disclaimer placeholder
  });

  it("closes on Escape (Sec 9.4 keyboard accessibility)", () => {
    render(<WiseMan />);
    fireEvent.click(screen.getByRole("button", { name: /open wise man/i }));
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("closes on the close button", () => {
    render(<WiseMan />);
    fireEvent.click(screen.getByRole("button", { name: /open wise man/i }));
    fireEvent.click(screen.getByRole("button", { name: /close wise man/i }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("does not show a mic button when SpeechRecognition is unsupported (graceful degradation, never a dead button)", () => {
    render(<WiseMan />);
    fireEvent.click(screen.getByRole("button", { name: /open wise man/i }));
    expect(screen.queryByRole("button", { name: /voice input/i })).not.toBeInTheDocument();
  });

  it("does not show a speaker toggle when speechSynthesis is unsupported", () => {
    render(<WiseMan />);
    fireEvent.click(screen.getByRole("button", { name: /open wise man/i }));
    expect(screen.queryByRole("button", { name: /spoken replies/i })).not.toBeInTheDocument();
  });

  it("shows the mic button when SpeechRecognition IS supported", () => {
    (window as unknown as Record<string, unknown>).SpeechRecognition = function MockRecognition() {
      return { start: jest.fn(), stop: jest.fn() };
    };
    render(<WiseMan />);
    fireEvent.click(screen.getByRole("button", { name: /open wise man/i }));
    expect(screen.getByRole("button", { name: /start voice input/i })).toBeInTheDocument();
  });

  it("sends a typed message and renders the reply", async () => {
    mockFetchOnce({ reply: "Profit Factor is gross profit over gross loss." });
    render(<WiseMan />);
    fireEvent.click(screen.getByRole("button", { name: /open wise man/i }));
    fireEvent.change(screen.getByLabelText(/message wise man/i), { target: { value: "What is Profit Factor?" } });
    fireEvent.click(screen.getByRole("button", { name: "Send" }));

    await waitFor(() => expect(screen.getAllByText(/Profit Factor is gross profit/).length).toBeGreaterThan(0));
    expect(global.fetch).toHaveBeenCalledWith(
      "/api/wise-man",
      expect.objectContaining({ method: "POST", credentials: "include" }),
    );
    const [, init] = (global.fetch as jest.Mock).mock.calls[0];
    const body = JSON.parse(init.body);
    expect(body.pageContext).toEqual({ page: "methodology" });
  });

  it("shows the escalated disclaimer banner when the guardrail blocks a request", async () => {
    mockFetchOnce({ error: { en: "I can't help with that.", ur: "Main iss mein madad nahi kar sakta." } }, 200);
    render(<WiseMan />);
    fireEvent.click(screen.getByRole("button", { name: /open wise man/i }));
    fireEvent.change(screen.getByLabelText(/message wise man/i), { target: { value: "Should I buy BTC?" } });
    fireEvent.click(screen.getByRole("button", { name: "Send" }));

    await waitFor(() => expect(screen.getByRole("alert")).toBeInTheDocument());
  });

  it("persists conversation history to sessionStorage and restores it on remount", async () => {
    mockFetchOnce({ reply: "Answer one." });
    const { unmount } = render(<WiseMan />);
    fireEvent.click(screen.getByRole("button", { name: /open wise man/i }));
    fireEvent.change(screen.getByLabelText(/message wise man/i), { target: { value: "Question one" } });
    fireEvent.click(screen.getByRole("button", { name: "Send" }));
    await waitFor(() => expect(screen.getAllByText("Answer one.").length).toBeGreaterThan(0));
    unmount();

    render(<WiseMan />);
    fireEvent.click(screen.getByRole("button", { name: /open wise man/i }));
    expect(screen.getByText("Question one")).toBeInTheDocument();
    expect(screen.getByText("Answer one.")).toBeInTheDocument();
  });

  it("Send is disabled for an empty message", () => {
    render(<WiseMan />);
    fireEvent.click(screen.getByRole("button", { name: /open wise man/i }));
    expect(screen.getByRole("button", { name: "Send" })).toBeDisabled();
  });
});
