/**
 * Banned word and preferred word penalty/bonus system.
 */

export interface BanwordConfig {
  hardBanned: string[];
  softDisliked: string[];
  preferredReplacements: Record<string, string[]>;
}

const DEFAULT_BANWORD_CONFIG: BanwordConfig = {
  hardBanned: [],
  softDisliked: [],
  preferredReplacements: {},
};

let banwordConfig: BanwordConfig = { ...DEFAULT_BANWORD_CONFIG };

/**
 * Set the banword configuration.
 */
export function setBanwordConfig(config: Partial<BanwordConfig>): void {
  banwordConfig = {
    ...banwordConfig,
    ...config,
    preferredReplacements: {
      ...banwordConfig.preferredReplacements,
      ...(config.preferredReplacements ?? {}),
    },
  };
}

/**
 * Reset to default configuration.
 */
export function resetBanwordConfig(): void {
  banwordConfig = { ...DEFAULT_BANWORD_CONFIG };
}

/**
 * Compute banword penalty for a candidate sentence.
 * Returns a score between 0 and 1, where:
 * 0 = contains hard banned words (severe)
 * 1 = no banned words, good preference matches
 */
export function computeBanwordPenalty(candidate: string): number {
  const lower = candidate.toLowerCase();
  const words = lower.split(/\s+/);

  // Check hard banned words
  for (const banned of banwordConfig.hardBanned) {
    if (lower.includes(banned.toLowerCase())) {
      return 0; // Hard reject on banned word
    }
  }

  // Soft disliked words penalty
  let dislikedCount = 0;
  for (const disliked of banwordConfig.softDisliked) {
    for (const word of words) {
      if (word.includes(disliked.toLowerCase())) {
        dislikedCount++;
      }
    }
  }

  // Preferred replacements bonus
  let preferredUsed = 0;
  let preferredAvailable = 0;
  for (const [original, replacements] of Object.entries(banwordConfig.preferredReplacements)) {
    // Check if original was used
    if (words.some((w) => w === original)) {
      preferredAvailable++;
    }
    // Check if a replacement was used instead
    for (const replacement of replacements) {
      if (words.some((w) => w === replacement.toLowerCase())) {
        preferredUsed++;
      }
    }
  }

  // Calculate final score
  const baseScore = 1.0;
  const dislikedPenalty = Math.min(dislikedCount * 0.1, 0.5);

  // Bonus for using preferred replacements
  let bonus = 0;
  if (preferredAvailable > 0) {
    bonus = (preferredUsed / preferredAvailable) * 0.15;
  }

  return Math.max(0, Math.min(1, baseScore - dislikedPenalty + bonus));
}


