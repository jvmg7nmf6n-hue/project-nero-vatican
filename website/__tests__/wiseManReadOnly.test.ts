import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";

// Sec 8.7: Wise Man must not write to the Truth Ledger, must not trigger
// any strategy/backtest execution, and must not import strategy/backtest
// modules in a way that could execute anything -- it reads committed JSON
// only. Asserted here by static source scanning (Sec 8.7's own suggested
// fallback when a runtime test "isn't feasible" -- a runtime test would
// require actually wiring up nero_core in a Node/Jest environment, which
// this repo's website side has never done and shouldn't start doing for a
// read-only guarantee that's really a static, import-level property).

const WISE_MAN_DIR = join(__dirname, "..", "lib", "wiseMan");
const ROUTE_FILE = join(__dirname, "..", "app", "api", "wise-man", "route.ts");

function allSourceFiles(): string[] {
  const files = readdirSync(WISE_MAN_DIR)
    .filter((f) => f.endsWith(".ts"))
    .map((f) => join(WISE_MAN_DIR, f));
  files.push(ROUTE_FILE);
  return files;
}

describe("Wise Man is read-only w.r.t. the research pipeline (Sec 8.7)", () => {
  const files = allSourceFiles();

  it("scanned at least the expected core modules (sanity check the scan itself isn't vacuous)", () => {
    expect(files.length).toBeGreaterThanOrEqual(8);
  });

  it.each(files)("%s never IMPORTS from nero_core or any Python bridge (comments mentioning them for context are fine)", (file) => {
    const src = readFileSync(file, "utf8");
    // Deliberately scoped to actual import/require statements, not any
    // mention of the string -- several modules' doc comments legitimately
    // reference nero_core.eve.budget_ledger.py etc. by name to explain WHY
    // this code exists (e.g. "not Eve's own budget_ledger.py, because...").
    // A comment citing that module is documentation, not a dependency.
    expect(src).not.toMatch(/^\s*import[^\n]*nero_core/m);
    expect(src).not.toMatch(/require\([^)]*nero_core/);
    expect(src).not.toMatch(/from\s+["'][^"']*nero_core/);
    expect(src).not.toMatch(/child_process/);
    expect(src).not.toMatch(/execSync|spawn\(/);
  });

  it.each(files)("%s never calls a write to docs/site_data", (file) => {
    const src = readFileSync(file, "utf8");
    // Reading docs/site_data (via lib/data.ts's fetchers, which this
    // directory legitimately imports) is fine; writing to it is not --
    // this repo's own write path is atomic_write_json_list in Python, never
    // reachable from TypeScript at all, but assert no fs.writeFile* call
    // exists in this directory either, as a structural backstop.
    expect(src).not.toMatch(/writeFile|writeFileSync|fs\.write/);
  });

  it("no module in this directory imports Node's fs write APIs at all", () => {
    for (const file of files) {
      const src = readFileSync(file, "utf8");
      const fsImportMatch = src.match(/from ["']node:fs["']/);
      if (fsImportMatch) {
        // route.ts's own test file above uses readdirSync/readFileSync for
        // this very scan -- but production wiseMan/ modules should have no
        // reason to import fs at all (they read data via lib/data.ts).
        expect(file).toBe(ROUTE_FILE + "__should_never_match__"); // force failure if this ever fires
      }
    }
  });
});
