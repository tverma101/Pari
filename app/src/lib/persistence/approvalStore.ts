import { createEmptyPreferenceMemory, type ApprovedExample, type PreferenceMemory } from "@/lib/personalization/approvalMemory";
import { nativeBridgeAvailable, requestNativeBridge } from "@/lib/platform/nativeBridge";

export interface ApprovalState {
  schemaVersion: number;
  examples: ApprovedExample[];
  memory: PreferenceMemory;
}

const SCHEMA_VERSION = 1;
const DB_NAME = "open-local-phraser-approval-memory";
const DB_VERSION = 1;
const EXAMPLES_STORE = "approved-examples";
const MEMORY_STORE = "preference-memory";

function normalizeMemory(value: unknown): PreferenceMemory {
  const empty = createEmptyPreferenceMemory();
  if (!value || typeof value !== "object") return empty;
  const raw = value as Partial<PreferenceMemory>;
  return {
    ...empty,
    ...raw,
    approvedReplacements: raw.approvedReplacements ?? {},
    revertedReplacements: raw.revertedReplacements ?? {},
    phrasePreferences: raw.phrasePreferences ?? {},
    avoidedPhrases: raw.avoidedPhrases ?? {},
    punctuation: raw.punctuation ?? {},
    contractions: raw.contractions ?? {},
    sentenceLength: raw.sentenceLength ?? empty.sentenceLength,
    paragraphLength: raw.paragraphLength ?? empty.paragraphLength,
    sentenceStructure: raw.sentenceStructure ?? {},
  };
}

function normalizeState(value: unknown): ApprovalState {
  if (!value || typeof value !== "object") {
    return { schemaVersion: SCHEMA_VERSION, examples: [], memory: createEmptyPreferenceMemory() };
  }

  const raw = value as Partial<ApprovalState>;
  return {
    schemaVersion: SCHEMA_VERSION,
    examples: Array.isArray(raw.examples) ? raw.examples : [],
    memory: normalizeMemory(raw.memory),
  };
}

function openDatabase(): Promise<IDBDatabase> {
  if (typeof indexedDB === "undefined") return Promise.reject(new Error("IndexedDB is unavailable"));

  return new Promise((resolve, reject) => {
    const request = indexedDB.open(DB_NAME, DB_VERSION);
    request.onerror = () => reject(request.error ?? new Error("Could not open approval database"));
    request.onupgradeneeded = () => {
      const database = request.result;
      if (!database.objectStoreNames.contains(EXAMPLES_STORE)) {
        database.createObjectStore(EXAMPLES_STORE, { keyPath: "id" });
      }
      if (!database.objectStoreNames.contains(MEMORY_STORE)) {
        database.createObjectStore(MEMORY_STORE, { keyPath: "id" });
      }
    };
    request.onsuccess = () => resolve(request.result);
  });
}

async function loadFromIndexedDB(): Promise<ApprovalState> {
  const database = await openDatabase();
  return new Promise((resolve, reject) => {
    const transaction = database.transaction([EXAMPLES_STORE, MEMORY_STORE], "readonly");
    const examplesRequest = transaction.objectStore(EXAMPLES_STORE).getAll();
    const memoryRequest = transaction.objectStore(MEMORY_STORE).get("current");
    transaction.onerror = () => reject(transaction.error ?? new Error("Could not read approval database"));
    transaction.oncomplete = () => {
      resolve(normalizeState({
        examples: examplesRequest.result ?? [],
        memory: memoryRequest.result?.value ?? memoryRequest.result,
      }));
      database.close();
    };
  });
}

async function saveToIndexedDB(record: ApprovedExample, memory: PreferenceMemory): Promise<ApprovalState> {
  const database = await openDatabase();
  return new Promise((resolve, reject) => {
    const transaction = database.transaction([EXAMPLES_STORE, MEMORY_STORE], "readwrite");
    transaction.objectStore(EXAMPLES_STORE).put(record);
    transaction.objectStore(MEMORY_STORE).put({ id: "current", value: memory });
    transaction.onerror = () => reject(transaction.error ?? new Error("Could not save approval"));
    transaction.oncomplete = () => {
      void loadFromIndexedDB().then(resolve, reject);
      database.close();
    };
  });
}

export async function loadApprovalState(): Promise<ApprovalState> {
  if (nativeBridgeAvailable()) {
    try {
      return normalizeState(await requestNativeBridge("loadState"));
    } catch {
      // The browser fallback keeps local development and QA usable when the
      // WKWebView bridge is not present. The packaged app uses native storage.
    }
  }

  try {
    return await loadFromIndexedDB();
  } catch {
    return { schemaVersion: SCHEMA_VERSION, examples: [], memory: createEmptyPreferenceMemory() };
  }
}

export async function persistApproval(
  record: ApprovedExample,
  memory: PreferenceMemory
): Promise<ApprovalState> {
  if (nativeBridgeAvailable()) {
    const result = await requestNativeBridge("saveApproval", { record, memory });
    return normalizeState(result);
  }

  return saveToIndexedDB(record, memory);
}

export function usesNativePersistence(): boolean {
  return nativeBridgeAvailable();
}
