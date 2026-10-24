#!/bin/bash
# Plainbook has no dependencies and no build step, so a cloud session needs
# only one thing: the pre-push guard that keeps the owner's records out of the
# repository (AGENTS.md, section 1). A fresh clone does not have it turned on.
set -euo pipefail

if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi

cd "${CLAUDE_PROJECT_DIR:-.}"

git config core.hooksPath .githooks

# Printed so the session knows how far the interpreter is above the 3.10 the README promises (AGENTS.md, section 8).
python3 -c 'import sys; print("python", sys.version.split()[0])'
