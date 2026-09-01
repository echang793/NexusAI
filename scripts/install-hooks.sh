#!/bin/bash
# Install this repo's git hooks (currently: pre-commit, blocks committing
# real financial data / secrets). Safe to re-run any time — always
# overwrites .git/hooks/pre-commit with the current tracked template.
#
# Run this once after cloning the repo on any machine (including a fresh
# setup, e.g. a new Mac).
set -e
cd "$(dirname "$0")/.."

if [ ! -d .git ]; then
    echo "Error: not a git repo (run this from inside NexusAI, or after cloning it)."
    exit 1
fi

cp scripts/githooks/pre-commit .git/hooks/pre-commit
chmod +x .git/hooks/pre-commit
echo "Installed .git/hooks/pre-commit"
