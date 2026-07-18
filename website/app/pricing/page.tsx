export const metadata = {
  title: "Pricing — Vatican",
};

interface Tier {
  name: string;
  price: string;
  description: string;
  features: string[];
}

const TIERS: Tier[] = [
  {
    name: "Free",
    price: "$0",
    description: "The public Truth Ledger, in full, forever.",
    features: [
      "Live council verdicts for every tracked strategy",
      "Full signal history in the Truth Ledger",
      "The graveyard of every retired strategy",
      "Methodology write-ups",
    ],
  },
  {
    name: "Paid",
    price: "TBD",
    description: "Faster access to new signals once the live-tracking phase ends.",
    features: [
      "Earlier signal notifications",
      "Per-asset watchlists",
      "Historical export tools",
    ],
  },
  {
    name: "Premium",
    price: "TBD",
    description: "For traders who want the full research process, not just the verdict.",
    features: [
      "Full strategy parameter visibility",
      "Priority access to new research batches",
      "Direct line for strategy questions",
    ],
  },
];

export default function PricingPage() {
  return (
    <div>
      <h1 className="font-serif text-3xl text-parchment">Pricing</h1>
      <p className="text-muted mt-2 max-w-2xl">
        Coming soon — currently in the live-tracking phase. Every tier below is
        informational only; nothing on this page is purchasable yet.
      </p>

      <div className="mt-8 grid gap-6 sm:grid-cols-3">
        {TIERS.map((tier) => (
          <div key={tier.name} className="rounded-lg border border-gold/30 bg-ink p-6">
            <h2 className="font-serif text-xl text-parchment">{tier.name}</h2>
            <div className="mt-1 text-2xl text-gold">{tier.price}</div>
            <p className="text-muted text-sm mt-2">{tier.description}</p>
            <ul className="mt-4 space-y-2 text-sm text-parchment">
              {tier.features.map((feature) => (
                <li key={feature}>&middot; {feature}</li>
              ))}
            </ul>
          </div>
        ))}
      </div>

      <p className="text-muted text-sm mt-8">
        Coming soon — currently in the live-tracking phase. No subscriptions are
        active or available for purchase today.
      </p>
    </div>
  );
}
