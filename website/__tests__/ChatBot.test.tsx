import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import ChatBot from "@/components/ChatBot";
import type { FaqEntry, StrategyChatContext } from "@/lib/types";

const FAQ: FaqEntry[] = [
  { question: "What does this strategy do?", answer: "It trades breakouts." },
  { question: "What is a stop loss?", answer: "A price that caps your risk." },
];

const CONTEXT: StrategyChatContext = {
  strategy_name: "BREAKOUT_MOMENTUM",
  asset: "GOLD",
  timeframe: "1week",
  mechanism: "x",
  verification_note: "y",
  win_rate: 0.6,
  current_signal: "WATCHING",
};

const originalFetch = global.fetch;

function openWidget() {
  fireEvent.click(screen.getByTestId("chatbot-toggle-open"));
}

beforeEach(() => {
  window.sessionStorage.clear();
});

afterEach(() => {
  global.fetch = originalFetch;
  jest.resetAllMocks();
});

describe("ChatBot collapse/expand", () => {
  it("starts collapsed, showing only the floating toggle button", () => {
    render(<ChatBot faqEntries={FAQ} strategyContext={CONTEXT} hasLiveChat={false} />);
    expect(screen.getByTestId("chatbot-toggle-open")).toBeInTheDocument();
    expect(screen.queryByTestId("chatbot-panel")).not.toBeInTheDocument();
  });

  it("expands to the full panel on click, and collapses again via the close button", () => {
    render(<ChatBot faqEntries={FAQ} strategyContext={CONTEXT} hasLiveChat={false} />);
    openWidget();
    expect(screen.getByTestId("chatbot-panel")).toBeInTheDocument();

    fireEvent.click(screen.getByTestId("chatbot-close"));
    expect(screen.queryByTestId("chatbot-panel")).not.toBeInTheDocument();
    expect(screen.getByTestId("chatbot-toggle-open")).toBeInTheDocument();
  });
});

describe("ChatBot FAQ chips (Part A)", () => {
  it("renders one chip per FAQ entry for this strategy family", () => {
    render(<ChatBot faqEntries={FAQ} strategyContext={CONTEXT} hasLiveChat={false} />);
    openWidget();
    expect(screen.getByTestId("faq-chip-0")).toHaveTextContent("What does this strategy do?");
    expect(screen.getByTestId("faq-chip-1")).toHaveTextContent("What is a stop loss?");
  });

  it("shows no answer until a chip is tapped", () => {
    render(<ChatBot faqEntries={FAQ} strategyContext={CONTEXT} hasLiveChat={false} />);
    openWidget();
    expect(screen.queryByTestId("faq-answer")).not.toBeInTheDocument();
  });

  it("shows the correct static answer when a chip is tapped", () => {
    render(<ChatBot faqEntries={FAQ} strategyContext={CONTEXT} hasLiveChat={false} />);
    openWidget();
    fireEvent.click(screen.getByTestId("faq-chip-0"));
    expect(screen.getByTestId("faq-answer")).toHaveTextContent("It trades breakouts.");
  });

  it("shows only one answer at a time -- tapping a second chip replaces the first answer", () => {
    render(<ChatBot faqEntries={FAQ} strategyContext={CONTEXT} hasLiveChat={false} />);
    openWidget();
    fireEvent.click(screen.getByTestId("faq-chip-0"));
    fireEvent.click(screen.getByTestId("faq-chip-1"));
    expect(screen.getAllByTestId("faq-answer")).toHaveLength(1);
    expect(screen.getByTestId("faq-answer")).toHaveTextContent("A price that caps your risk.");
  });

  it("collapses the answer when the same chip is tapped again", () => {
    render(<ChatBot faqEntries={FAQ} strategyContext={CONTEXT} hasLiveChat={false} />);
    openWidget();
    fireEvent.click(screen.getByTestId("faq-chip-0"));
    fireEvent.click(screen.getByTestId("faq-chip-0"));
    expect(screen.queryByTestId("faq-answer")).not.toBeInTheDocument();
  });

  it("never renders a text input in the FAQ-only section when hasLiveChat is false", () => {
    render(<ChatBot faqEntries={FAQ} strategyContext={CONTEXT} hasLiveChat={false} />);
    openWidget();
    expect(screen.queryByTestId("chat-input")).not.toBeInTheDocument();
    expect(screen.queryByTestId("chatbot-live-chat")).not.toBeInTheDocument();
  });
});

