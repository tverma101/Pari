#!/usr/bin/env bash
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
cd "$HERE"

node validate-english-core.mjs
node audit-english-core-shadow.mjs
node test-english-core-choice-parser.mjs
python3 test_english_core_choice_parser.py

printf '%s\n' 'English Core structural self-check passed.'
