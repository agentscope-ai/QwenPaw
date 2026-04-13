# Open Source & Contribution

QwenPaw is open source. The project repository is hosted on GitHub:

**https://github.com/agentscope-ai/QwenPaw**

---

## 🎯 How to Contribute

Thank you for your interest in QwenPaw, and we warmly welcome all forms of contribution! To keep collaboration smooth and maintain quality, please follow these guidelines.

### 1. Check Existing Plans and Issues

Before starting:

- **Check [Open Issues](https://github.com/agentscope-ai/QwenPaw/issues)** and the [Roadmap](/docs/roadmap)
- **If a related issue exists** and is open or unassigned: comment to say you want to work on it to avoid duplicate effort
- **If no related issue exists**: open a new issue describing your proposal. The maintainers will respond and help align with the project direction

### 2. Commit Message Format

We follow the [Conventional Commits](https://www.conventionalcommits.org/) specification for clear history and tooling.

**Format:**

```
<type>(<scope>): <subject>
```

**Types:**

- `feat:` New feature
- `fix:` Bug fix
- `docs:` Documentation only
- `style:` Code style (whitespace, formatting, etc.)
- `refactor:` Code change that neither fixes a bug nor adds a feature
- `perf:` Performance improvement
- `test:` Adding or updating tests
- `chore:` Build, tooling, or maintenance

**Examples:**

```bash
feat(channels): add Telegram channel support
fix(skills): correct SKILL.md front matter parsing
docs(readme): update Docker quick start
refactor(providers): simplify custom provider validation
test(agents): add tests for skill loading
```

### 3. Pull Request Title Format

PR titles should follow the same convention:

**Format:** `<type>(<scope>): <description>`

- Use one of: `feat`, `fix`, `docs`, `test`, `refactor`, `chore`, `perf`, `style`, `build`, `revert`
- **Scope must be lowercase** (letters, numbers, hyphens, underscores only)
- Keep the description short and descriptive

**Examples:**

```
feat(models): add custom provider for Azure OpenAI
fix(channels): handle empty content_parts in Discord
docs(skills): document Skills Hub import
```

### 4. Code and Quality

- **Required local gate (must pass before push/PR):**
  ```bash
  pip install -e ".[dev,full]"
  pre-commit install
  pre-commit run --all-files
  pytest
  ```
- **If pre-commit modifies files:** Commit those changes, then rerun `pre-commit run --all-files` until it passes cleanly
- **CI policy:** Pull requests with failing pre-commit checks are not merge-ready
- **Frontend formatting:** If your changes involve the `console` or `website` directories, run the formatter before committing:
  ```bash
  cd console && npm run format
  cd website && pnpm format
  ```
- **Documentation:** Update docs when you add or change user-facing behavior. The docs live under `website/public/docs/`

---

## 💬 Getting Help

- **Discussions:** [GitHub Discussions](https://github.com/agentscope-ai/QwenPaw/discussions)
- **Bugs and features:** [GitHub Issues](https://github.com/agentscope-ai/QwenPaw/issues)
- **Community and developer groups:** See [Community page](/docs/community)

---

## 🗺️ Roadmap

Check our [Roadmap](/docs/roadmap) for items marked **Seeking Contributors** (e.g. new channels, model providers, skills, MCPs, or display/UX improvements) — great places to start!

---

Thank you for contributing to QwenPaw. Your work helps make it a better assistant for everyone. 🐾
