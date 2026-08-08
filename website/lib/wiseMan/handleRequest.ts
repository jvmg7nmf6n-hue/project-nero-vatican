// Wise Man's full request orchestration (CC-1 directive v3, Sec 5, 6, 8).
// Pure, dependency-injected, and testable without a real Next.js request --
// website/app/api/wise-man/route.ts is a thin wrapper that parses the
// Request, calls handleWiseManRequest(), and turns the result into a
// Response with the right status/cookie (same split chatApi.ts/route.ts
// already established for the existing chatbot).
//
// READ-ONLY W.R.T. THE RESEARCH PIPELINE (Sec 8.7): this module and every
// module it imports touches only website/lib/wiseMan/*, website/lib/data.ts
// (read-only fetchers), and website/lib/chatApi.ts's constants. Nothing
// here imports from nero_core, writes to docs/site_data/, or can trigger
// any strategy/backtest execution -- asserted directly in
// website/__tests__/wiseManReadOnly.test.ts via static source scanning.

import { ANTHROPIC_API_URL, ANTHROPIC_VERSION, GUARDRAIL_MODEL, checkGuardrail, WiseManContentBlock } from "./guardrail";
import { checkAndReserveBudget, type AtomicCounterStore, type BudgetConfig } from "./budget";
import { checkRateLimit, type RateLimitConfig } from "./rateLimit";
import { createSessionToken, verifySessionToken } from "./session";
import { validateAttachmentSet, type SniffedType } from "./attachments";
import { resolvePageContext, type PageContextIdentifier } from "./pageContext";
import { buildWiseManSystemBlocks } from "./systemPrompt";
import { MAX_MESSAGE_CHARS, MAX_TURNS_PER_CONVERSATION, isAllowedOrigin } from "./config";
import type { WiseManErrorCode } from "./errors";

export const GENERATION_MODEL = GUARDRAIL_MODEL; // claude-haiku-4-5 -- cost-consistent with the guardrail, see route docstring
export const GENERATION_MAX_TOKENS = 1024;
/** Rough per-request cost estimate for the budget RESERVATION step (cents)
 * -- reconciled against the real usage-derived cost after the call
 * completes. Deliberately conservative (over-, not under-, estimates) so
 * the reservation step never under-reserves. */
export const ESTIMATED_COST_CENTS = 1;

export interface WiseManHistoryTurn {
  role: "user" | "assistant";
  text: string;
}

export interface WiseManAttachmentInput {
  dataBase64: string;
}

export interface WiseManRequestInput {
  message: unknown;
  pageContext: unknown;
  attachments?: unknown;
  history?: unknown;
  sessionToken: string | null;
  ip: string;
  origin: string | null;
}

export interface WiseManDeps {
  apiKey: string;
  sessionSecret: string;
  store: AtomicCounterStore;
  budgetConfig: BudgetConfig;
  rateLimitConfig: RateLimitConfig;
  allowedOrigins: string[];
  enabled: boolean;
  fetchImpl?: typeof fetch;
  now?: Date;
}

export interface WiseManResult {
  httpStatus: number;
  reply?: string;
  errorCode?: WiseManErrorCode;
  newSessionToken?: string;
}

function isValidHistory(value: unknown): value is WiseManHistoryTurn[] {
  return (
    Array.isArray(value) &&
    value.every(
      (t) =>
        typeof t === "object" &&
        t !== null &&
        (t as { role?: unknown }).role !== undefined &&
        ((t as { role?: unknown }).role === "user" || (t as { role?: unknown }).role === "assistant") &&
        typeof (t as { text?: unknown }).text === "string",
    )
  );
}

function isValidPageContext(value: unknown): value is PageContextIdentifier {
  if (typeof value !== "object" || value === null) return false;
  const page = (value as { page?: unknown }).page;
  const validPages = [
    "home", "strategy", "agents", "factory-loop", "graveyard", "heatmap",
    "lab", "ledger", "macro", "methodology", "pricing", "quant", "signals",
  ];
  if (typeof page !== "string" || !validPages.includes(page)) return false;
  if (page === "strategy") return typeof (value as { id?: unknown }).id === "string";
  return true;
}

