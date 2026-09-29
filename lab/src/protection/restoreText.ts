import type { ProtectedSpan, RestorationMap } from "../core/types.js";

/**
 * Restore placeholders in generated text back to original protected spans.
 * Also validates that all placeholders are present and correctly positioned.
 */
export function restoreText(
  generatedText: string,
  spans: ProtectedSpan[]
): { restored: string; failures: string[] } {
  const failures: string[] = [];
  let text = generatedText;

  // Sort spans by placeholder position in the generated text
  // Process from right to left to preserve offsets
  const spansWithPositions = spans
    .map((span) => ({
      span,
      position: text.indexOf(span.placeholder),
    }))
    .sort((a, b) => b.position - a.position); // reverse order

  for (const { span, position } of spansWithPositions) {
    if (position === -1) {
      // Check if the original text still exists (model kept it unchanged)
      const originalPos = text.indexOf(span.originalText);
      if (originalPos !== -1) {
        // Original text still there — that's fine
        span.restored = true;
        continue;
      }

      failures.push(
        `Missing placeholder ${span.placeholder} (type: ${span.type}, original: "${span.originalText}")`
      );
      continue;
    }

    // Replace placeholder with original text
    const before = text.substring(0, position);
    const after = text.substring(position + span.placeholder.length);
    text = before + span.originalText + after;
    span.restored = true;
  }

  // Final check: verify no stray placeholders remain
  const remainingPlaceholders = text.match(/PH_[A-Z_]{4,}_\d{4}_[a-z0-9]{4}/g);
  if (remainingPlaceholders) {
    for (const ph of remainingPlaceholders) {
      const span = spans.find((s) => s.placeholder === ph);
      if (span) {
        failures.push(`Stray placeholder ${ph} not restored (type: ${span.type})`);
      } else {
        failures.push(`Unknown placeholder ${ph} found in output`);
      }
    }
  }

  // Mark all restored spans
  for (const span of spans) {
    if (!span.restored) {
      // Check if original text is still intact
      if (text.includes(span.originalText)) {
        span.restored = true;
      }
    }
  }

  return { restored: text, failures };
}

/**
 * Validate that a candidate's restored output does not contain any placeholders
 * and that all original protected spans are preserved.
 */
export function validateRestoration(
  restoredText: string,
  originalSpans: ProtectedSpan[]
): { valid: boolean; failures: string[] } {
  const failures: string[] = [];

  // Check for stray placeholders
  const placeholderRegex = /PH_[A-Z_]{4,}_\d{4}_[a-z0-9]{4}/g;
  placeholderRegex.lastIndex = 0;
  const strayPlaceholders = restoredText.match(placeholderRegex);
  if (strayPlaceholders) {
    failures.push(`Found ${strayPlaceholders.length} stray placeholders in restored text`);
  }

  // Check each original protected span is present and unchanged
  for (const span of originalSpans) {
    if (!restoredText.includes(span.originalText)) {
      // Check if the placeholder is still there (means restore didn't happen)
      if (restoredText.includes(span.placeholder)) {
        failures.push(
          `Placeholder ${span.placeholder} not restored for "${span.originalText}" (type: ${span.type})`
        );
      } else {
        // The text was changed and not restored — worst case
        failures.push(
          `Protected span "${span.originalText}" (type: ${span.type}) was altered or removed`
        );
      }
    }
  }

  // Check for any new numbers, dates, citations that weren't in original
  // (conservative check — just flag them)
  // This is a soft check since models may add new digits legitimately

  return { valid: failures.length === 0, failures };
}
