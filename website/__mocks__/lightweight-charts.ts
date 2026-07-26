// Manual Jest mock for lightweight-charts, adjacent to node_modules -- Jest applies
// this automatically to every `import ... from "lightweight-charts"` in the test
// suite, with zero effect on the real production bundle (which always imports the
// real library). lightweight-charts renders to a <canvas>, which jsdom doesn't
// support meaningfully -- tests only need to verify OUR OWN code calls this API
// correctly, never real rendering.
//
// Deliberately exports ONLY `createChart` and `ColorType` -- the same names the real
// library exports -- rather than extra test-only helpers, so this file never risks
// diverging from the real package's type declarations that `tsconfig.json`'s broad
// `**/*.tsx` include would otherwise type-check test files against. Each createChart()
// call returns a FRESH mock chart/series pair (not one shared global instance), so
// tests can inspect `createChart.mock.results[0].value` / `.addCandlestickSeries.mock.
// results[0].value` without needing to manually clear nested mocks between renders.
export const ColorType = { Solid: "solid" };

export const createChart = jest.fn(() => ({
  addCandlestickSeries: jest.fn(() => ({
    setData: jest.fn(),
    setMarkers: jest.fn(),
  })),
  applyOptions: jest.fn(),
  remove: jest.fn(),
}));
