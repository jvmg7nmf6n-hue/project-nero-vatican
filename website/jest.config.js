const nextJest = require("next/jest");

// next/jest handles SWC transforms and CSS/module mocking automatically. It does
// NOT add a moduleNameMapper entry for tsconfig's "@/*" alias (verified against
// node_modules/next/dist/build/jest/jest.js) -- SWC rewrites plain `import ...
// from "@/x"` statements at transform time via jsConfig/resolvedBaseUrl, but a
// runtime string like `jest.mock("@/lib/data")` never goes through that and is
// resolved by Jest itself, which fails without the mapping below.
const createJestConfig = nextJest({ dir: "./" });

/** @type {import('jest').Config} */
const customJestConfig = {
  setupFilesAfterEnv: ["<rootDir>/jest.setup.js"],
  testEnvironment: "jest-environment-jsdom",
  moduleNameMapper: {
    "^@/(.*)$": "<rootDir>/$1",
  },
};

module.exports = createJestConfig(customJestConfig);
