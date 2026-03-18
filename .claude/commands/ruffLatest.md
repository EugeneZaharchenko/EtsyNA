Your goal is to check, fix, and format $ARGUMENTS Python files.

Do the following as bash commands:

1. **Lint and auto-fix:**
   Run `uv run ruff check --fix --unsafe-fixes $ARGUMENTS`

2. **Format code:**
   Run `uv run ruff format $ARGUMENTS`

3. **Type checking (optional, if mypy/pyright configured):**
   Run `uv run mypy $ARGUMENTS` or `uv run pyright $ARGUMENTS`

4. **If no $ARGUMENTS provided:**
   - First try: `git diff --name-only --cached -- '*.py'` (staged files)
   - Then try: `git diff --name-only HEAD -- '*.py'` (modified files)
   - Fallback: `find . -name '*.py' -mmin -30 -type f` (changed in last 30 min)
   - Run commands on found files

5. **Report remaining issues** that cannot be auto-fixed
