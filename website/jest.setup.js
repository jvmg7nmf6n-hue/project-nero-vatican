import { TextDecoder, TextEncoder } from "node:util";

import "@testing-library/jest-dom";

// jest-environment-jsdom doesn't expose these globals (a known jsdom gap --
// they're WHATWG Encoding globals, not part of the DOM surface jsdom implements).
if (typeof global.TextEncoder === "undefined") {
  global.TextEncoder = TextEncoder;
}
if (typeof global.TextDecoder === "undefined") {
  global.TextDecoder = TextDecoder;
}
