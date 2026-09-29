import AppKit
import Darwin
import Foundation
import Network

struct AgentStyleTweaks: Codable {
    var strengthOffset: Int
    var warmthPolish: Bool
    var preserveSentenceCount: Bool

    init(strengthOffset: Int = 0, warmthPolish: Bool = false, preserveSentenceCount: Bool = true) {
        self.strengthOffset = strengthOffset
        self.warmthPolish = warmthPolish
        self.preserveSentenceCount = preserveSentenceCount
    }
}

struct AgentStyle: Codable {
    let id: String
    var name: String
    var description: String
    var instructions: String
    var baseMode: String
    var strength: Int
    var tweaks: AgentStyleTweaks
    let createdAt: String
    var updatedAt: String

    private enum CodingKeys: String, CodingKey {
        case id, name, description, instructions, baseMode, strength, tweaks, createdAt, updatedAt
    }

    init(id: String, name: String, description: String, instructions: String, baseMode: String, strength: Int, tweaks: AgentStyleTweaks, createdAt: String, updatedAt: String) {
        self.id = id
        self.name = name
        self.description = description
        self.instructions = instructions
        self.baseMode = baseMode
        self.strength = strength
        self.tweaks = tweaks
        self.createdAt = createdAt
        self.updatedAt = updatedAt
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        id = try container.decode(String.self, forKey: .id)
        name = try container.decode(String.self, forKey: .name)
        description = try container.decode(String.self, forKey: .description)
        instructions = try container.decode(String.self, forKey: .instructions)
        baseMode = try container.decode(String.self, forKey: .baseMode)
        strength = try container.decode(Int.self, forKey: .strength)
        tweaks = try container.decodeIfPresent(AgentStyleTweaks.self, forKey: .tweaks) ?? AgentStyleTweaks()
        createdAt = try container.decode(String.self, forKey: .createdAt)
        updatedAt = try container.decode(String.self, forKey: .updatedAt)
    }
}

private struct AgentStyleDocument: Codable {
    let schemaVersion: Int
    var styles: [AgentStyle]
}

struct AgentStyleInput: Codable {
    var name: String?
    var description: String?
    var instructions: String?
    var baseMode: String?
    var strength: Int?
    var tweaks: AgentStyleTweaks?
}

private struct AgentErrorResponse: Codable {
    let ok: Bool
    let error: String
}

private struct AgentStylesResponse: Codable {
    let ok: Bool
    let styles: [AgentStyle]
}

private struct AgentStyleResponse: Codable {
    let ok: Bool
    let style: AgentStyle
}

private struct AgentHealthResponse: Codable {
    let ok: Bool
    let service: String
    let schemaVersion: Int
    let stylesCount: Int
    let idleTimeoutSeconds: Int
    let lastActivityAt: String
}

private struct AgentDeleteResponse: Codable {
    let ok: Bool
    let deletedId: String
}

private struct AgentShutdownResponse: Codable {
    let ok: Bool
    let message: String
}

private struct AgentHTTPResponse {
    let status: Int
    let body: Data
    let contentType: String
}

final class AgentStyleStore {
    private let fileURL: URL
    private let encoder: JSONEncoder
    private let decoder: JSONDecoder

    init() {
        let applicationSupport = FileManager.default.urls(
            for: .applicationSupportDirectory,
            in: .userDomainMask
        ).first ?? FileManager.default.temporaryDirectory
        let directory = applicationSupport.appendingPathComponent("Open Local Phraser", isDirectory: true)
        try? FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        fileURL = directory.appendingPathComponent("custom-styles.json")

        encoder = JSONEncoder()
        encoder.outputFormatting = [.prettyPrinted, .sortedKeys]
        encoder.dateEncodingStrategy = .iso8601
        decoder = JSONDecoder()
        decoder.dateDecodingStrategy = .iso8601
    }

    func list() -> [AgentStyle] {
        load().styles.sorted { lhs, rhs in
            if lhs.updatedAt == rhs.updatedAt { return lhs.name.localizedCaseInsensitiveCompare(rhs.name) == .orderedAscending }
            return lhs.updatedAt > rhs.updatedAt
        }
    }

    func listPayload() -> [String: Any] {
        let encoder = JSONEncoder()
        guard let data = try? encoder.encode(list()),
              let styles = try? JSONSerialization.jsonObject(with: data) as? [[String: Any]]
        else {
            return ["ok": true, "styles": [[String: Any]]()]
        }
        return ["ok": true, "styles": styles]
    }

    func create(input: AgentStyleInput) throws -> AgentStyle {
        let now = Self.timestamp()
        var document = load()
        let normalized = try normalize(input: input, requireInstructions: true)
        let style = AgentStyle(
            id: UUID().uuidString.lowercased(),
            name: normalized.name,
            description: normalized.description,
            instructions: normalized.instructions,
            baseMode: normalized.baseMode,
            strength: normalized.strength,
            tweaks: normalized.tweaks,
            createdAt: now,
            updatedAt: now
        )
        document.styles.append(style)
        try save(document)
        return style
    }

