#!/usr/bin/env bash
# Run once after cloning. Registers the `ours` merge driver so per-branch
# identity files (repository.yaml, addon/icon.png, addon/logo.png) are
# preserved when merging dev -> beta -> main.
set -e
git config merge.ours.driver true
echo "Configured merge.ours.driver — channel identity files will be preserved on merge."
