const SHA256_K = new Uint32Array([
  0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4, 0xab1c5ed5,
  0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174,
  0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
  0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967,
  0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13, 0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85,
  0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
  0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3,
  0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208, 0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2,
]);

function rotateRight(value: number, bits: number): number {
  return ((value >>> bits) | (value << (32 - bits))) >>> 0;
}

function inlineSha256Hex(text: string): string {
  const bytes = new TextEncoder().encode(text);
  const state = new Uint32Array([
    0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a, 0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19,
  ]);
  const paddedLength = Math.ceil((bytes.length + 9) / 64) * 64;
  const buffer = new Uint8Array(paddedLength);
  buffer.set(bytes);
  buffer[bytes.length] = 0x80;
  const view = new DataView(buffer.buffer);
  const bitLength = bytes.length * 8;
  view.setUint32(paddedLength - 8, Math.floor(bitLength / 0x100000000), false);
  view.setUint32(paddedLength - 4, bitLength >>> 0, false);

  const schedule = new Uint32Array(64);
  for (let block = 0; block < paddedLength; block += 64) {
    for (let index = 0; index < 16; index += 1) {
      schedule[index] = view.getUint32(block + index * 4, false);
    }
    for (let index = 16; index < 64; index += 1) {
      const previous = schedule[index - 15];
      const recent = schedule[index - 2];
      const s0 = rotateRight(previous, 7) ^ rotateRight(previous, 18) ^ (previous >>> 3);
      const s1 = rotateRight(recent, 17) ^ rotateRight(recent, 19) ^ (recent >>> 10);
      schedule[index] = (schedule[index - 16] + s0 + schedule[index - 7] + s1) >>> 0;
    }

    let a = state[0];
    let b = state[1];
    let c = state[2];
    let d = state[3];
    let e = state[4];
    let f = state[5];
    let g = state[6];
    let h = state[7];

    for (let index = 0; index < 64; index += 1) {
      const s1 = rotateRight(e, 6) ^ rotateRight(e, 11) ^ rotateRight(e, 25);
      const choose = (e & f) ^ (~e & g);
      const temp1 = (h + s1 + choose + SHA256_K[index] + schedule[index]) >>> 0;
      const s0 = rotateRight(a, 2) ^ rotateRight(a, 13) ^ rotateRight(a, 22);
      const majority = (a & b) ^ (a & c) ^ (b & c);
      const temp2 = (s0 + majority) >>> 0;
      h = g;
      g = f;
      f = e;
      e = (d + temp1) >>> 0;
      d = c;
      c = b;
      b = a;
      a = (temp1 + temp2) >>> 0;
    }

    state[0] = (state[0] + a) >>> 0;
    state[1] = (state[1] + b) >>> 0;
    state[2] = (state[2] + c) >>> 0;
    state[3] = (state[3] + d) >>> 0;
    state[4] = (state[4] + e) >>> 0;
    state[5] = (state[5] + f) >>> 0;
    state[6] = (state[6] + g) >>> 0;
    state[7] = (state[7] + h) >>> 0;
  }

  let hex = "";
  for (let index = 0; index < state.length; index += 1) {
    hex += state[index].toString(16).padStart(8, "0");
  }
  return hex;
}

export interface TextRange {
  start: number;
  end: number;
}

export interface StudioDecisionRecord {
  id: string;
  paragraphId: string;
  paragraphHash: string;
  saved: boolean;
  selectionText: string;
  selectionRange: TextRange;
  operation: string;
  optionsShown: string[];
  optionPicked: string;
  optionsSkipped: string[];
  modelId: string;
  adapterId: string | null;
  timestamp: string;
  originalParagraph?: string;
  finalParagraph?: string;
}

interface NodeFs {
  mkdirSync(p: string, options?: { recursive?: boolean }): void;
  appendFileSync(p: string, data: string, encoding: string): void;
  existsSync(p: string): boolean;
  readFileSync(p: string, encoding: string): string;
  writeFileSync(p: string, data: string, encoding: string): void;
}

interface NodePath {
  dirname(p: string): string;
  join(...paths: string[]): string;
}

interface NodeOs {
  homedir(): string;
}

interface NodeCrypto {
  createHash(algorithm: string): {
    update(data: string, encoding?: string): {
      digest(encoding: string): string;
    };
  };
}

function getNodeFs(): NodeFs | null {
  if (typeof process !== "undefined" && typeof (process as any).getBuiltinModule === "function") {
    return (process as any).getBuiltinModule("fs") as NodeFs;
  }
  return null;
}

function getNodePath(): NodePath | null {
  if (typeof process !== "undefined" && typeof (process as any).getBuiltinModule === "function") {
    return (process as any).getBuiltinModule("path") as NodePath;
  }
  return null;
}

function getNodeOs(): NodeOs | null {
  if (typeof process !== "undefined" && typeof (process as any).getBuiltinModule === "function") {
    return (process as any).getBuiltinModule("os") as NodeOs;
  }
  return null;
}

