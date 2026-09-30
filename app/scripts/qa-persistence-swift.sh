#!/usr/bin/env bash
# Compiles and runs the Swift persistence checks.
#
# ApprovalPersistence used to be reachable only through the WKWebView shell, so
# the corrupt-file and history-destruction paths had never been executed. This
# compiles the type against a temporary directory instead of the real
# Application Support file.
#
# Skips cleanly when no Swift toolchain is present (CI runners without one) so a
# missing compiler is never reported as a passing test.
set -uo pipefail

cd "$(dirname "$0")/.." || exit 1

if ! command -v swiftc >/dev/null 2>&1; then
  echo "qa-persistence-swift: SKIP (no swiftc on PATH)"
  exit 0
fi

out="$(mktemp -t pari-persistence).bin"
trap 'rm -f "$out"' EXIT

if ! swiftc -o "$out" \
  Sources/OpenLocalPhraser/ApprovalPersistence.swift \
  scripts/qa-persistence-swift.swift 2>/tmp/pari-swift-build.log; then
  echo "qa-persistence-swift: FAILED to compile"
  sed 's/^/  /' /tmp/pari-swift-build.log
  exit 1
fi

"$out"
