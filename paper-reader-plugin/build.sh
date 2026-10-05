#!/usr/bin/env bash
set -euo pipefail

# DSH Web2 client bundles are lazy CommonJS factories. Loading the script must
# register the factory; the plugin body is materialized later by DSH's module
# loader with its own `require` implementation.
cd "$(dirname "$0")"
./node_modules/.bin/esbuild src/client/index.ts \
  --bundle \
  --outfile=lib/client.js \
  --format=cjs \
  --platform=browser \
  --external:react \
  --external:react-dom \
  --external:@deepseek-ai/dsh-client-runtime \
  --external:@deepseek-ai/dsh-client-ui-slots \
  '--banner:js=window.__ModuleLoader__.load({ id: "dsh-paper-reader", factory: (require) => { var module = { exports: {} }; var exports = module.exports;' \
  '--footer:js=return module.exports; } });'

node scripts/verify-client-bundle.mjs
echo "Client bundle built and verified successfully"
