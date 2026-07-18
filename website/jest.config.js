const nextJest = require("next/jest");

// next/jest handles SWC transforms, CSS/module mocking, and reads tsconfig's "paths"
// (the "@/*" alias) automatically - no manual moduleNameMapper needed for that.
const createJestConfig = nextJest({ dir: "./" });

/** @type {import('jest').Config} */
const customJestConfig = {
  setupFilesAfterEnv: ["<rootDir>/jest.setup.js"],
  testEnvironment: "jest-environment-jsdom",
};

module.exports = createJestConfig(customJestConfig);
