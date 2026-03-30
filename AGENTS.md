# AGENTS.md

## Project Structure

```
CoPaw/
├── src/copaw/           # Backend (Python)
├── console/             # Frontend 1 (Vite + TypeScript)
├── website/             # Frontend 2 (Vite)
├── tests/               # Python tests
│   ├── unit/           # Unit tests
│   └── integrated/     # Integration tests
├── pyproject.toml       # Python config
└── .pre-commit-config.yaml
```

## Backend (Python)

### Setup

```bash
# Create and activate venv
python -m venv .venv
source .venv/bin/activate

# Install deps
pip install -e ".[dev]"
pre-commit install
```

### Lint & Format

```bash
# Run all checks (required before commit)
pre-commit run --all-files

# Run checks for a specific file
pre-commit run --files src/copaw/cli/main.py
```

## Testing

### Python (pytest)

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=src/copaw

# Run specific test file
pytest tests/unit/test_example.py

# Run tests matching pattern
pytest -k "test_name_pattern"
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

- **Line length**: 79 characters (Black & Flake8 configured as in .pre-commit-config.yaml)
- **Formatter**: Black
- **Linters/Type checking**: Flake8, Pylint, Mypy (as configured in .pre-commit-config.yaml)

Run `pre-commit run --all-files` to auto-format and check.

### TypeScript/JavaScript

- **Line length**: 80 characters
- **Linter**: ESLint
- **Formatter**: Prettier

## Full Guidelines

See [CONTRIBUTING.md](CONTRIBUTING.md) for detailed guidelines.

## Quick Rules

- **Always use .venv** for Python commands (python, pip), formatters and `pre-commit` commands
- **Run pre-commit** every time the backend code is changed
- **Run tests** before major commits: `pytest`
- **Format frontend** code from each app directory: `cd console && npm run format`, `cd website && pnpm format`
