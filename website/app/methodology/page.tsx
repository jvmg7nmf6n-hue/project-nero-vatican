export const metadata = {
  title: "Methodology — Vatican",
};

export default function MethodologyPage() {
  return (
    <div className="prose-vatican max-w-2xl">
      <h1 className="font-serif text-3xl text-parchment">Methodology</h1>
      <p className="text-muted mt-2">
        Plain-language notes on how we decide whether a strategy is worth watching,
        worth trading on paper, or worth killing.
      </p>

      <section className="mt-8">
        <h2 className="font-serif text-xl text-parchment">Train/test split</h2>
        <p className="text-muted mt-2">
          Before we look at how a strategy performs, we split its historical data into
          two pieces: an earlier &quot;train&quot; period and a later, never-before-seen
          &quot;test&quot; period. We only decide the strategy&apos;s rules and parameters using
          the train period. The test period is checked afterward, once, to see whether
          the edge holds up on data the strategy never influenced. A strategy that only
          works on the train period and falls apart on the test period is not
          considered real.
        </p>
      </section>

      <section className="mt-8">
        <h2 className="font-serif text-xl text-parchment">Bootstrap confidence interval</h2>
        <p className="text-muted mt-2">
          A single average return number can be misleading — a handful of lucky trades
          can make a weak strategy look strong. To account for that, we resample the
          actual trade results thousands of times (with replacement) and recompute the
          average each time. This gives us a range — a confidence interval — for the
          true expectancy, instead of one fragile point estimate. If that range
          includes zero or goes negative, we don&apos;t treat the strategy as proven.
        </p>
      </section>

      <section className="mt-8">
        <h2 className="font-serif text-xl text-parchment">Random-entry baseline</h2>
        <p className="text-muted mt-2">
          Some of a strategy&apos;s apparent performance can come purely from its exit and
          position-sizing rules, not from the entry signal itself. To isolate the
          signal&apos;s actual contribution, we run a baseline version that enters trades
          at random (calibrated to the same number of trades) but keeps every other
          rule — stops, targets, sizing — identical. If the real strategy doesn&apos;t
          clearly beat its own random-entry baseline, the entry signal isn&apos;t adding
          value.
        </p>
      </section>

      <section className="mt-8">
        <h2 className="font-serif text-xl text-parchment">Grid-shift robustness</h2>
        <p className="mt-2 text-muted">
          Candle boundaries are an arbitrary human choice — a &quot;12-hour candle&quot; could
          just as easily start at a different hour of the day. A strategy that only
          works because of one specific candle alignment is fragile. We rebuild the
          same timeframe at several different UTC-hour offsets from the native 1-hour
          data and re-run the strategy on each shifted grid. A result that survives
          only on one exact alignment and disappears on the others is treated as noise,
          not edge.
        </p>
      </section>

      <section className="mt-8">
        <h2 className="font-serif text-xl text-parchment">Verdict categories</h2>
        <ul className="mt-2 space-y-3 text-muted">
          <li>
            <span className="text-teal font-medium">Survived</span> — beats its
            random-entry baseline, holds a positive expectancy confidence interval on
            both train and test periods, and has enough resolved trades (at least 20)
            to say so with any confidence.
          </li>
          <li>
            <span className="text-gold font-medium">Promising — watchlist</span> —
            shows a positive signal but hasn&apos;t yet cleared every bar above (too few
            trades, a confidence interval that touches zero, or robustness results that
            are mixed). Kept under live observation, not yet trusted.
          </li>
          <li>
            <span className="text-loss font-medium">Died</span> — fails to beat its
            random-entry baseline, or its expectancy confidence interval includes zero
            or goes negative, on real data. Retired to the{" "}
            <a href="/graveyard" className="underline">
              graveyard
            </a>
            .
          </li>
        </ul>
      </section>
    </div>
  );
}
