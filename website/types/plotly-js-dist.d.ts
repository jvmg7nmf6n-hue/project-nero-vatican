// `plotly.js-dist` ships no bundled type declarations, and `@types/plotly.js`
// (its declarations are correct and match plotly.js-dist's runtime API 1:1 --
// plotly.js-dist is literally plotly.js pre-bundled for browser use with no
// API differences) declares the module name "plotly.js", not
// "plotly.js-dist". This shim re-exports those real types under the actual
// import specifier used in components/Correlation3DSurface.tsx.
declare module "plotly.js-dist" {
  import * as Plotly from "plotly.js";
  export default Plotly;
}
