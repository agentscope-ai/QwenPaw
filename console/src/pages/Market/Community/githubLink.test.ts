import { describe, expect, it } from "vitest";
import { isGithubRepoLink, normalizeGithubLink } from "./githubLink";

describe("githubLink", () => {
  it("accepts public GitHub repository URL shapes", () => {
    expect(isGithubRepoLink("https://github.com/owner/repo")).toBe(true);
    expect(isGithubRepoLink("github.com/owner/repo")).toBe(true);
    expect(isGithubRepoLink("http://www.github.com/o/r.git/")).toBe(true);
  });
  it("canonicalizes to https://github.com/{owner}/{repo}", () => {
    expect(normalizeGithubLink("github.com/owner/repo")).toBe(
      "https://github.com/owner/repo",
    );
    expect(normalizeGithubLink(" http://www.github.com/o/r.git/ ")).toBe(
      "https://github.com/o/r",
    );
    expect(normalizeGithubLink("https://github.com/owner/repo")).toBe(
      "https://github.com/owner/repo",
    );
  });
  it("collapses empty and non-GitHub values to an empty string", () => {
    expect(normalizeGithubLink("")).toBe("");
    expect(normalizeGithubLink("   ")).toBe("");
    expect(normalizeGithubLink("https://evil.example.com/phish")).toBe("");
    expect(isGithubRepoLink("https://evil.example.com/phish")).toBe(false);
    // A scheme-less lookalike must not survive as a same-origin href.
    expect(isGithubRepoLink("github.com.evil.example.com/o/r")).toBe(false);
    // Unicode homoglyphs stay out: JS \w is ASCII-only, and the backend
    // regex mirrors it via re.ASCII.
    expect(isGithubRepoLink("https://github.com/\u0430dmin/repo")).toBe(false);
    expect(isGithubRepoLink("g\u0131thub.com/o/r")).toBe(false);
  });
});
