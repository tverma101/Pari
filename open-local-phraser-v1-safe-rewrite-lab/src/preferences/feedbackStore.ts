import type { FeedbackEvent, FeedbackType } from "../core/types.js";
import * as fs from "fs";
import * as path from "path";

const FEEDBACK_FILE = new URL("../../data/feedback.json", import.meta.url).pathname;

/**
 * In-memory feedback store.
 */
const feedbackEvents: FeedbackEvent[] = [];

/**
 * Load feedback from disk.
 */
export function loadFeedback(filePath?: string): void {
  const p = filePath ?? FEEDBACK_FILE;
  try {
    const data = fs.readFileSync(p, "utf-8");
    const loaded = JSON.parse(data);
    if (Array.isArray(loaded)) {
      feedbackEvents.length = 0;
      feedbackEvents.push(...loaded);
    }
  } catch {
    // No feedback file yet
  }
}

/**
 * Save feedback to disk.
 */
export function saveFeedback(filePath?: string): void {
  const p = filePath ?? FEEDBACK_FILE;
  try {
    const dir = path.dirname(p);
    if (!fs.existsSync(dir)) {
      fs.mkdirSync(dir, { recursive: true });
    }
    fs.writeFileSync(p, JSON.stringify(feedbackEvents, null, 2), "utf-8");
  } catch {
    // Ignore write errors
  }
}

/**
 * Record a feedback event.
 */
export function recordFeedback(
  type: FeedbackType,
  originalText: string,
  candidateText: string,
  metadata?: Record<string, unknown>
): void {
  const event: FeedbackEvent = {
    timestamp: new Date().toISOString(),
    type,
    originalText,
    candidateText,
    metadata,
  };
  feedbackEvents.push(event);
  // Auto-save
  saveFeedback();
}

/**
 * Get all feedback events.
 */
export function getAllFeedback(): FeedbackEvent[] {
  return [...feedbackEvents];
}

/**
 * Get feedback events filtered by type.
 */
export function getFeedbackByType(type: FeedbackType): FeedbackEvent[] {
  return feedbackEvents.filter((e) => e.type === type);
}

/**
 * Summarize feedback counts.
 */
export function summarizeFeedback(): Record<string, number> {
  const summary: Record<string, number> = {};
  for (const event of feedbackEvents) {
    summary[event.type] = (summary[event.type] ?? 0) + 1;
  }
  return summary;
}

/**
 * Clear all feedback.
 */
export function clearFeedback(): void {
  feedbackEvents.length = 0;
  saveFeedback();
}

export type { FeedbackEvent, FeedbackType };