    func update(id: String, input: AgentStyleInput) throws -> AgentStyle {
        var document = load()
        guard let index = document.styles.firstIndex(where: { $0.id == id }) else {
            throw AgentStyleStoreError.notFound
        }

        let current = document.styles[index]
        let merged = AgentStyleInput(
            name: input.name ?? current.name,
            description: input.description ?? current.description,
            instructions: input.instructions ?? current.instructions,
            baseMode: input.baseMode ?? current.baseMode,
            strength: input.strength ?? current.strength,
            tweaks: input.tweaks ?? current.tweaks
        )
        let normalized = try normalize(input: merged, requireInstructions: true)
        var updated = current
        updated.name = normalized.name
        updated.description = normalized.description
        updated.instructions = normalized.instructions
        updated.baseMode = normalized.baseMode
        updated.strength = normalized.strength
        updated.tweaks = normalized.tweaks
        updated.updatedAt = Self.timestamp()
        document.styles[index] = updated
        try save(document)
        return updated
    }

    func delete(id: String) throws {
        var document = load()
        let originalCount = document.styles.count
        document.styles.removeAll { $0.id == id }
        guard document.styles.count != originalCount else {
            throw AgentStyleStoreError.notFound
        }
        try save(document)
    }

    private func load() -> AgentStyleDocument {
        guard let data = try? Data(contentsOf: fileURL),
              let document = try? decoder.decode(AgentStyleDocument.self, from: data),
              document.schemaVersion == 1
        else {
            return AgentStyleDocument(schemaVersion: 1, styles: [])
        }
        return document
    }

    private func save(_ document: AgentStyleDocument) throws {
        let data = try encoder.encode(document)
        try data.write(to: fileURL, options: .atomic)
    }

    private func normalize(input: AgentStyleInput, requireInstructions: Bool) throws -> (name: String, description: String, instructions: String, baseMode: String, strength: Int, tweaks: AgentStyleTweaks) {
        let name = input.name?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        guard !name.isEmpty, name.count <= 80 else {
            throw AgentStyleStoreError.invalid("name must be 1–80 characters")
        }

        let description = input.description?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        guard description.count <= 320 else {
            throw AgentStyleStoreError.invalid("description must be at most 320 characters")
        }

        let instructions = input.instructions?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        if requireInstructions {
            guard !instructions.isEmpty, instructions.count <= 4_000 else {
                throw AgentStyleStoreError.invalid("instructions must be 1–4,000 characters")
            }
        }

        let baseMode = input.baseMode?.trimmingCharacters(in: .whitespacesAndNewlines).lowercased() ?? "personal"
        guard ["personal", "warmth"].contains(baseMode) else {
            throw AgentStyleStoreError.invalid("baseMode must be personal or warmth")
        }

        let strength = input.strength ?? 56
        guard (0...100).contains(strength) else {
            throw AgentStyleStoreError.invalid("strength must be between 0 and 100")
        }

        let rawTweaks = input.tweaks ?? AgentStyleTweaks()
        guard (-24...24).contains(rawTweaks.strengthOffset) else {
            throw AgentStyleStoreError.invalid("tweaks.strengthOffset must be between -24 and 24")
        }

        return (name, description, instructions, baseMode, strength, rawTweaks)
    }

    private static func timestamp() -> String {
        ISO8601DateFormatter().string(from: Date())
    }
}

enum AgentStyleStoreError: LocalizedError {
    case invalid(String)
    case notFound

    var errorDescription: String? {
        switch self {
        case .invalid(let message): return message
        case .notFound: return "The requested custom style was not found."
        }
    }
}

final class AgentStyleBackend {
    private let store: AgentStyleStore
    private let queue = DispatchQueue(label: "com.tejas.pari.agent-style-backend")
    private let idleTimeout: TimeInterval
    private var listener: NWListener?
    private var idleTimer: DispatchSourceTimer?
    private var lastActivity = Date()
    private var onIdleShutdown: (() -> Void)?

    init(idleTimeout: TimeInterval = 600, onIdleShutdown: (() -> Void)? = nil) {
        store = AgentStyleStore()
        self.idleTimeout = max(1, idleTimeout)
        self.onIdleShutdown = onIdleShutdown
    }

