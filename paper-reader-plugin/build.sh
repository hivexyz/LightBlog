#!/bin/bash
# Build script for paper-reader-plugin client bundle.
cd "$(dirname "$0")"
npx esbuild src/client/index.ts --bundle --outfile=lib/client.js --format=cjs --platform=browser --external:react --external:react-dom --external:@deepseek-ai/dsh-client-runtime --external:@deepseek-ai/dsh-client-ui-slots
echo "Client bundle built successfully"
