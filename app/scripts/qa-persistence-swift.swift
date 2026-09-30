// Executes ApprovalPersistence against a temporary directory. These paths used
// to be unreachable from any test because the state file location was hardcoded
// to the real Application Support directory -- and the failure mode they guard
// (silently destroying every saved approval) is destructive enough that shipping
// it unverified is not acceptable.
//
// Run: swiftc -O Sources/OpenLocalPhraser/*.swift scripts/qa-persistence-swift.swift
//      (the sources define an AppKit entrypoint; compile this file with -parse-as-library
//      style isolation via `swift scripts/qa-persistence-swift.swift` is NOT used)
// Instead it is run by scripts/qa-persistence-swift.sh, which compiles only the
// persistence type plus this file.

import Foundation

var failures: [String] = []

func check(_ condition: Bool, _ message: String) {
    if condition {
        print("  ok   \(message)")
    } else {
        failures.append(message)
        print("  FAIL \(message)")
    }
}

func makeTempDirectory() -> URL {
    let url = FileManager.default.temporaryDirectory
        .appendingPathComponent("pari-persistence-test-\(UUID().uuidString)", isDirectory: true)
    try? FileManager.default.createDirectory(at: url, withIntermediateDirectories: true)
    return url
}

func record(_ id: String, _ text: String) -> [String: Any] {
    return [
        "id": id,
        "originalText": text,
        "editedText": text + " (edited)",
        "createdAt": "2026-01-01T00:00:00.000Z",
    ]
}

@main
struct PersistenceQA {
    static func main() throws {
    // 1. Missing file is a legitimate empty state, not an error.
    do {
        let directory = makeTempDirectory()
        defer { try? FileManager.default.removeItem(at: directory) }
        let persistence = ApprovalPersistence(directory: directory)
        let state = persistence.loadState()
        check(state["ok"] as? Bool != false, "missing file reports an empty state, not a failure")
        check((state["examples"] as? [[String: Any]])?.isEmpty ?? true, "missing file yields zero examples")
    }

    // 2. A valid file round-trips.
    do {
        let directory = makeTempDirectory()
        defer { try? FileManager.default.removeItem(at: directory) }
        let persistence = ApprovalPersistence(directory: directory)
        _ = try persistence.saveApproval(payload: [
            "record": record("r1", "The team met"),
            "memory": [:],
        ])
        let state = persistence.loadState()
        check(state["ok"] as? Bool != false, "valid file is not reported as a failure")
        check((state["examples"] as? [[String: Any]])?.count == 1, "saved approval is read back")
    }

    // 3. Corrupt file is reported as unreadable rather than as an empty history.
    do {
        let directory = makeTempDirectory()
        defer { try? FileManager.default.removeItem(at: directory) }
        let url = directory.appendingPathComponent("approved-state.json")
        try "{ this is not json".write(to: url, atomically: true, encoding: .utf8)
        let persistence = ApprovalPersistence(directory: directory)
        let state = persistence.loadState()
        check(state["ok"] as? Bool == false, "corrupt file reports ok:false")
        check((state["error"] as? String)?.isEmpty == false, "corrupt file explains itself")
    }

    // 4. The destructive path: saving against a corrupt file must NOT destroy it.
    do {
        let directory = makeTempDirectory()
        defer { try? FileManager.default.removeItem(at: directory) }
        let url = directory.appendingPathComponent("approved-state.json")
        let corrupt = "{ this is not json"
        try corrupt.write(to: url, atomically: true, encoding: .utf8)
        let persistence = ApprovalPersistence(directory: directory)

        var refused = false
        do {
            _ = try persistence.saveApproval(payload: [
                "record": record("r1", "The team met"),
                "memory": [:],
            ])
        } catch {
            refused = true
        }
        check(refused, "saveApproval refuses to write over an unreadable history")

        let after = (try? String(contentsOf: url, encoding: .utf8)) ?? ""
        check(after == corrupt, "the unreadable file is left byte-for-byte untouched")
    }

    // 5. A save that replaces an existing record id does not duplicate it.
    do {
        let directory = makeTempDirectory()
        defer { try? FileManager.default.removeItem(at: directory) }
        let persistence = ApprovalPersistence(directory: directory)
        _ = try persistence.saveApproval(payload: ["record": record("r1", "A"), "memory": [:]])
        _ = try persistence.saveApproval(payload: ["record": record("r1", "A"), "memory": [:]])
        let state = persistence.loadState()
        check((state["examples"] as? [[String: Any]])?.count == 1, "re-saving the same record id does not duplicate it")
    }

    if failures.isEmpty {
        print("  persistence: all checks passed")
        exit(0)
    }
    print("  persistence: \(failures.count) check(s) failed")
    exit(1)

    }
}