    func start(completion: @escaping (Result<UInt16, Error>) -> Void) {
        do {
            let parameters = NWParameters.tcp
            parameters.requiredInterfaceType = .loopback
            let listener = try NWListener(using: parameters, on: .any)
            self.listener = listener
            lastActivity = Date()

            var completed = false
            listener.stateUpdateHandler = { [weak self] state in
                switch state {
                case .ready:
                    guard !completed, let port = listener.port?.rawValue else { return }
                    completed = true
                    self?.startIdleTimer()
                    completion(.success(port))
                case .failed(let error):
                    guard !completed else { return }
                    completed = true
                    self?.stop()
                    completion(.failure(error))
                case .cancelled:
                    guard !completed else { return }
                    completed = true
                    completion(.failure(URLError(.cancelled)))
                default:
                    break
                }
            }
            listener.newConnectionHandler = { [weak self] connection in
                self?.handle(connection)
            }
            listener.start(queue: queue)
        } catch {
            completion(.failure(error))
        }
    }

    func stop() {
        listener?.cancel()
        listener = nil
        idleTimer?.cancel()
        idleTimer = nil
    }

    private func startIdleTimer() {
        let timer = DispatchSource.makeTimerSource(queue: queue)
        timer.schedule(deadline: .now() + min(30, idleTimeout), repeating: min(30, idleTimeout))
        timer.setEventHandler { [weak self] in
            guard let self else { return }
            guard Date().timeIntervalSince(self.lastActivity) >= self.idleTimeout else { return }
            self.stop()
            self.onIdleShutdown?()
        }
        idleTimer = timer
        timer.resume()
    }

    private func touch() {
        lastActivity = Date()
    }

    private func handle(_ connection: NWConnection) {
        connection.stateUpdateHandler = { state in
            if case .failed = state { connection.cancel() }
        }
        connection.start(queue: queue)
        receiveRequest(on: connection, buffered: Data())
    }

    private func receiveRequest(on connection: NWConnection, buffered: Data) {
        connection.receive(minimumIncompleteLength: 1, maximumLength: 131_072) { [weak self] data, _, isComplete, error in
            guard let self else {
                connection.cancel()
                return
            }
            if error != nil {
                connection.cancel()
                return
            }

            var requestData = buffered
            if let data { requestData.append(data) }
            guard let headerEnd = requestData.range(of: Data("\r\n\r\n".utf8)) else {
                if isComplete || requestData.count > 131_072 {
                    self.send(AgentHTTPResponse(status: 400, body: Data("Bad request".utf8), contentType: "text/plain; charset=utf-8"), on: connection)
                } else {
                    self.receiveRequest(on: connection, buffered: requestData)
                }
                return
            }

            let headerData = requestData.prefix(upTo: headerEnd.lowerBound)
            let bodyStart = headerEnd.upperBound
            let body = requestData.suffix(from: bodyStart)
            guard let request = self.parseRequest(headerData: headerData) else {
                self.send(AgentHTTPResponse(status: 400, body: Data("Bad request".utf8), contentType: "text/plain; charset=utf-8"), on: connection)
                return
            }

            let expectedBodyLength = request.contentLength
            guard expectedBodyLength <= 65_536 else {
                self.send(AgentHTTPResponse(status: 413, body: Data("Request body too large".utf8), contentType: "text/plain; charset=utf-8"), on: connection)
                return
            }
            if body.count < expectedBodyLength {
                self.receiveRequest(on: connection, buffered: requestData)
                return
            }

            self.touch()
            let requestBody = Data(body.prefix(expectedBodyLength))
            let response = self.respond(method: request.method, target: request.target, body: requestBody)
            self.send(response, on: connection)
        }
    }

    private struct ParsedRequest {
        let method: String
        let target: String
        let contentLength: Int
    }

    private func parseRequest(headerData: Data) -> ParsedRequest? {
        guard let header = String(data: headerData, encoding: .utf8) else { return nil }
        let lines = header.components(separatedBy: "\r\n")
        guard let requestLine = lines.first else { return nil }
        let fields = requestLine.split(separator: " ", maxSplits: 2, omittingEmptySubsequences: true)
        guard fields.count == 3 else { return nil }

        var contentLength = 0
        for line in lines.dropFirst() {
            let parts = line.split(separator: ":", maxSplits: 1, omittingEmptySubsequences: true)
            guard parts.count == 2 else { continue }
            if parts[0].trimmingCharacters(in: .whitespacesAndNewlines).lowercased() == "content-length" {
                guard let value = Int(parts[1].trimmingCharacters(in: .whitespacesAndNewlines)), value >= 0 else { return nil }
                contentLength = value
            }
        }
        return ParsedRequest(method: String(fields[0]).uppercased(), target: String(fields[1]), contentLength: contentLength)
    }