async function callGeneration(params: {
  systemBlocks: ReturnType<typeof buildWiseManSystemBlocks>;
  message: string;
  attachmentBlocks: WiseManContentBlock[];
  history: WiseManHistoryTurn[];
  apiKey: string;
  fetchImpl: typeof fetch;
}): Promise<string> {
  const messages = [
    ...params.history.map((t) => ({ role: t.role, content: t.text })),
    {
      role: "user",
      content: [
        ...params.attachmentBlocks.map((b) =>
          b.type === "text" ? { type: "text", text: b.text } : { type: b.type, source: { type: "base64", media_type: b.mediaType, data: b.dataBase64 } },
        ),
        { type: "text", text: params.message },
      ],
    },
  ];
  const response = await params.fetchImpl(ANTHROPIC_API_URL, {
    method: "POST",
    headers: { "Content-Type": "application/json", "x-api-key": params.apiKey, "anthropic-version": ANTHROPIC_VERSION },
    body: JSON.stringify({
      model: GENERATION_MODEL,
      max_tokens: GENERATION_MAX_TOKENS,
      system: params.systemBlocks,
      messages,
    }),
  });
  if (!response.ok) {
    throw new Error(`generation upstream returned ${response.status}`);
  }
  const payload = await response.json();
  const textBlocks = Array.isArray(payload?.content) ? payload.content.filter((b: { type?: string }) => b?.type === "text") : [];
  return textBlocks.map((b: { text?: string }) => b.text ?? "").join("");
}