describe("ChatBot live chat (Part B)", () => {
  it("hides the live chat input entirely when hasLiveChat is false (missing API key)", () => {
    render(<ChatBot faqEntries={FAQ} strategyContext={CONTEXT} hasLiveChat={false} />);
    openWidget();
    expect(screen.queryByTestId("chat-send")).not.toBeInTheDocument();
  });

  it("shows the input, send button, and label when hasLiveChat is true", () => {
    render(<ChatBot faqEntries={FAQ} strategyContext={CONTEXT} hasLiveChat={true} />);
    openWidget();
    expect(screen.getByTestId("chat-input")).toBeInTheDocument();
    expect(screen.getByTestId("chat-send")).toBeInTheDocument();
    expect(screen.getByText("Ask anything in any language...")).toBeInTheDocument();
  });

  it("sends a message, shows a typing indicator, then renders the streamed reply as a bot bubble", async () => {
    const mockResponse = {
      ok: true,
      body: null,
      text: async () => "Bonjour!",
    } as unknown as Response;
    global.fetch = jest.fn().mockResolvedValue(mockResponse);

    render(<ChatBot faqEntries={FAQ} strategyContext={CONTEXT} hasLiveChat={true} />);
    openWidget();

    fireEvent.change(screen.getByTestId("chat-input"), { target: { value: "Bonjour" } });
    fireEvent.click(screen.getByTestId("chat-send"));

    const bubbles = screen.getAllByTestId("chat-bubble");
    expect(bubbles.some((b) => b.textContent === "Bonjour" && b.getAttribute("data-role") === "user")).toBe(true);

    await waitFor(() => {
      const updated = screen.getAllByTestId("chat-bubble");
      expect(updated.some((b) => b.textContent === "Bonjour!" && b.getAttribute("data-role") === "assistant")).toBe(
        true
      );
    });
    expect(screen.queryByTestId("typing-indicator")).not.toBeInTheDocument();
  });

  it("sends the correct request body: message, strategyContext, and conversation history", async () => {
    const mockFetch = jest.fn().mockResolvedValue({ ok: true, body: null, text: async () => "ok" } as unknown as Response);
    global.fetch = mockFetch;

    render(<ChatBot faqEntries={FAQ} strategyContext={CONTEXT} hasLiveChat={true} />);
    openWidget();
    fireEvent.change(screen.getByTestId("chat-input"), { target: { value: "hello" } });
    fireEvent.click(screen.getByTestId("chat-send"));

    await waitFor(() => expect(mockFetch).toHaveBeenCalledTimes(1));
    const [url, init] = mockFetch.mock.calls[0];
    expect(url).toBe("/api/chat");
    const body = JSON.parse(init.body);
    expect(body.message).toBe("hello");
    expect(body.strategyContext).toEqual(CONTEXT);
    expect(Array.isArray(body.history)).toBe(true);
  });

  it("caps the input at 500 characters", () => {
    render(<ChatBot faqEntries={FAQ} strategyContext={CONTEXT} hasLiveChat={true} />);
    openWidget();
    expect(screen.getByTestId("chat-input")).toHaveAttribute("maxLength", "500");
  });

  it("shows the generic fallback error message on a failed API call, never a technical error", async () => {
    global.fetch = jest.fn().mockResolvedValue({ ok: false, status: 502, body: null, text: async () => "" } as unknown as Response);

    render(<ChatBot faqEntries={FAQ} strategyContext={CONTEXT} hasLiveChat={true} />);
    openWidget();
    fireEvent.change(screen.getByTestId("chat-input"), { target: { value: "hello" } });
    fireEvent.click(screen.getByTestId("chat-send"));

    await waitFor(() => {
      expect(screen.getByTestId("chat-error")).toHaveTextContent(
        "AI is temporarily unavailable. Please check the FAQ above or try later."
      );
    });
  });

  it("shows the same generic fallback message when fetch throws (network failure)", async () => {
    global.fetch = jest.fn().mockRejectedValue(new Error("network down"));

    render(<ChatBot faqEntries={FAQ} strategyContext={CONTEXT} hasLiveChat={true} />);
    openWidget();
    fireEvent.change(screen.getByTestId("chat-input"), { target: { value: "hello" } });
    fireEvent.click(screen.getByTestId("chat-send"));

    await waitFor(() => {
      expect(screen.getByTestId("chat-error")).toHaveTextContent(/temporarily unavailable/);
    });
  });
});

describe("ChatBot rate limiting", () => {
  it("increments the sessionStorage message counter on each send", async () => {
    global.fetch = jest.fn().mockResolvedValue({ ok: true, body: null, text: async () => "ok" } as unknown as Response);

    render(<ChatBot faqEntries={FAQ} strategyContext={CONTEXT} hasLiveChat={true} />);
    openWidget();

    fireEvent.change(screen.getByTestId("chat-input"), { target: { value: "one" } });
    fireEvent.click(screen.getByTestId("chat-send"));
    await waitFor(() => expect(window.sessionStorage.getItem("vatican_chat_message_count")).toBe("1"));

    fireEvent.change(screen.getByTestId("chat-input"), { target: { value: "two" } });
    fireEvent.click(screen.getByTestId("chat-send"));
    await waitFor(() => expect(window.sessionStorage.getItem("vatican_chat_message_count")).toBe("2"));
  });

  it("blocks sending and shows the limit message once 10 messages have been sent this session", async () => {
    window.sessionStorage.setItem("vatican_chat_message_count", "10");
    const mockFetch = jest.fn();
    global.fetch = mockFetch;

    render(<ChatBot faqEntries={FAQ} strategyContext={CONTEXT} hasLiveChat={true} />);
    openWidget();
    fireEvent.change(screen.getByTestId("chat-input"), { target: { value: "one more" } });
    fireEvent.click(screen.getByTestId("chat-send"));

    expect(screen.getByTestId("chat-error")).toHaveTextContent(
      "You've reached today's limit. Come back tomorrow for more questions!"
    );
    expect(mockFetch).not.toHaveBeenCalled();
  });
});
