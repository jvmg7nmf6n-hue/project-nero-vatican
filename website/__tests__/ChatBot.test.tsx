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

    // Bug fix regression: the user's message and an assistant bubble must
    // both remain visible -- a prior version deleted the last message here.
    const bubbles = screen.getAllByTestId("chat-bubble");
    expect(bubbles.some((b) => b.getAttribute("data-role") === "user" && b.textContent === "hello")).toBe(true);
    expect(bubbles.some((b) => b.getAttribute("data-role") === "assistant")).toBe(true);
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

    // Bug fix regression: same as above -- nothing gets removed on a thrown
    // network error either.
    const bubbles = screen.getAllByTestId("chat-bubble");
    expect(bubbles.some((b) => b.getAttribute("data-role") === "user" && b.textContent === "hello")).toBe(true);
    expect(bubbles.some((b) => b.getAttribute("data-role") === "assistant")).toBe(true);
  });
});

describe("ChatBot conversation persistence (bug fix)", () => {
  const HISTORY_KEY = "vatican_chat_history_BREAKOUT_MOMENTUM_GOLD_1week";

  it("keeps all 3 user messages and all 3 AI responses visible after 3 full exchanges -- nothing disappears", async () => {
    let call = 0;
    global.fetch = jest.fn().mockImplementation(() => {
      call += 1;
      return Promise.resolve({ ok: true, body: null, text: async () => `Reply ${call}` } as unknown as Response);
    });

    render(<ChatBot faqEntries={FAQ} strategyContext={CONTEXT} hasLiveChat={true} />);
    openWidget();

    for (let i = 1; i <= 3; i += 1) {
      fireEvent.change(screen.getByTestId("chat-input"), { target: { value: `Message ${i}` } });
      fireEvent.click(screen.getByTestId("chat-send"));
      // eslint-disable-next-line no-await-in-loop
      await waitFor(() => {
        expect(screen.getAllByTestId("chat-bubble").some((b) => b.textContent === `Reply ${i}`)).toBe(true);
      });
    }

    const bubbles = screen.getAllByTestId("chat-bubble");
    expect(bubbles).toHaveLength(6);
    for (let i = 1; i <= 3; i += 1) {
      expect(
        bubbles.some((b) => b.textContent === `Message ${i}` && b.getAttribute("data-role") === "user")
      ).toBe(true);
      expect(
        bubbles.some((b) => b.textContent === `Reply ${i}` && b.getAttribute("data-role") === "assistant")
      ).toBe(true);
    }
  });

  it("keeps already-streamed text visible even if the connection errors right after -- no late deletion", async () => {
    const encoder = new TextEncoder();
    let readCount = 0;
    const reader = {
      read: jest.fn().mockImplementation(() => {
        readCount += 1;
        if (readCount === 1) {
          return Promise.resolve({ done: false, value: encoder.encode("Partial reply") });
        }
        return Promise.reject(new Error("connection reset"));
      }),
    };
    global.fetch = jest.fn().mockResolvedValue({ ok: true, body: { getReader: () => reader } } as unknown as Response);

    render(<ChatBot faqEntries={FAQ} strategyContext={CONTEXT} hasLiveChat={true} />);
    openWidget();
    fireEvent.change(screen.getByTestId("chat-input"), { target: { value: "hello" } });
    fireEvent.click(screen.getByTestId("chat-send"));

    await waitFor(() => {
      expect(screen.getAllByTestId("chat-bubble").some((b) => b.textContent === "Partial reply")).toBe(true);
    });
    // The error banner still shows (the connection did fail), but the reply
    // that already streamed in must not be wiped out by that failure.
    await waitFor(() => expect(screen.getByTestId("chat-error")).toBeInTheDocument());
    expect(screen.getAllByTestId("chat-bubble").some((b) => b.textContent === "Partial reply")).toBe(true);
  });

  it("hydrates a prior conversation from sessionStorage on mount", () => {
    window.sessionStorage.setItem(
      HISTORY_KEY,
      JSON.stringify([
        { role: "user", content: "earlier question" },
        { role: "assistant", content: "earlier answer" },
      ])
    );

    render(<ChatBot faqEntries={FAQ} strategyContext={CONTEXT} hasLiveChat={true} />);
    openWidget();

    const bubbles = screen.getAllByTestId("chat-bubble");
    expect(bubbles.some((b) => b.textContent === "earlier question")).toBe(true);
    expect(bubbles.some((b) => b.textContent === "earlier answer")).toBe(true);
  });

  it("writes the conversation to sessionStorage, keyed per strategy, after each exchange", async () => {
    global.fetch = jest.fn().mockResolvedValue({ ok: true, body: null, text: async () => "reply" } as unknown as Response);

    render(<ChatBot faqEntries={FAQ} strategyContext={CONTEXT} hasLiveChat={true} />);
    openWidget();
    fireEvent.change(screen.getByTestId("chat-input"), { target: { value: "hello" } });
    fireEvent.click(screen.getByTestId("chat-send"));

    await waitFor(() => {
      const stored = window.sessionStorage.getItem(HISTORY_KEY);
      expect(stored).not.toBeNull();
      expect(JSON.parse(stored as string)).toEqual([
        { role: "user", content: "hello" },
        { role: "assistant", content: "reply" },
      ]);
    });
  });

  it("keeps two strategies' conversations independent (different history keys)", () => {
    window.sessionStorage.setItem(HISTORY_KEY, JSON.stringify([{ role: "user", content: "gold question" }]));
    const otherContext: StrategyChatContext = { ...CONTEXT, strategy_name: "TREND_PULLBACK", asset: "BNB", timeframe: "12h" };

    render(<ChatBot faqEntries={FAQ} strategyContext={otherContext} hasLiveChat={true} />);
    openWidget();

    expect(screen.queryByText("gold question")).not.toBeInTheDocument();
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

  it("blocks sending and shows the limit message once the sanity ceiling (500) has been reached this session", async () => {
    window.sessionStorage.setItem("vatican_chat_message_count", "500");
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

  it("does not block sending at message counts well past the old 10-message limit (testing phase needs unrestricted exploration)", async () => {
    window.sessionStorage.setItem("vatican_chat_message_count", "100");
    const mockFetch = jest.fn().mockResolvedValue({ ok: true, body: null, text: async () => "ok" } as unknown as Response);
    global.fetch = mockFetch;

    render(<ChatBot faqEntries={FAQ} strategyContext={CONTEXT} hasLiveChat={true} />);
    openWidget();
    fireEvent.change(screen.getByTestId("chat-input"), { target: { value: "still going" } });
    fireEvent.click(screen.getByTestId("chat-send"));

    await waitFor(() => expect(mockFetch).toHaveBeenCalledTimes(1));
    expect(screen.queryByTestId("chat-error")).not.toBeInTheDocument();
  });
});

describe("ChatBot conversation history sent to the server", () => {
  const HISTORY_KEY = "vatican_chat_history_BREAKOUT_MOMENTUM_GOLD_1week";

  it("truncates the history sent to the server to HISTORY_LIMIT, even in a very long session", async () => {
    // Seed 20 prior messages -- well beyond HISTORY_LIMIT (12) -- into this
    // strategy's stored conversation, simulating a long-running session.
    const longHistory = Array.from({ length: 20 }, (_, i) => ({
      role: i % 2 === 0 ? "user" : "assistant",
      content: `msg${i}`,
    }));
    window.sessionStorage.setItem(HISTORY_KEY, JSON.stringify(longHistory));

    const mockFetch = jest.fn().mockResolvedValue({ ok: true, body: null, text: async () => "ok" } as unknown as Response);
    global.fetch = mockFetch;

    render(<ChatBot faqEntries={FAQ} strategyContext={CONTEXT} hasLiveChat={true} />);
    openWidget();
    fireEvent.change(screen.getByTestId("chat-input"), { target: { value: "new message" } });
    fireEvent.click(screen.getByTestId("chat-send"));

    await waitFor(() => expect(mockFetch).toHaveBeenCalledTimes(1));
    const [, init] = mockFetch.mock.calls[0];
    const body = JSON.parse(init.body);

    // Only the most recent HISTORY_LIMIT (12) of the 20 stored messages go out.
    expect(body.history).toHaveLength(12);
    expect(body.history[0]).toEqual({ role: "user", content: "msg8" });
    expect(body.history[body.history.length - 1]).toEqual({ role: "assistant", content: "msg19" });
  });
});