    private func respond(method: String, target: String, body: Data) -> AgentHTTPResponse {
        if method == "OPTIONS" {
            return AgentHTTPResponse(status: 204, body: Data(), contentType: "text/plain")
        }
        guard ["GET", "POST", "PATCH", "DELETE"].contains(method) else {
            return json(status: 405, value: AgentErrorResponse(ok: false, error: "Method not allowed"))
        }

        let path = target.split(separator: "?", maxSplits: 1, omittingEmptySubsequences: false).first.map(String.init) ?? "/"
        let decodedPath = path.removingPercentEncoding ?? path
        let components = decodedPath.split(separator: "/", omittingEmptySubsequences: true).map(String.init)

        if method == "GET", decodedPath == "/health" {
            let timestamp = ISO8601DateFormatter().string(from: lastActivity)
            return json(status: 200, value: AgentHealthResponse(
                ok: true,
                service: "pari-agent-style-backend",
                schemaVersion: 1,
                stylesCount: store.list().count,
                idleTimeoutSeconds: Int(idleTimeout),
                lastActivityAt: timestamp
            ))
        }

        if method == "GET", decodedPath == "/v1/styles" {
            return json(status: 200, value: AgentStylesResponse(ok: true, styles: store.list()))
        }

        if method == "POST", decodedPath == "/v1/styles" {
            do {
                let input = try decodeInput(body)
                return json(status: 201, value: AgentStyleResponse(ok: true, style: try store.create(input: input)))
            } catch {
                return errorResponse(error, fallback: "Could not create custom style.")
            }
        }

        if components.count == 3, components[0] == "v1", components[1] == "styles" {
            let id = components[2]
            if method == "PATCH" {
                do {
                    let input = try decodeInput(body)
                    return json(status: 200, value: AgentStyleResponse(ok: true, style: try store.update(id: id, input: input)))
                } catch {
                    return errorResponse(error, fallback: "Could not update custom style.")
                }
            }
            if method == "DELETE" {
                do {
                    try store.delete(id: id)
                    return json(status: 200, value: AgentDeleteResponse(ok: true, deletedId: id))
                } catch {
                    return errorResponse(error, fallback: "Could not delete custom style.")
                }
            }
        }

        if method == "POST", decodedPath == "/v1/shutdown" {
            DispatchQueue.main.async { [weak self] in
                self?.stop()
                NSApp.terminate(nil)
            }
            return json(status: 202, value: AgentShutdownResponse(ok: true, message: "The style backend is shutting down."))
        }

        return json(status: 404, value: AgentErrorResponse(ok: false, error: "Not found"))
    }

    private func decodeInput(_ body: Data) throws -> AgentStyleInput {
        guard !body.isEmpty else { throw AgentStyleStoreError.invalid("A JSON style body is required") }
        do {
            return try JSONDecoder().decode(AgentStyleInput.self, from: body)
        } catch {
            throw AgentStyleStoreError.invalid("The style body must be valid JSON")
        }
    }

    private func errorResponse(_ error: Error, fallback: String) -> AgentHTTPResponse {
        let status: Int
        if case AgentStyleStoreError.notFound = error {
            status = 404
        } else if error is AgentStyleStoreError {
            status = 422
        } else {
            status = 500
        }
        return json(status: status, value: AgentErrorResponse(ok: false, error: error.localizedDescription.isEmpty ? fallback : error.localizedDescription))
    }

    private func json<T: Encodable>(status: Int, value: T) -> AgentHTTPResponse {
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.sortedKeys]
        let data = (try? encoder.encode(value)) ?? Data("{\"ok\":false,\"error\":\"Could not encode response\"}".utf8)
        return AgentHTTPResponse(status: status, body: data, contentType: "application/json; charset=utf-8")
    }

    private func send(_ response: AgentHTTPResponse, on connection: NWConnection) {
        let statusText: String
        switch response.status {
        case 200: statusText = "OK"
        case 201: statusText = "Created"
        case 202: statusText = "Accepted"
        case 204: statusText = "No Content"
        case 404: statusText = "Not Found"
        case 405: statusText = "Method Not Allowed"
        case 413: statusText = "Payload Too Large"
        case 422: statusText = "Unprocessable Entity"
        default: statusText = "Error"
        }
        let header = "HTTP/1.1 \(response.status) \(statusText)\r\nContent-Type: \(response.contentType)\r\nContent-Length: \(response.body.count)\r\nCache-Control: no-store\r\nAccess-Control-Allow-Origin: *\r\nAccess-Control-Allow-Methods: GET, POST, PATCH, DELETE, OPTIONS\r\nAccess-Control-Allow-Headers: Content-Type\r\nConnection: close\r\n\r\n"
        connection.send(content: Data(header.utf8), completion: .contentProcessed { [weak self] error in
            if error != nil {
                connection.cancel()
                return
            }
            if response.body.isEmpty {
                connection.cancel()
                return
            }
            connection.send(content: response.body, completion: .contentProcessed { _ in
                connection.cancel()
                _ = self
            })
        })
    }
}
