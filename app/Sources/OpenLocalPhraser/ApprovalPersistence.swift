import Foundation

final class ApprovalPersistence {
    private let stateURL: URL

    /// `directory` is injectable so the corrupt-file and history-preservation
    /// behaviour can be exercised against a temporary directory. Tests must never
    /// touch the real Application Support file.
    init(directory: URL? = nil) {
        let applicationSupport = FileManager.default.urls(
            for: .applicationSupportDirectory,
            in: .userDomainMask
        ).first ?? FileManager.default.temporaryDirectory
        let resolved = directory
            ?? applicationSupport.appendingPathComponent("Open Local Phraser", isDirectory: true)
        try? FileManager.default.createDirectory(at: resolved, withIntermediateDirectories: true)
        stateURL = resolved.appendingPathComponent("approved-state.json")
    }

    func loadState() -> [String: Any] {
        // An unreadable or corrupt file is not the same thing as an empty
        // history. Returning defaultState() for both made the UI silently drop
        // from "learned from N approved edits" to "learns from the edits you
        // approve" while still claiming private storage, so a corrupt file looked
        // exactly like a first run. Report the failure instead.
        guard FileManager.default.fileExists(atPath: stateURL.path) else {
            return defaultState()
        }

        do {
            let data = try Data(contentsOf: stateURL)
            let object = try JSONSerialization.jsonObject(with: data)
            guard let state = object as? [String: Any] else {
                throw NSError(
                    domain: "OpenLocalPhraser.Persistence",
                    code: 4,
                    userInfo: [NSLocalizedDescriptionKey: "The saved approval history is not in a readable format."]
                )
            }
            return state
        } catch {
            return [
                "ok": false,
                "error": "Your saved approvals could not be read on this Mac, so Pari is not using them.",
                "examples": [],
                "memory": [:],
            ]
        }
    }

    func saveApproval(payload: [String: Any]) throws -> [String: Any] {
        guard let record = payload["record"] as? [String: Any],
              let recordID = record["id"] as? String,
              let memory = payload["memory"] as? [String: Any]
        else {
            throw NSError(domain: "OpenLocalPhraser.Persistence", code: 1, userInfo: [
                NSLocalizedDescriptionKey: "Approval payload was invalid."
            ])
        }

        // loadState() reports an unreadable file as ok:false with empty
        // examples. Merging into that silently discarded the entire prior
        // history and wrote back a single record, so one save against a corrupt
        // file destroyed every approval the user had. Refuse instead: losing
        // history silently is far worse than refusing one save.
        let existing = loadState()
        if existing["ok"] as? Bool == false {
            throw NSError(domain: "OpenLocalPhraser.Persistence", code: 5, userInfo: [
                NSLocalizedDescriptionKey: "Your saved approvals could not be read, so this rewrite was not saved. Nothing was changed."
            ])
        }
        var examples = existing["examples"] as? [[String: Any]] ?? []
        examples.removeAll { ($0["id"] as? String) == recordID }
        examples.append(record)

        let nextState: [String: Any] = [
            "schemaVersion": 1,
            "examples": examples,
            "memory": memory,
        ]
        let data = try JSONSerialization.data(withJSONObject: nextState, options: [.prettyPrinted, .sortedKeys])
        try data.write(to: stateURL, options: .atomic)
        return nextState
    }

    private func defaultState() -> [String: Any] {
        let memory: [String: Any] = [
            "schemaVersion": 1,
            "approvedReplacements": [String: Any](),
            "revertedReplacements": [String: Any](),
            "phrasePreferences": [String: Any](),
            "avoidedPhrases": [String: Any](),
            "punctuation": [String: Any](),
            "contractions": [String: Any](),
            "sentenceLength": ["total": 0, "count": 0],
            "paragraphLength": ["total": 0, "count": 0],
            "sentenceStructure": [String: Any](),
            "lastUpdatedAt": NSNull(),
        ]
        return [
            "schemaVersion": 1,
            "examples": [[String: Any]](),
            "memory": memory,
        ]
    }
}
