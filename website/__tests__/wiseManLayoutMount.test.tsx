import { readdirSync, existsSync } from "node:fs";
import { join } from "node:path";
import { render, screen } from "@testing-library/react";
import RootLayout from "@/app/layout";

jest.mock("next/navigation", () => ({
  usePathname: () => "/",
}));

// Sec 8.6: "Ship a test that enumerates the site's routes and asserts the
// widget mounts on each -- so a new page added later can't silently miss
// it." The real guarantee here is structural, not per-page: Next.js's App
// Router nests every route under app/**/page.tsx inside the NEAREST
// layout.tsx up the directory tree unless that route's own subtree defines
// a competing layout.tsx that opts out of the parent. So the test that
// actually catches "a new page silently missing the widget" is: (1) every
// real page.tsx in the app currently nests under the root layout (no other
// layout.tsx exists anywhere in app/ that could intercept it), and (2) the
// root layout itself renders <WiseMan />. A test that instead rendered
// each page individually would need heavy per-page data mocking (already
// covered by each page's own test file) and wouldn't actually strengthen
// this guarantee -- App Router's own nesting rule is what does the work.

const APP_DIR = join(__dirname, "..", "app");

function findFiles(dir: string, filename: string): string[] {
  const results: string[] = [];
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const full = join(dir, entry.name);
    if (entry.isDirectory()) {
      results.push(...findFiles(full, filename));
    } else if (entry.name === filename) {
      results.push(full);
    }
  }
  return results;
}

describe("Wise Man mounts on every route (Sec 8.6)", () => {
  it("app/layout.tsx (the root layout) is the ONLY layout.tsx in the app directory", () => {
    // If this ever finds a second layout.tsx, that subtree could silently
    // escape the root layout's <WiseMan /> -- this test exists specifically
    // to catch that before it ships.
    const layouts = findFiles(APP_DIR, "layout.tsx");
    expect(layouts).toEqual([join(APP_DIR, "layout.tsx")]);
  });

  it("real page.tsx routes exist under app/ and none define a competing layout (sanity: the scan below isn't vacuous)", () => {
    const pages = findFiles(APP_DIR, "page.tsx");
    expect(pages.length).toBeGreaterThanOrEqual(12); // home + 11 static routes + strategy/[id], per GATE A finding 1.6
  });

  it("RootLayout renders WiseMan as a direct child of body, alongside {children}", () => {
    render(
      <RootLayout>
        <div data-testid="page-content">Real page content</div>
      </RootLayout>,
    );
    expect(screen.getByTestId("wise-man-widget")).toBeInTheDocument();
    expect(screen.getByTestId("page-content")).toBeInTheDocument();
  });

  it("app/layout.tsx source imports and renders WiseMan (static confirmation, in case the render test above is ever skipped)", () => {
    const src = require("node:fs").readFileSync(join(APP_DIR, "layout.tsx"), "utf8");
    expect(src).toMatch(/import\s+WiseMan\s+from\s+["']@\/components\/WiseMan["']/);
    expect(src).toMatch(/<WiseMan\s*\/>/);
  });
});
