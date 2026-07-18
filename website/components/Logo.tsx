import styles from "./Logo.module.css";

export interface LogoProps {
  className?: string;
  animated?: boolean;
}

// Circular gold ring with a parchment V monogram, a teal market line, and
// (when animated) an orbiting spark that flashes the V and pulses a ring
// burst once per 4s lap, plus an independent 3s market-line redraw loop.
export default function Logo({ className, animated = true }: LogoProps) {
  const cls = (name: keyof typeof styles) => (animated ? styles[name] : undefined);

  return (
    <svg
      viewBox="0 0 100 100"
      role="img"
      aria-label="Vatican"
      className={className}
      xmlns="http://www.w3.org/2000/svg"
    >
      <circle cx="50" cy="50" r="42" fill="none" stroke="#d4af37" strokeWidth="2" />
      <circle cx="50" cy="50" r="36" fill="none" stroke="#d4af37" strokeWidth="1" opacity="0.6" />

      <path
        d="M 22 66 L 34 58 L 44 62 L 56 44 L 68 50 L 80 30"
        fill="none"
        stroke="#2ec4b6"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
        pathLength={100}
        className={cls("marketLine")}
        opacity="0.85"
      />
      <circle r="2.2" fill="#2ec4b6" className={cls("marketDot")}>
        {animated ? (
          <animateMotion
            dur="3s"
            repeatCount="indefinite"
            path="M 22 66 L 34 58 L 44 62 L 56 44 L 68 50 L 80 30"
          />
        ) : null}
      </circle>

      <path
        d="M 32 30 L 50 70 L 68 30"
        fill="none"
        stroke="#e8e2d0"
        strokeWidth="7"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <path
        d="M 38 32 L 50 62 L 62 32"
        fill="none"
        stroke="#d4af37"
        strokeWidth="3"
        strokeLinecap="round"
        strokeLinejoin="round"
        className={cls("innerV")}
      />

      <circle cx="50" cy="8" r="4" fill="#d4af37" className={cls("burst")} />

      {animated ? (
        <g className={styles.orbit}>
          <circle cx="50" cy="8" r="2.4" fill="#d4af37" />
        </g>
      ) : (
        <circle cx="50" cy="8" r="2.4" fill="#d4af37" />
      )}
    </svg>
  );
}
