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
    let raw: unknown;
    try {
      raw = await requestNativeBridge("loadState");
    } catch (error) {
      // A missing bridge is expected in the browser and in QA, so fall through
      // to IndexedDB there. A bridge that answers with an explicit failure is a
      // real read error and must not be indistinguishable from an empty history.
      if (!/bridge|unavailable|timed out/i.test(error instanceof Error ? error.message : String(error))) {
        throw error;
      }
    }
    if (raw !== undefined) {
      const payload = raw as { ok?: boolean; error?: string };
      if (payload.ok === false) {
        throw new Error(payload.error ?? "Your saved approvals could not be read on this Mac.");
      }
      return normalizeState(raw);
    }
  }

  try {
    return await loadFromIndexedDB();
  } catch (error) {
    // loadFromIndexedDB resolves only when the transaction genuinely completed,
    // so a rejection means the store could not be read -- not that it was empty.
    // Returning an empty state here made the UI say "learns from the edits you
    // approve" while the real history was still on disk and unreadable. Report it
    // so the UI can withdraw its storage claim instead of asserting a clean slate.
    const detail = error instanceof Error ? error.name : "unknown error";
    console.error("approval store could not be read", error);
    throw new Error(`Your saved approvals could not be read on this device, so Pari is not using them. (${detail})`);
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
