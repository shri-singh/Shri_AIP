#!/usr/bin/env bash
set -euo pipefail
mkdir -p vendor
if [[ ! -e vendor/OpenMetadata ]]; then
 git clone --filter=blob:none https://github.com/open-metadata/OpenMetadata.git vendor/OpenMetadata
fi
if [[ ! -e vendor/CopilotKit ]]; then
 git clone --filter=blob:none https://github.com/CopilotKit/CopilotKit.git vendor/CopilotKit
fi
if [[ -n "${OM_REF:-}" ]]; then git -C vendor/OpenMetadata checkout --detach "$OM_REF"; fi
if [[ -n "${COPILOT_REF:-}" ]]; then git -C vendor/CopilotKit checkout --detach "$COPILOT_REF"; fi
printf 'OpenMetadata SHA: '; git -C vendor/OpenMetadata rev-parse HEAD
printf 'CopilotKit SHA: '; git -C vendor/CopilotKit rev-parse HEAD
echo 'Pin the reviewed SHAs in your build documentation. No automatic upgrades.'
