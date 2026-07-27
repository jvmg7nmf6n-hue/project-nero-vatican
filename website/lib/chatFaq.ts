import type { FaqEntry, StrategyDescription, StrategyRosterEntry, StrategyStats } from "./types";

const MAX_ANSWER_WORDS = 100;

// Every answer is built from real, already-public fields (description,
// win_rate, resolved_trades) -- never a per-family hardcoded script, so a
// strategy with no strategy_descriptions.json entry still gets an honest,
// non-fabricated answer instead of silently missing FAQ content.
function truncateToWords(text: string, maxWords: number): string {
  const words = text.trim().split(/\s+/);
  if (words.length <= maxWords) {
    return text.trim();
  }
  return `${words.slice(0, maxWords).join(" ")}...`;
}

function formatWinRatePercent(winRate: number | null): string {
  return winRate === null ? "not enough data yet" : `${(winRate * 100).toFixed(0)}%`;
}

function pluralTrades(n: number): string {
  return `${n} trade${n === 1 ? "" : "s"}`;
}

export const FAQ_QUESTIONS: readonly string[] = [
  "What does this strategy do?",
  "What should I do when signal comes?",
  "What is a stop loss?",
  "How much should I invest?",
  "Why does Vatican show losses too?",
  "Is profit guaranteed?",
  "How often does a signal come?",
];

export function buildFaqEntries(
  entry: Pick<StrategyRosterEntry, "name" | "asset" | "timeframe">,
  description: StrategyDescription | null,
  statsRow: Pick<StrategyStats, "win_rate" | "resolved_trades"> | null
): FaqEntry[] {
  const winRateText = formatWinRatePercent(statsRow?.win_rate ?? null);
  const resolvedTrades = statsRow?.resolved_trades ?? 0;

  const mechanismAnswer = description
    ? description.mechanism
    : `${entry.name} trades ${entry.asset} on the ${entry.timeframe} timeframe. A plain-language description hasn't been written up for this strategy yet — check the backtest evidence link on this page for the full research report.`;

  const answers: string[] = [
    mechanismAnswer,
    `A signal from ${entry.name} is research and education, not an instruction to trade. If you're studying or paper-trading it, note the entry price and decide your own stop-loss and position size before doing anything — Vatican never places real orders. For real money, always think it through yourself or talk to a licensed financial advisor in your country.`,
    `A stop-loss is the price where you'd exit a losing trade automatically, so a bad move can only cost you so much. For example, entering at $100 with a stop at $95 caps your risk at $5 per unit. Every Vatican strategy, including ${entry.name}, defines its own stop-loss as part of its tested logic — it's core risk management, not optional.`,
    `Vatican can't answer this — how much to invest depends on your own finances, goals, and risk tolerance, which we don't know. This project is paper-trading research and education only, never financial advice. For a real decision involving your own money, please consult a licensed financial advisor in your country.`,
    `Because hiding losses would make Vatican dishonest. Every signal ${entry.name} generates — wins AND losses — gets logged in the public Truth Ledger, so you see the real, unfiltered track record instead of a curated highlight reel. Its win rate so far (${winRateText}) only means something because every trade counts, good or bad.`,
    `No — nothing in trading is guaranteed, and Vatican never claims otherwise. ${entry.name}'s win rate on ${entry.asset}/${entry.timeframe} so far is ${winRateText}, based on ${pluralTrades(resolvedTrades)}, but past results never guarantee future performance. This is research and education, not financial advice.`,
    `${entry.name} only checks for a new signal once each ${entry.timeframe} candle closes on ${entry.asset}, and most candles produce no signal at all — it waits for its specific setup rather than trading constantly. So far it has completed ${pluralTrades(resolvedTrades)}. There's no fixed schedule — it only signals when its real conditions are met.`,
  ];

  return FAQ_QUESTIONS.map((question, index) => ({
    question,
    answer: truncateToWords(answers[index], MAX_ANSWER_WORDS),
  }));
}
