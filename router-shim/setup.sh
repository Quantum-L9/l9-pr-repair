#!/usr/bin/env bash
# Build the router-shim and its public LLM-Router dependency.
#
# The @quantum-l9/llm-router package ships TypeScript source with no `prepare`
# hook, so installing it from the (public) git repo does NOT auto-build dist/.
# We install it and then compile it in place so shim.mjs can import dist/index.js.
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$here"

# --ignore-scripts: installing a package must not be able to execute it. Any
# dependency's preinstall/install/postinstall hook otherwise runs arbitrary code
# on the developer machine or CI runner that merely resolves the tree. Nothing
# here needs those hooks -- as the note above records, @quantum-l9/llm-router
# ships no `prepare` hook and is built explicitly below.
echo "[router-shim] installing dependencies..."
npm install --ignore-scripts

dep_dir="node_modules/@quantum-l9/llm-router"
if [ ! -f "$dep_dir/dist/index.js" ]; then
  echo "[router-shim] building @quantum-l9/llm-router from source..."
  # `npm run build` stays: it is this script's own deliberate build step, not a
  # hook a dependency got to choose.
  (cd "$dep_dir" && npm install --ignore-scripts && npm run build)
fi

echo "[router-shim] ready. Provider keys are read from the environment at runtime:"
echo "  OPENROUTER_API_KEY, PERPLEXITY_API_KEY"
