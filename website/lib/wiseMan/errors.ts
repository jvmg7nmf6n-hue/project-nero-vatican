// Wise Man's bilingual, friendly, human-readable error copy (Sec 8.8, and
// the explicit human decision at GATE B kickoff: "Error messages --
// bilingual (English + Roman Urdu) for all user-facing failure states").
// No raw exception, no stack trace, no upstream error body ever reaches the
// browser -- every failure mode maps to one of these codes.

export type WiseManErrorCode =
  | "feature_disabled"
  | "storage_not_configured"
  | "origin_forbidden"
  | "invalid_request"
  | "input_too_long"
  | "too_many_turns"
  | "attachment_invalid"
  | "rate_limit_session"
  | "rate_limit_ip"
  | "rate_limit_attachment"
  | "budget_daily"
  | "budget_monthly"
  | "guardrail_blocked"
  | "guardrail_failed_closed"
  | "timeout"
  | "upstream_error";

export interface BilingualMessage {
  en: string;
  ur: string;
}

export const WISE_MAN_ERROR_MESSAGES: Record<WiseManErrorCode, BilingualMessage> = {
  feature_disabled: {
    en: "Wise Man is resting right now. Please check back later.",
    ur: "Wise Man abhi available nahi hai. Baraye meherbani thori dair baad try karein.",
  },
  storage_not_configured: {
    en: "Wise Man is resting right now. Please check back later.",
    ur: "Wise Man abhi available nahi hai. Baraye meherbani thori dair baad try karein.",
  },
  origin_forbidden: {
    en: "This request could not be verified. Please use the site directly.",
    ur: "Yeh request verify nahi ho saki. Baraye meherbani site seedha use karein.",
  },
  invalid_request: {
    en: "Sorry, that request wasn't formatted correctly.",
    ur: "Maazrat, yeh request sahi format mein nahi thi.",
  },
  input_too_long: {
    en: "That message is too long. Please shorten it and try again.",
    ur: "Yeh message bohat lamba hai. Baraye meherbani chota karke dobara koshish karein.",
  },
  too_many_turns: {
    en: "This conversation has reached its length limit. Please start a new one.",
    ur: "Yeh conversation apni limit tak pohanch gayi hai. Baraye meherbani nayi shuru karein.",
  },
  attachment_invalid: {
    en: "That file couldn't be used -- please check the format and size and try again.",
    ur: "Yeh file use nahi ho saki -- baraye meherbani format aur size check karke dobara koshish karein.",
  },
  rate_limit_session: {
    en: "You've sent a lot of messages recently. Please slow down and try again in a bit.",
    ur: "Aapne haal hi mein bohat saare messages bheje hain. Baraye meherbani thori dair baad dobara koshish karein.",
  },
  rate_limit_ip: {
    en: "Too many requests from this network right now. Please try again later.",
    ur: "Is network se abhi bohat zyada requests aa rahi hain. Baraye meherbani baad mein koshish karein.",
  },
  rate_limit_attachment: {
    en: "Too many file uploads recently. Please try again in a bit, or ask without an attachment.",
    ur: "Haal hi mein bohat zyada files upload hui hain. Thori dair baad koshish karein, ya bina attachment ke poochein.",
  },
  budget_daily: {
    en: "Wise Man has reached today's usage limit. Please check back tomorrow.",
    ur: "Wise Man aaj ki usage limit tak pohanch gaya hai. Baraye meherbani kal check karein.",
  },
  budget_monthly: {
    en: "Wise Man has reached this month's usage limit. Please check back later.",
    ur: "Wise Man is mahine ki usage limit tak pohanch gaya hai. Baraye meherbani baad mein check karein.",
  },
  guardrail_blocked: {
    en: "I can't help with personal financial decisions -- I only explain published methodology and site data, and I'm not a substitute for licensed financial advice.",
    ur: "Main personal financial decisions mein madad nahi kar sakta -- main sirf published methodology aur site data explain karta hoon, licensed financial advice ka substitute nahi hoon.",
  },
  guardrail_failed_closed: {
    en: "Sorry, I couldn't safely process that request. Please try again.",
    ur: "Maazrat, main is request ko safe tareeqe se process nahi kar saka. Baraye meherbani dobara koshish karein.",
  },
  timeout: {
    en: "That took too long to answer. Please try again.",
    ur: "Iska jawab dene mein bohat waqt lag gaya. Baraye meherbani dobara koshish karein.",
  },
  upstream_error: {
    en: "Something went wrong on our end. Please try again in a moment.",
    ur: "Humari taraf se kuch ghalat ho gaya. Baraye meherbani thori dair baad dobara koshish karein.",
  },
};

export function formatWiseManError(code: WiseManErrorCode): BilingualMessage {
  return WISE_MAN_ERROR_MESSAGES[code];
}
