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

// jest-environment-jsdom doesn't implement ResizeObserver (also not part of the
// DOM surface jsdom implements) -- @xyflow/react (FactoryLoopDiagram, CC-1 Part
// D3) requires it to measure its container on mount. A minimal no-op stand-in is
// enough for tests: they only need the component to mount without throwing, not
// real resize-driven layout (jsdom has no real layout engine to observe anyway).
if (typeof global.ResizeObserver === "undefined") {
  global.ResizeObserver = class ResizeObserver {
    observe() {}
    unobserve() {}
    disconnect() {}
  };
}
