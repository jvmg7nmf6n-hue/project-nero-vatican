import {
  sniffMediaType,
  validateAttachment,
  validateAttachmentSet,
  estimatePdfPageCount,
  MAX_IMAGE_BYTES,
  MAX_ATTACHMENTS_PER_REQUEST,
  MAX_PDF_PAGES,
} from "@/lib/wiseMan/attachments";

const PNG_HEADER = Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]);
const JPEG_HEADER = Buffer.from([0xff, 0xd8, 0xff, 0xe0]);
const GIF_HEADER = Buffer.from("GIF89a", "ascii");
const WEBP_HEADER = Buffer.concat([Buffer.from("RIFF", "ascii"), Buffer.from([0, 0, 0, 0]), Buffer.from("WEBP", "ascii")]);
const PDF_HEADER = Buffer.from("%PDF-1.4\n", "ascii");

function pdfWithNPages(n: number): Buffer {
  const pages = Array.from({ length: n }, () => "<< /Type /Page >>").join(" ");
  return Buffer.concat([PDF_HEADER, Buffer.from(`<< /Type /Pages /Kids [] /Count ${n} >> ${pages}`, "ascii")]);
}

describe("sniffMediaType (Sec 6 content sniffing, never trusts extension/claimed MIME type)", () => {
  it("detects PNG by magic bytes", () => {
    expect(sniffMediaType(Buffer.concat([PNG_HEADER, Buffer.alloc(10)]))).toBe("image/png");
  });
  it("detects JPEG by magic bytes", () => {
    expect(sniffMediaType(Buffer.concat([JPEG_HEADER, Buffer.alloc(10)]))).toBe("image/jpeg");
  });
  it("detects GIF by magic bytes", () => {
    expect(sniffMediaType(Buffer.concat([GIF_HEADER, Buffer.alloc(10)]))).toBe("image/gif");
  });
  it("detects WebP by magic bytes", () => {
    expect(sniffMediaType(Buffer.concat([WEBP_HEADER, Buffer.alloc(10)]))).toBe("image/webp");
  });
  it("detects PDF by magic bytes", () => {
    expect(sniffMediaType(Buffer.concat([PDF_HEADER, Buffer.alloc(10)]))).toBe("application/pdf");
  });
  it("returns null for an unrecognized type -- e.g. a renamed executable claiming to be an image", () => {
    const fakeExe = Buffer.from([0x4d, 0x5a, 0x90, 0x00]); // real MZ/PE header
    expect(sniffMediaType(fakeExe)).toBeNull();
  });
  it("returns null for empty/too-short input", () => {
    expect(sniffMediaType(Buffer.alloc(0))).toBeNull();
    expect(sniffMediaType(Buffer.from([0x89, 0x50]))).toBeNull();
  });
});

describe("estimatePdfPageCount", () => {
  it("counts /Type /Page objects, not /Type /Pages", () => {
    expect(estimatePdfPageCount(pdfWithNPages(3))).toBe(3);
  });
  it("does not confuse /Type /Pages (the tree root) with a real page", () => {
    const onlyRoot = Buffer.concat([PDF_HEADER, Buffer.from("<< /Type /Pages /Kids [] /Count 0 >>", "ascii")]);
    expect(estimatePdfPageCount(onlyRoot)).toBe(0);
  });
});

describe("validateAttachment (Sec 6 real, documented, server-side-enforced limits)", () => {
  it("accepts a well-formed PDF under the page cap", () => {
    const result = validateAttachment(pdfWithNPages(5));
    expect(result.valid).toBe(true);
    expect(result.sniffedType).toBe("application/pdf");
  });

  it("rejects a PDF over MAX_PDF_PAGES with a friendly reason, not a raw error", () => {
    const result = validateAttachment(pdfWithNPages(MAX_PDF_PAGES + 1));
    expect(result.valid).toBe(false);
    expect(result.reason).toContain(`${MAX_PDF_PAGES}-page limit`);
  });

  it("accepts a small image under MAX_IMAGE_BYTES", () => {
    const result = validateAttachment(Buffer.concat([PNG_HEADER, Buffer.alloc(100)]));
    expect(result.valid).toBe(true);
  });

  it("rejects an image over MAX_IMAGE_BYTES", () => {
    const oversized = Buffer.concat([PNG_HEADER, Buffer.alloc(MAX_IMAGE_BYTES + 1)]);
    const result = validateAttachment(oversized);
    expect(result.valid).toBe(false);
    expect(result.reason).toContain("10MB");
  });

  it("rejects an unrecognized type with a friendly message", () => {
    const result = validateAttachment(Buffer.from("not a real file"));
    expect(result.valid).toBe(false);
    expect(result.reason).toContain("PNG, JPEG, GIF, WebP, and PDF");
  });
});

describe("validateAttachmentSet (per-request caps)", () => {
  it("rejects more than MAX_ATTACHMENTS_PER_REQUEST attachments", () => {
    const many = Array.from({ length: MAX_ATTACHMENTS_PER_REQUEST + 1 }, () =>
      Buffer.concat([PNG_HEADER, Buffer.alloc(10)]),
    );
    const result = validateAttachmentSet(many);
    expect(result.valid).toBe(false);
    expect(result.reason).toContain(`max ${MAX_ATTACHMENTS_PER_REQUEST}`);
  });

  it("accepts a valid set under all caps", () => {
    const set = [Buffer.concat([PNG_HEADER, Buffer.alloc(10)]), pdfWithNPages(2)];
    expect(validateAttachmentSet(set).valid).toBe(true);
  });

  it("propagates a per-attachment validation failure with its reason", () => {
    const set = [Buffer.concat([PNG_HEADER, Buffer.alloc(10)]), Buffer.from("garbage")];
    const result = validateAttachmentSet(set);
    expect(result.valid).toBe(false);
    expect(result.reason).toContain("Unrecognized file type");
  });
});
