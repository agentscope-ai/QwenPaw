# AGENTS.md

## Project Structure

```
CoPaw/
├── src/copaw/           # Backend (Python)
├── console/             # Frontend 1 (Vite + TypeScript)
├── website/             # Frontend 2 (Vite)
├── pyproject.toml       # Python config
└── .pre-commit-config.yaml
```

## Backend (Python)

### Setup

```bash
# Create and activate venv
python -m venv .venv
source .venv/bin/activate  # macOS/Linux

# Install deps
pip install -e ".[dev]"
pre-commit install
```

### Lint & Format

```bash
# Run all checks (required before commit)
pre-commit run --all-files

# Run specific check
pre-commit run --files src/copaw/cli/main.py
```

## Frontend

### Console (Vite + TS)

```bash
cd console
npm install
npm run dev      # Start dev server
npm run build    # Production build
npm run lint     # ESLint check
npm run format   # Code formatting
```

### Website (Vite)

```bash
cd website
pnpm install
pnpm dev
pnpm build
pnpm format
```

## Code Style

### Python

- **Line length**: 88 characters (Black default)
- **Formatter**: Black
- **Linter**: Ruff, Flake8
- **Import order**: isort

Run `pre-commit run --all-files` to auto-format and check.

### TypeScript/JavaScript

- **Line length**: 80 characters
- **Linter**: ESLint
- **Formatter**: Prettier

### Commit Convention

Follow [Conventional Commits](https://www.conventionalcommits.org/):

```
<type>(<scope>): <subject>
```

Types: `feat`, `fix`, `docs`, `style`, `refactor`, `perf`, `test`, `chore`

**Examples:**
```bash
feat(channels): add Telegram channel stub
fix(skills): correct SKILL.md parsing
docs(readme): update quick start
```

## Full Guidelines

See [CONTRIBUTING.md](CONTRIBUTING.md) for detailed contribution guidelines.

## Quick Rules

- **Always use .venv** for Python commands
- **Run pre-commit** before every commit
- **Format frontend** code with `npm run format` or `pnpm format`
- **Follow commit convention** for all commits
