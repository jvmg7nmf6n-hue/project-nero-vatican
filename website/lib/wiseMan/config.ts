// Wise Man feature flag (Sec 8.1) + input caps (Sec 8.4) + origin allowlist (Sec 8.5).

/** Same parsing convention as EVE_ENABLED (nero_core.eve.config.is_enabled,
 * per .env.example's own comment) for consistency across this codebase:
 * unset/empty/anything other than 1/true/yes/on (case-insensitive) means
 * disabled. Defaults to disabled -- a brand-new, real-money-spending
 * feature should not go live silently on deploy. */
export function isWiseManEnabled(env: Partial<Record<string, string>> = process.env): boolean {
  const raw = (env.WISE_MAN_ENABLED ?? "").trim().toLowerCase();
  return raw === "1" || raw === "true" || raw === "yes" || raw === "on";
}

export const MAX_MESSAGE_CHARS = 2000;
export const MAX_TURNS_PER_CONVERSATION = 20;

/** Sec 8.5: the endpoint only serves requests from the site's own origins.
 * Populated from WISE_MAN_ALLOWED_ORIGINS (comma-separated) or falls back
 * to the production domain found in GATE A finding 1.5 (this repo's own
 * GitHub metadata .homepage field) plus localhost for dev. */
export function loadAllowedOrigins(env: Partial<Record<string, string>> = process.env): string[] {
  const configured = (env.WISE_MAN_ALLOWED_ORIGINS ?? "").split(",").map((s) => s.trim()).filter(Boolean);
  if (configured.length > 0) return configured;
  return ["https://project-nero-vatican.vercel.app", "http://localhost:3000"];
}

export function isAllowedOrigin(origin: string | null, allowed: string[]): boolean {
  if (!origin) return false;
  return allowed.includes(origin);
}