function getNodeCrypto(): NodeCrypto | null {
  if (typeof process !== "undefined" && typeof (process as any).getBuiltinModule === "function") {
    return (process as any).getBuiltinModule("crypto") as NodeCrypto;
  }
  return null;
}

export function hashParagraph(text: string): string {
  const crypto = getNodeCrypto();
  if (crypto) {
    return crypto.createHash("sha256").update(text.trim(), "utf8").digest("hex");
  }
  return inlineSha256Hex(text.trim());
}

export function getApplicationSupportPath(): string {
  const os = getNodeOs();
  const path = getNodePath();
  if (os && path) {
    if (process.platform === "darwin") {
      return path.join(os.homedir(), "Library", "Application Support", "Open Local Phraser");
    }
    return path.join(os.homedir(), ".open-local-phraser");
  }
  return "~/Library/Application Support/Open Local Phraser";
}

export function getDefaultDecisionLogPath(): string {
  const path = getNodePath();
  if (path) {
    return path.join(getApplicationSupportPath(), "studio-decisions.jsonl");
  }
  return `${getApplicationSupportPath()}/studio-decisions.jsonl`;
}

let inMemoryDecisions: StudioDecisionRecord[] = [];

export function appendStudioDecision(
  record: StudioDecisionRecord,
  logPath: string = getDefaultDecisionLogPath()
): void {
  inMemoryDecisions.push(record);
  const fs = getNodeFs();
  const path = getNodePath();
  if (fs && path) {
    try {
      fs.mkdirSync(path.dirname(logPath), { recursive: true });
      fs.appendFileSync(logPath, JSON.stringify(record) + "\n", "utf8");
    } catch {
      // Ignore filesystem write errors
    }
  } else if (typeof localStorage !== "undefined") {
    try {
      localStorage.setItem("pari-studio-decisions", JSON.stringify(inMemoryDecisions));
    } catch {
      // Ignore localStorage quotas
    }
  }
}

export function markParagraphSavedInLog(
  paragraphId: string,
  paragraphHash: string,
  originalParagraph: string,
  finalParagraph: string,
  logPath: string = getDefaultDecisionLogPath()
): number {
  let updatedCount = 0;
  inMemoryDecisions = inMemoryDecisions.map((decision) => {
    if (decision.paragraphId === paragraphId || decision.paragraphHash === paragraphHash) {
      updatedCount += 1;
      return {
        ...decision,
        saved: true,
        originalParagraph,
        finalParagraph,
      };
    }
    return decision;
  });

  const fs = getNodeFs();
  if (fs) {
    try {
      if (fs.existsSync(logPath)) {
        const lines = fs.readFileSync(logPath, "utf8").split("\n").filter(Boolean);
        const updatedLines = lines.map((line) => {
          try {
            const item = JSON.parse(line) as StudioDecisionRecord;
            if (item.paragraphId === paragraphId || item.paragraphHash === paragraphHash) {
              return JSON.stringify({
                ...item,
                saved: true,
                originalParagraph,
                finalParagraph,
              });
            }
            return line;
          } catch {
            return line;
          }
        });
        fs.writeFileSync(logPath, updatedLines.join("\n") + "\n", "utf8");
      }
    } catch {
      // Ignore fs errors in browser context
    }
  } else if (typeof localStorage !== "undefined") {
    try {
      localStorage.setItem("pari-studio-decisions", JSON.stringify(inMemoryDecisions));
    } catch {
      // Ignore localStorage errors
    }
  }

  return updatedCount;
}

export function getInMemoryDecisions(): StudioDecisionRecord[] {
  return [...inMemoryDecisions];
}

export function clearInMemoryDecisions(): void {
  inMemoryDecisions = [];
}

export function exportSavedDecisionsToJsonl(
  outputPath: string,
  logPath: string = getDefaultDecisionLogPath()
): { exportedCount: number; destination: string } {
  let decisionsToExport: StudioDecisionRecord[] = [];
  const fs = getNodeFs();
  const path = getNodePath();

  if (fs) {
    try {
      if (fs.existsSync(logPath)) {
        const lines = fs.readFileSync(logPath, "utf8").split("\n").filter(Boolean);
        decisionsToExport = lines
          .map((l) => {
            try {
              return JSON.parse(l) as StudioDecisionRecord;
            } catch {
              return null;
            }
          })
          .filter((d): d is StudioDecisionRecord => Boolean(d && d.saved));
      }
    } catch {
      // Fall back to in-memory
    }
  }

  if (decisionsToExport.length === 0) {
    decisionsToExport = inMemoryDecisions.filter((d) => d.saved);
  }

  if (fs && path) {
    fs.mkdirSync(path.dirname(outputPath), { recursive: true });
    const content =
      decisionsToExport.map((d) => JSON.stringify(d)).join("\n") +
      (decisionsToExport.length > 0 ? "\n" : "");
    fs.writeFileSync(outputPath, content, "utf8");
  }

  return { exportedCount: decisionsToExport.length, destination: outputPath };
}
