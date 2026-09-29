import type { PreferenceProfile } from "../core/types.js";
import * as fs from "fs";
import * as path from "path";

const DEFAULT_PROFILES_DIR = new URL("../../data", import.meta.url).pathname;

const DEFAULT_PROFILE: PreferenceProfile = {
  id: "default",
  name: "Default Student Profile",
  hardBannedWords: [],
  softDislikedWords: [
    "utilize", "facilitate", "elucidate", "aforementioned", "moreover",
    "furthermore", "therefore", "thus", "underscores", "underscore",
    "multifaceted", "demonstrates", "illustrates", "exemplifies",
    "imperative", "pivotal", "subsequently", "individuals",
  ],
  preferredReplacements: {
    utilize: ["use"],
    individuals: ["people"],
    demonstrates: ["shows"],
    illustrates: ["shows"],
    moreover: ["also"],
    therefore: ["so"],
    significant: ["important", "clear", "big"],
    crucial: ["important"],
    facilitate: ["help"],
    aforementioned: ["earlier"],
  },
  formalityTarget: 1,
  lexicalDiversityTarget: 0.4,
  structureChangeTarget: 0.3,
  sentenceLengthTarget: "same",
  professorPenaltyWeight: 0.15,
};

let profiles: PreferenceProfile[] = [DEFAULT_PROFILE];

/**
 * Get a preference profile by ID or name.
 */
export function getProfile(idOrName: string): PreferenceProfile | null {
  return profiles.find((p) => p.id === idOrName || p.name === idOrName) ?? null;
}

/**
 * Get the default profile.
 */
export function getDefaultProfile(): PreferenceProfile {
  return DEFAULT_PROFILE;
}

/**
 * Create a new preference profile.
 */
export function createProfile(profile: PreferenceProfile): void {
  profiles.push(profile);
}

/**
 * Update an existing profile.
 */
export function updateProfile(id: string, updates: Partial<PreferenceProfile>): void {
  const index = profiles.findIndex((p) => p.id === id);
  if (index !== -1) {
    profiles[index] = { ...profiles[index], ...updates };
  }
}

/**
 * Load profiles from a JSON file.
 */
export function loadProfiles(filePath?: string): void {
  const p = filePath ?? path.join(DEFAULT_PROFILES_DIR, "preferenceProfiles.json");
  try {
    const data = fs.readFileSync(p, "utf-8");
    const loaded = JSON.parse(data);
    if (Array.isArray(loaded)) {
      profiles = loaded;
    }
  } catch {
    // Use defaults
  }
}

/**
 * Save profiles to a JSON file.
 */
export function saveProfiles(filePath?: string): void {
  const p = filePath ?? path.join(DEFAULT_PROFILES_DIR, "preferenceProfiles.json");
  try {
    const dir = path.dirname(p);
    if (!fs.existsSync(dir)) {
      fs.mkdirSync(dir, { recursive: true });
    }
    fs.writeFileSync(p, JSON.stringify(profiles, null, 2), "utf-8");
  } catch {
    // Ignore write errors
  }
}

/**
 * Get all profiles.
 */
export function getAllProfiles(): PreferenceProfile[] {
  return [...profiles];
}

export type { PreferenceProfile };