export async function handleWiseManRequest(input: WiseManRequestInput, deps: WiseManDeps): Promise<WiseManResult> {
  const fetchImpl = deps.fetchImpl ?? fetch;
  const now = deps.now ?? new Date();

  if (!deps.enabled) {
    return { httpStatus: 503, errorCode: "feature_disabled" };
  }

  // Sec 8.5: origin restriction. A present, non-matching Origin is always
  // rejected. A missing Origin is not itself fatal (some legitimate
  // same-origin requests omit it) -- documented as a known, deliberate gap;
  // rate limiting and the spend cap are the primary backstops, not this check.
  if (input.origin && !isAllowedOrigin(input.origin, deps.allowedOrigins)) {
    return { httpStatus: 403, errorCode: "origin_forbidden" };
  }

  if (typeof input.message !== "string" || input.message.trim().length === 0) {
    return { httpStatus: 400, errorCode: "invalid_request" };
  }
  if (input.message.length > MAX_MESSAGE_CHARS) {
    return { httpStatus: 400, errorCode: "input_too_long" };
  }
  if (!isValidPageContext(input.pageContext)) {
    return { httpStatus: 400, errorCode: "invalid_request" };
  }
  const history = input.history === undefined ? [] : isValidHistory(input.history) ? input.history : null;
  if (history === null) {
    return { httpStatus: 400, errorCode: "invalid_request" };
  }
  if (history.length > MAX_TURNS_PER_CONVERSATION) {
    return { httpStatus: 400, errorCode: "too_many_turns" };
  }

  const rawAttachments = Array.isArray(input.attachments) ? input.attachments : [];
  const attachmentBuffers = rawAttachments
    .filter((a): a is WiseManAttachmentInput => typeof a === "object" && a !== null && typeof (a as { dataBase64?: unknown }).dataBase64 === "string")
    .map((a) => Buffer.from(a.dataBase64, "base64"));
  if (attachmentBuffers.length > 0) {
    const validation = validateAttachmentSet(attachmentBuffers);
    if (!validation.valid) {
      return { httpStatus: 400, errorCode: "attachment_invalid" };
    }
  }

  const session = verifySessionToken(input.sessionToken, deps.sessionSecret, now.getTime());
  const { session: newSession, token: newSessionToken } = session
    ? { session, token: null }
    : createSessionToken(deps.sessionSecret, now.getTime());
  const sessionId = session?.id ?? newSession.id;

  let rateLimitResult;
  try {
    rateLimitResult = await checkRateLimit({
      store: deps.store,
      config: deps.rateLimitConfig,
      sessionId,
      ip: input.ip,
      hasAttachment: attachmentBuffers.length > 0,
      now,
    });
  } catch {
    // FAIL CLOSED (Sec 8.8): a store error must never surface as a raw
    // exception -- same posture as the budget check just below.
    return { httpStatus: 503, errorCode: "upstream_error", newSessionToken: newSessionToken ?? undefined };
  }
  if (!rateLimitResult.allowed) {
    const code: WiseManErrorCode =
      rateLimitResult.reason === "ip_limit"
        ? "rate_limit_ip"
        : rateLimitResult.reason === "session_attachment_limit"
          ? "rate_limit_attachment"
          : "rate_limit_session";
    return { httpStatus: 429, errorCode: code, newSessionToken: newSessionToken ?? undefined };
  }

  let budgetResult;
  try {
    budgetResult = await checkAndReserveBudget({ store: deps.store, config: deps.budgetConfig, costCents: ESTIMATED_COST_CENTS, now });
  } catch {
    return { httpStatus: 503, errorCode: "upstream_error", newSessionToken: newSessionToken ?? undefined };
  }
  if (!budgetResult.allowed) {
    const code: WiseManErrorCode = budgetResult.reason === "monthly_cap_reached" ? "budget_monthly" : "budget_daily";
    return { httpStatus: 503, errorCode: code, newSessionToken: newSessionToken ?? undefined };
  }

  const attachmentBlocks: WiseManContentBlock[] = attachmentBuffers.map((buf) => {
    const sniffed = sniffToBlockType(buf);
    return sniffed === "application/pdf"
      ? { type: "document", mediaType: "application/pdf", dataBase64: buf.toString("base64") }
      : { type: "image", mediaType: sniffed ?? "image/png", dataBase64: buf.toString("base64") };
  });

  const inboundBlocks: WiseManContentBlock[] = [...attachmentBlocks, { type: "text", text: input.message }];
  const priorUserTurns = history.filter((t) => t.role === "user").map((t) => t.text);

  const inboundVerdict = await checkGuardrail({
    blocks: inboundBlocks,
    direction: "inbound",
    apiKey: deps.apiKey,
    priorUserTurns,
    fetchImpl,
  });
  if (inboundVerdict.blocked) {
    return {
      httpStatus: 200,
      errorCode: inboundVerdict.failedClosed ? "guardrail_failed_closed" : "guardrail_blocked",
      newSessionToken: newSessionToken ?? undefined,
    };
  }

  const pageContextText = await resolvePageContext(input.pageContext);
  const systemBlocks = buildWiseManSystemBlocks(pageContextText);

  let reply: string;
  try {
    reply = await callGeneration({ systemBlocks, message: input.message, attachmentBlocks, history, apiKey: deps.apiKey, fetchImpl });
  } catch {
    return { httpStatus: 502, errorCode: "upstream_error", newSessionToken: newSessionToken ?? undefined };
  }

  const outboundVerdict = await checkGuardrail({
    blocks: [{ type: "text", text: reply }],
    direction: "outbound",
    apiKey: deps.apiKey,
    fetchImpl,
  });
  if (outboundVerdict.blocked) {
    return {
      httpStatus: 200,
      errorCode: outboundVerdict.failedClosed ? "guardrail_failed_closed" : "guardrail_blocked",
      newSessionToken: newSessionToken ?? undefined,
    };
  }

  return { httpStatus: 200, reply, newSessionToken: newSessionToken ?? undefined };
}

function sniffToBlockType(buf: Buffer): SniffedType {
  // Re-sniffed here (cheap, deterministic) rather than threading the
  // earlier validateAttachmentSet's result through -- keeps this function
  // independently correct even if called from a path that skipped
  // validation (it never should, but this avoids a silent trust
  // assumption between two call sites).
  if (buf.subarray(0, 8).equals(Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]))) return "image/png";
  if (buf[0] === 0xff && buf[1] === 0xd8 && buf[2] === 0xff) return "image/jpeg";
  if (buf.subarray(0, 6).toString("ascii") === "GIF87a" || buf.subarray(0, 6).toString("ascii") === "GIF89a") return "image/gif";
  if (buf.subarray(0, 4).toString("ascii") === "RIFF" && buf.subarray(8, 12).toString("ascii") === "WEBP") return "image/webp";
  if (buf.subarray(0, 5).toString("ascii") === "%PDF-") return "application/pdf";
  return null;
}
