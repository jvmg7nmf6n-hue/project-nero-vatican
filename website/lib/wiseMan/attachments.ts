// Wise Man attachment validation (CC-1 directive v3, Sec 6). Validated by
// CONTENT SNIFFING (magic bytes), never by file extension or client-claimed
// MIME type -- a renamed .exe claiming to be image/png is rejected here
// because its actual bytes don't match a PNG signature, regardless of what
// the upload's declared type says.
//
// Real, documented limits as of 2026-08-08 (GATE A finding 1.8, dated
// against platform.claude.com/docs): 32MB max request body; PDFs capped at
// 100 pages for a <1M-token-context model (claude-haiku-4-5 is 200K
// context, so it's in the 100-page tier, not the 600-page tier); images
// max 10MB each (base64-encoded, Claude API direct), max 8000x8000px, and
// for a 200K-context model like Haiku, max 100 images per request.
//
// PDF page count is a BEST-EFFORT estimate (counting `/Type /Page` object
// occurrences in the raw bytes) -- exact for well-formed, non-compressed-
// xref PDFs, an honest approximation otherwise. Documented as a real
// limitation, not silently overclaimed as exact.

export type SniffedType = "image/png" | "image/jpeg" | "image/gif" | "image/webp" | "application/pdf" | null;

export function sniffMediaType(bytes: Buffer): SniffedType {
  if (bytes.length >= 8 && bytes.subarray(0, 8).equals(Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]))) {
    return "image/png";
  }
  if (bytes.length >= 3 && bytes[0] === 0xff && bytes[1] === 0xd8 && bytes[2] === 0xff) {
    return "image/jpeg";
  }
  if (bytes.length >= 6 && (bytes.subarray(0, 6).toString("ascii") === "GIF87a" || bytes.subarray(0, 6).toString("ascii") === "GIF89a")) {
    return "image/gif";
  }
  if (bytes.length >= 12 && bytes.subarray(0, 4).toString("ascii") === "RIFF" && bytes.subarray(8, 12).toString("ascii") === "WEBP") {
    return "image/webp";
  }
  if (bytes.length >= 5 && bytes.subarray(0, 5).toString("ascii") === "%PDF-") {
    return "application/pdf";
  }
  return null;
}

export const MAX_TOTAL_REQUEST_BYTES = 32 * 1024 * 1024; // 32MB, documented Claude API request cap
export const MAX_IMAGE_BYTES = 10 * 1024 * 1024; // 10MB per image, Claude API direct
export const MAX_ATTACHMENTS_PER_REQUEST = 5; // configurable-in-spirit, conservative default well under the 100-image API cap
export const MAX_PDF_PAGES = 100; // Haiku 4.5 is a 200K-context (<1M) model -- the 100-page tier, not 600

export function estimatePdfPageCount(bytes: Buffer): number {
  const text = bytes.toString("latin1");
  const matches = text.match(/\/Type\s*\/Page(?!s)/g);
  return matches ? matches.length : 0;
}

export interface AttachmentValidationResult {
  valid: boolean;
  reason?: string;
  sniffedType?: SniffedType;
}

export function validateAttachment(bytes: Buffer): AttachmentValidationResult {
  const sniffed = sniffMediaType(bytes);
  if (!sniffed) {
    return { valid: false, reason: "Unrecognized file type -- only PNG, JPEG, GIF, WebP, and PDF are supported." };
  }
  if (sniffed === "application/pdf") {
    if (bytes.length > MAX_TOTAL_REQUEST_BYTES) {
      return { valid: false, reason: "PDF exceeds the 32MB request size limit.", sniffedType: sniffed };
    }
    const pages = estimatePdfPageCount(bytes);
    if (pages > MAX_PDF_PAGES) {
      return { valid: false, reason: `PDF has an estimated ${pages} pages, over the ${MAX_PDF_PAGES}-page limit.`, sniffedType: sniffed };
    }
    return { valid: true, sniffedType: sniffed };
  }
  if (bytes.length > MAX_IMAGE_BYTES) {
    return { valid: false, reason: "Image exceeds the 10MB size limit.", sniffedType: sniffed };
  }
  return { valid: true, sniffedType: sniffed };
}

export interface AttachmentSetValidationResult {
  valid: boolean;
  reason?: string;
}

export function validateAttachmentSet(attachments: Buffer[]): AttachmentSetValidationResult {
  if (attachments.length > MAX_ATTACHMENTS_PER_REQUEST) {
    return { valid: false, reason: `Too many attachments -- max ${MAX_ATTACHMENTS_PER_REQUEST} per request.` };
  }
  const totalBytes = attachments.reduce((sum, a) => sum + a.length, 0);
  if (totalBytes > MAX_TOTAL_REQUEST_BYTES) {
    return { valid: false, reason: "Total attachment size exceeds the 32MB request limit." };
  }
  for (const a of attachments) {
    const result = validateAttachment(a);
    if (!result.valid) return { valid: false, reason: result.reason };
  }
  return { valid: true };
}
