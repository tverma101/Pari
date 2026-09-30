import AppKit
import Darwin
import Foundation
import Network
import WebKit

private let unconfiguredNativeModelID = "unconfigured-native-model"
private let unconfiguredNativeModelPath = "native-models/unconfigured"

final class LocalWebServer {
    private let rootDirectory: URL
    private let queue = DispatchQueue(label: "com.tejas.pari.local-web-server")
    private var listener: NWListener?

    init(rootDirectory: URL) {
        self.rootDirectory = rootDirectory
    }

    func start(completion: @escaping (Result<UInt16, Error>) -> Void) {
        do {
            let parameters = NWParameters.tcp
            parameters.requiredInterfaceType = .loopback
            let listener = try NWListener(using: parameters, on: .any)
            self.listener = listener
            var completed = false
            listener.stateUpdateHandler = { [weak self] state in
                switch state {
                case .ready:
                    guard !completed, let port = listener.port?.rawValue else { return }
                    completed = true
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
    }

    private func handle(_ connection: NWConnection) {
        connection.stateUpdateHandler = { state in
            if case .failed = state {
                connection.cancel()
            }
        }
        connection.start(queue: queue)
        receiveRequest(on: connection, buffered: Data())
    }

    private func receiveRequest(on connection: NWConnection, buffered: Data) {
        connection.receive(minimumIncompleteLength: 1, maximumLength: 65_536) { [weak self] data, _, isComplete, error in
            guard let self else {
                connection.cancel()
                return
            }

            if let error {
                NSLog("[OpenLocalPhraser] local server receive error \(error.localizedDescription)")
                connection.cancel()
                return
            }

            var requestData = buffered
            if let data {
                requestData.append(data)
            }

            if let headerEnd = requestData.range(of: Data("\r\n\r\n".utf8)) {
                self.respond(to: requestData.prefix(upTo: headerEnd.lowerBound), on: connection)
                return
            }

            if isComplete || requestData.count > 65_536 {
                self.send(status: 400, body: Data("Bad request".utf8), contentType: "text/plain", on: connection)
                return
            }

            self.receiveRequest(on: connection, buffered: requestData)
        }
    }

    private func respond(to headerData: Data, on connection: NWConnection) {
        guard let header = String(data: headerData, encoding: .utf8),
              let requestLine = header.components(separatedBy: "\r\n").first
        else {
            send(status: 400, body: Data("Bad request".utf8), contentType: "text/plain", on: connection)
            return
        }

        let fields = requestLine.split(separator: " ", maxSplits: 2, omittingEmptySubsequences: true)
        guard fields.count >= 2, fields[0] == "GET" || fields[0] == "HEAD" || fields[0] == "OPTIONS" else {
            send(status: 405, body: Data("Method not allowed".utf8), contentType: "text/plain", on: connection)
            return
        }

        if fields[0] == "OPTIONS" {
            send(status: 204, body: Data(), contentType: "text/plain", on: connection)
            return
        }

        let target = String(fields[1]).split(separator: "?", maxSplits: 1, omittingEmptySubsequences: false).first.map(String.init) ?? "/"
        let path = target.removingPercentEncoding ?? target
        let relativePath = path == "/" ? "index.html" : String(path.drop { $0 == "/" })
        let components = relativePath.split(separator: "/", omittingEmptySubsequences: true)
        guard !relativePath.contains("\0"), !components.contains(".."), !relativePath.hasPrefix("/") else {
            send(status: 403, body: Data("Forbidden".utf8), contentType: "text/plain", on: connection)
            return
        }

        let requestedFile = rootDirectory.appendingPathComponent(relativePath)
        let resolvedFile = requestedFile.resolvingSymlinksInPath()
        let rootPath = rootDirectory.resolvingSymlinksInPath().path
        guard resolvedFile.path == rootPath || resolvedFile.path.hasPrefix(rootPath + "/"),
              let body = try? Data(contentsOf: resolvedFile)
        else {
            send(status: 404, body: Data("Not found".utf8), contentType: "text/plain", on: connection)
            return
        }

        send(
            status: 200,
            body: fields[0] == "HEAD" ? Data() : body,
            contentType: mimeType(for: resolvedFile),
            contentLength: body.count,
            on: connection
        )
    }

    private func send(status: Int, body: Data, contentType: String, contentLength: Int? = nil, on connection: NWConnection) {
        let responseBodyLength = contentLength ?? body.count
        let header = "HTTP/1.1 \(status) \(statusText(for: status))\r\nContent-Type: \(contentType)\r\nContent-Length: \(responseBodyLength)\r\nCache-Control: no-cache\r\nAccess-Control-Allow-Origin: *\r\nAccess-Control-Allow-Methods: GET, HEAD, OPTIONS\r\nAccess-Control-Allow-Headers: *\r\nConnection: close\r\n\r\n"
        let headerData = Data(header.utf8)
        connection.send(content: headerData, completion: .contentProcessed { error in
            if let error {
                NSLog("[OpenLocalPhraser] local server send error \(error.localizedDescription)")
                connection.cancel()
                return
            }

            guard !body.isEmpty else {
                connection.cancel()
                return
            }

            connection.send(content: body, completion: .contentProcessed { _ in
                connection.cancel()
            })
        })
    }

    private func statusText(for status: Int) -> String {
        switch status {
        case 200: return "OK"
        case 204: return "No Content"
        case 400: return "Bad Request"
        case 403: return "Forbidden"
        case 404: return "Not Found"
        case 405: return "Method Not Allowed"
        default: return "Error"
        }
    }

    private func mimeType(for url: URL) -> String {
        switch url.pathExtension.lowercased() {
        case "html", "htm": return "text/html; charset=utf-8"
        case "css": return "text/css; charset=utf-8"
        case "js", "mjs": return "text/javascript; charset=utf-8"
        case "json": return "application/json; charset=utf-8"
        case "wasm": return "application/wasm"
        case "onnx": return "application/octet-stream"
        case "txt": return "text/plain; charset=utf-8"
        default: return "application/octet-stream"
        }
    }
}

final class BundleSchemeHandler: NSObject, WKURLSchemeHandler {
    private let webDirectory: URL

    init(webDirectory: URL) {
        self.webDirectory = webDirectory
        super.init()
    }

    func webView(_ webView: WKWebView, start urlSchemeTask: WKURLSchemeTask) {
        let requestPath = urlSchemeTask.request.url?.path ?? "/"
        let normalizedPath = requestPath == "/"
            ? "index.html"
            : String(requestPath.drop { $0 == "/" })
        let requestedFileURL = webDirectory.appendingPathComponent(normalizedPath)

        // Security: ensure resolved path is within webDirectory
        let resolvedPath = requestedFileURL.resolvingSymlinksInPath()
        let webDirPath = webDirectory.resolvingSymlinksInPath().path
        guard resolvedPath.path == webDirPath || resolvedPath.path.hasPrefix(webDirPath + "/") else {
            urlSchemeTask.didFailWithError(URLError(.noPermissionsToReadFile))
            return
        }

        guard FileManager.default.fileExists(atPath: resolvedPath.path),
              let data = try? Data(contentsOf: resolvedPath)
        else {
            urlSchemeTask.didFailWithError(URLError(.fileDoesNotExist))
            return
        }

        let mimeType = mimeTypeForPath(resolvedPath)
        let contentType = contentTypeHeader(for: mimeType)
        guard let response = HTTPURLResponse(
            url: urlSchemeTask.request.url!,
            statusCode: 200,
            httpVersion: "HTTP/1.1",
            headerFields: [
                "Content-Type": contentType,
                "Content-Length": "\(data.count)",
                "Cache-Control": "no-cache",
            ]
        ) else {
            urlSchemeTask.didFailWithError(URLError(.badServerResponse))
            return
        }

        urlSchemeTask.didReceive(response)
        urlSchemeTask.didReceive(data)
        urlSchemeTask.didFinish()
    }

    func webView(_ webView: WKWebView, stop urlSchemeTask: WKURLSchemeTask) {}

    private func mimeTypeForPath(_ url: URL) -> String {
        let ext = url.pathExtension.lowercased()
        switch ext {
        case "html", "htm":  return "text/html"
        case "css":          return "text/css"
        case "js":           return "application/javascript"
        case "mjs":          return "application/javascript"
        case "json":         return "application/json"
        case "png":          return "image/png"
        case "jpg", "jpeg":  return "image/jpeg"
        case "gif":          return "image/gif"
        case "svg":          return "image/svg+xml"
        case "ico":          return "image/x-icon"
        case "woff":         return "font/woff"
        case "woff2":        return "font/woff2"
        case "wasm":         return "application/wasm"
        case "onnx":         return "application/octet-stream"
        case "txt":          return "text/plain"
        case "xml":          return "application/xml"
        case "map":          return "application/json"
        default:             return "application/octet-stream"
        }
    }

    private func contentTypeHeader(for mimeType: String) -> String {
        if mimeType.hasPrefix("text/")
            || mimeType == "application/javascript"
            || mimeType == "application/json"
            || mimeType == "application/xml" {
            return "\(mimeType); charset=utf-8"
        }

        return mimeType
    }
}

final class ApprovalPersistence {
    private let stateURL: URL

    init() {
        let applicationSupport = FileManager.default.urls(
            for: .applicationSupportDirectory,
            in: .userDomainMask
        ).first ?? FileManager.default.temporaryDirectory
        let directory = applicationSupport.appendingPathComponent("Open Local Phraser", isDirectory: true)
        try? FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        stateURL = directory.appendingPathComponent("approved-state.json")
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

        let existing = loadState()
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

final class AppDelegate: NSObject, NSApplicationDelegate, WKNavigationDelegate, WKScriptMessageHandler {
    private let appName = "Pari"
    private let headless = CommandLine.arguments.contains("--headless")
    private let headlessCustomStyle = CommandLine.arguments.contains("--headless-custom-style")
    private let headlessMissingModel = CommandLine.arguments.contains("--headless-missing-model")
    private let headlessRequireNative = CommandLine.arguments.contains("--headless-require-native")
    private let headlessFreeLLM = CommandLine.arguments.contains("--headless-freellm")
    private let headlessOllama = CommandLine.arguments.contains("--headless-ollama")
    private let headlessCustomStyleName = ProcessInfo.processInfo.environment["PARI_HEADLESS_CUSTOM_STYLE_NAME"] ?? "QA Warm Direct"
    private let agentStyleBackendRequested = CommandLine.arguments.contains("--agent-style-backend")
    private let headlessInput: String = {
        let environment = ProcessInfo.processInfo.environment
        let remoteRequested = CommandLine.arguments.contains("--headless-freellm")
            || CommandLine.arguments.contains("--headless-ollama")
            || environment["PARI_GENERATION_BACKEND"]?.trimmingCharacters(in: .whitespacesAndNewlines).lowercased() == "freellm"
            || environment["PARI_GENERATION_BACKEND"]?.trimmingCharacters(in: .whitespacesAndNewlines).lowercased() == "ollama"
            || environment["PARI_FREELLM_ENABLED"] == "1"
        if remoteRequested {
            // Keep the installed remote-path smoke deterministic and focused
            // on proving the route, while the full adversarial shootout covers
            // long ADHD-style paragraphs and hard safety cases separately.
            return "The package arrived yesterday but it was damaged."
        }
        return "My ADHD makes it difficult for me to sustain attention for long periods, stay focused when there are distractions, organize tasks and assignments, and remember information or instructions. I can also have difficulty listening continuously during lectures and completing work that requires sustained mental effort. These symptoms can affect my test performance, note-taking, time management, and ability to keep up with longer assignments."
    }()
    private let consoleHandlerName = "openLocalPhraserConsole"
    private let nativeHandlerName = "openLocalPhraserNative"
    private let clipboardHandlerName = "openLocalPhraserClipboard"
    private let scheme = "app"
    private let approvalPersistence = ApprovalPersistence()
    private let agentStyleStore = AgentStyleStore()
    private let nativeModelPathOverride: URL? = {
        guard let value = ProcessInfo.processInfo.environment["PARI_NATIVE_MODEL_PATH"],
              !value.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
        else { return nil }
        let expanded = (value as NSString).expandingTildeInPath
        if expanded.hasPrefix("/") {
            return URL(fileURLWithPath: expanded).standardizedFileURL
        }
        return URL(fileURLWithPath: FileManager.default.currentDirectoryPath)
            .appendingPathComponent(expanded)
            .standardizedFileURL
    }()
    private let nativeModelID: String = {
        // Precedence: env > config > fallback (matches scripts). Env must override config.
        if let env = ProcessInfo.processInfo.environment["PARI_NATIVE_MODEL_ID"], !env.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
            return env.trimmingCharacters(in: .whitespacesAndNewlines)
        }
        if let resourceURL = Bundle.main.resourceURL,
           let data = try? Data(contentsOf: resourceURL.appendingPathComponent("native-models/config.json")),
           let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
           let native = json["nativeModel"] as? [String: Any],
           let id = native["id"] as? String, !id.isEmpty { return id }
        return unconfiguredNativeModelID
    }()
    private let nativeModelRelativePath: String = {
        if let resourceURL = Bundle.main.resourceURL,
           let data = try? Data(contentsOf: resourceURL.appendingPathComponent("native-models/config.json")),
           let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
           let native = json["nativeModel"] as? [String: Any],
           let p = native["localPath"] as? String, !p.isEmpty { return p }
        return unconfiguredNativeModelPath
    }()
    private let nativeWorkerRelativePath = "native-runtime/paraphrase_worker.py"
    private let nativeMtpWorkerRelativePath = "native-runtime/mtp_paraphrase_worker.py"
    private let freeLLMWorkerRelativePath = "native-runtime/freellm_worker.py"
    private let ollamaWorkerRelativePath = "native-runtime/ollama_worker.py"
    private let nativeModelRequiredFiles = [
        "manifest.json",
        "config.json",
        "model.safetensors",
        "model.safetensors.index.json",
        "tokenizer.json",
        "tokenizer_config.json",
    ]
    private let nativeGenerationQueue = DispatchQueue(
        label: "com.tejas.pari.native-generation",
        qos: .userInitiated
    )

    private lazy var webDirectory: URL = {
        Bundle.main.resourceURL!.appendingPathComponent("web", isDirectory: true)
    }()

    private lazy var indexURL: URL = {
        webDirectory.appendingPathComponent("index.html")
    }()

    private lazy var assetsDirectory: URL = {
        webDirectory.appendingPathComponent("assets", isDirectory: true)
    }()

    private lazy var modelDirectory: URL = {
        webDirectory.appendingPathComponent("models", isDirectory: true)
    }()

    private lazy var nativeModelInstallDirectory: URL = {
        if let nativeModelPathOverride {
            return nativeModelPathOverride
        }
        let applicationSupport = FileManager.default.urls(
            for: .applicationSupportDirectory,
            in: .userDomainMask
        ).first ?? FileManager.default.temporaryDirectory
        return applicationSupport
            .appendingPathComponent("Open Local Phraser", isDirectory: true)
            .appendingPathComponent("Models", isDirectory: true)
            .appendingPathComponent(nativeModelRelativePath, isDirectory: true)
    }()

    private var window: NSWindow?
    private var webView: WKWebView?
    private var localWebServer: LocalWebServer?
    private var localWebServerURL: URL?
    private var headlessContextRequested = false
    private var headlessGrammarProbeStarted = false
    private var nativeProcesses: [Int: Process] = [:]
    private var agentStyleBackend: AgentStyleBackend?

    private var freellmRequested: Bool {
        if headlessFreeLLM { return true }
        let environment = ProcessInfo.processInfo.environment
        let backend = environment["PARI_GENERATION_BACKEND"]?.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        if backend == "ollama" { return false }
        return backend == "freellm"
            || environment["PARI_FREELLM_ENABLED"] == "1"
    }

    private var ollamaRequested: Bool {
        if headlessOllama { return true }
        let environment = ProcessInfo.processInfo.environment
        return environment["PARI_GENERATION_BACKEND"]?.trimmingCharacters(in: .whitespacesAndNewlines).lowercased() == "ollama"
    }

    private var headlessExpectedGenerationSource: String {
        if ollamaRequested { return "ollama" }
        if freellmRequested { return "freellm-api" }
        if headlessRequireNative { return "native-mlx" }
        return nativeModelURL() == nil ? "local-safe-engine" : "native-mlx"
    }

    func applicationDidFinishLaunching(_ notification: Notification) {
        if agentStyleBackendRequested {
            NSApp.setActivationPolicy(.accessory)
            startAgentStyleBackend()
            return
        }

        NSApp.setActivationPolicy(headless ? .accessory : .regular)
        if !headless {
            configureApplicationMenu()
        }
        buildWindow()
        startLocalWebServer()
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool {
        true
    }

    deinit {
        webView?.configuration.userContentController.removeScriptMessageHandler(forName: consoleHandlerName)
        webView?.configuration.userContentController.removeScriptMessageHandler(forName: nativeHandlerName)
        webView?.configuration.userContentController.removeScriptMessageHandler(forName: clipboardHandlerName)
    }

    func userContentController(_ userContentController: WKUserContentController, didReceive message: WKScriptMessage) {
        if message.name == clipboardHandlerName {
            handleClipboardMessage(message)
            return
        }

        if message.name == nativeHandlerName {
            handleNativeMessage(message)
            return
        }

        guard message.name == consoleHandlerName else { return }

        if let payload = message.body as? [String: Any] {
            let level = payload["level"] as? String ?? "log"
            let text = payload["message"] as? String ?? String(describing: payload)
            log("web[\(level)] \(text)")
        } else {
            log("web \(String(describing: message.body))")
        }
    }

    func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
        log("navigation finished \(webView.url?.absoluteString ?? "<unknown>")")
        if headless {
            runHeadlessSmokeTest()
        }
    }

    func webView(
        _ webView: WKWebView,
        decidePolicyFor navigationAction: WKNavigationAction,
        decisionHandler: @escaping (WKNavigationActionPolicy) -> Void
    ) {
        guard let url = navigationAction.request.url else {
            log("blocked navigation \(navigationAction.request.url?.absoluteString ?? "<unknown>")")
            decisionHandler(.cancel)
            return
        }

        let isLocalServerURL = url.scheme == "http"
            && url.host == localWebServerURL?.host
            && url.port == localWebServerURL?.port
        guard isLocalServerURL else {
            log("blocked navigation \(url.absoluteString)")
            decisionHandler(.cancel)
            return
        }

        decisionHandler(.allow)
    }

    func webView(
        _ webView: WKWebView,
        didFail navigation: WKNavigation!,
        withError error: Error
    ) {
        log("navigation failed \(error.localizedDescription)")
        showErrorPage(
            title: "Could not launch Pari",
            message: error.localizedDescription
        )
    }

    func webView(
        _ webView: WKWebView,
        didFailProvisionalNavigation navigation: WKNavigation!,
        withError error: Error
    ) {
        log("provisional navigation failed \(error.localizedDescription)")
        showErrorPage(
            title: "Could not launch Pari",
            message: error.localizedDescription
        )
    }

    func webViewWebContentProcessDidTerminate(_ webView: WKWebView) {
        log("web content process terminated")
        showErrorPage(
            title: "Pari stopped unexpectedly",
            message: "The embedded web content process terminated before the app finished rendering."
        )
    }

    private func buildWindow() {
        let configuration = WKWebViewConfiguration()
        configuration.websiteDataStore = .default()
        configuration.defaultWebpagePreferences.allowsContentJavaScript = true
        configuration.preferences.javaScriptCanOpenWindowsAutomatically = false

        let schemeHandler = BundleSchemeHandler(webDirectory: webDirectory)
        configuration.setURLSchemeHandler(schemeHandler, forURLScheme: scheme)

        let contentController = WKUserContentController()
        contentController.add(self, name: consoleHandlerName)
        contentController.add(self, name: nativeHandlerName)
        contentController.add(self, name: clipboardHandlerName)
        contentController.addUserScript(
            WKUserScript(
                source: makeBootDiagnosticsScript(),
                injectionTime: .atDocumentStart,
                forMainFrameOnly: true
            )
        )
        contentController.addUserScript(
            WKUserScript(
                source: makeConsoleBridgeScript(),
                injectionTime: .atDocumentStart,
                forMainFrameOnly: false
            )
        )
        configuration.userContentController = contentController

        let webView = WKWebView(frame: .zero, configuration: configuration)
        webView.frame = NSRect(x: 0, y: 0, width: 1380, height: 920)
        webView.autoresizingMask = [.width, .height]
        webView.navigationDelegate = self
        webView.setValue(true, forKey: "drawsBackground")

        let window = NSWindow(
            contentRect: NSRect(x: 0, y: 0, width: 1380, height: 920),
            styleMask: [.titled, .closable, .miniaturizable, .resizable],
            backing: .buffered,
            defer: false
        )
        window.title = appName
        window.titleVisibility = .visible
        window.contentView = webView
        window.center()
        if headless {
            // Keep the installed-app smoke test isolated from the user's desktop.
            // The normal launch path below remains unchanged.
            window.orderOut(nil)
        } else {
            window.makeKeyAndOrderFront(nil)
            window.makeFirstResponder(webView)
        }

        self.window = window
        self.webView = webView
        if !headless {
            NSApp.activate(ignoringOtherApps: true)
        }
    }

    private func configureApplicationMenu() {
        let mainMenu = NSMenu(title: appName)

        let appMenuItem = NSMenuItem()
        let appMenu = NSMenu(title: appName)
        appMenuItem.submenu = appMenu
        mainMenu.addItem(appMenuItem)

        let aboutItem = NSMenuItem(
            title: "About (appName)",
            action: #selector(NSApplication.orderFrontStandardAboutPanel(_:)),
            keyEquivalent: ""
        )
        aboutItem.target = NSApp
        appMenu.addItem(aboutItem)
        appMenu.addItem(.separator())

        let servicesItem = NSMenuItem(title: "Services", action: nil, keyEquivalent: "")
        let servicesMenu = NSMenu(title: "Services")
        servicesItem.submenu = servicesMenu
        appMenu.addItem(servicesItem)
        NSApp.servicesMenu = servicesMenu

        appMenu.addItem(.separator())
        let hideItem = NSMenuItem(
            title: "Hide (appName)",
            action: #selector(NSApplication.hide(_:)),
            keyEquivalent: "h"
        )
        hideItem.target = NSApp
        appMenu.addItem(hideItem)

        let hideOthersItem = NSMenuItem(
            title: "Hide Others",
            action: #selector(NSApplication.hideOtherApplications(_:)),
            keyEquivalent: "h"
        )
        hideOthersItem.keyEquivalentModifierMask = [.command, .option]
        hideOthersItem.target = NSApp
        appMenu.addItem(hideOthersItem)

        let showAllItem = NSMenuItem(
            title: "Show All",
            action: #selector(NSApplication.unhideAllApplications(_:)),
            keyEquivalent: ""
        )
        showAllItem.target = NSApp
        appMenu.addItem(showAllItem)

        appMenu.addItem(.separator())
        let quitItem = NSMenuItem(
            title: "Quit (appName)",
            action: #selector(NSApplication.terminate(_:)),
            keyEquivalent: "q"
        )
        quitItem.target = NSApp
        appMenu.addItem(quitItem)

        let editMenuItem = NSMenuItem()
        let editMenu = NSMenu(title: "Edit")
        editMenuItem.submenu = editMenu
        mainMenu.addItem(editMenuItem)

        editMenu.addItem(menuItem(title: "Undo", action: "undo:", key: "z"))
        let redoItem = menuItem(title: "Redo", action: "redo:", key: "z")
        redoItem.keyEquivalentModifierMask = [.command, .shift]
        editMenu.addItem(redoItem)
        editMenu.addItem(.separator())
        editMenu.addItem(menuItem(title: "Cut", action: "cut:", key: "x"))
        editMenu.addItem(menuItem(title: "Copy", action: "copy:", key: "c"))
        editMenu.addItem(menuItem(title: "Paste", action: "paste:", key: "v"))
        editMenu.addItem(menuItem(title: "Paste and Match Style", action: "pasteAsPlainText:", key: "v", modifiers: [.command, .option]))
        editMenu.addItem(menuItem(title: "Delete", action: "delete:", key: ""))
        editMenu.addItem(.separator())
        editMenu.addItem(menuItem(title: "Select All", action: "selectAll:", key: "a"))

        let windowMenuItem = NSMenuItem()
        let windowMenu = NSMenu(title: "Window")
        windowMenuItem.submenu = windowMenu
        mainMenu.addItem(windowMenuItem)
        windowMenu.addItem(NSMenuItem(
            title: "Minimize",
            action: #selector(NSWindow.performMiniaturize(_:)),
            keyEquivalent: "m"
        ))
        windowMenu.addItem(NSMenuItem(
            title: "Zoom",
            action: #selector(NSWindow.performZoom(_:)),
            keyEquivalent: ""
        ))
        windowMenu.addItem(.separator())
        windowMenu.addItem(NSMenuItem(
            title: "Bring All to Front",
            action: #selector(NSApplication.arrangeInFront(_:)),
            keyEquivalent: ""
        ))
        NSApp.windowsMenu = windowMenu

        NSApp.mainMenu = mainMenu
    }

    private func menuItem(
        title: String,
        action: String,
        key: String,
        modifiers: NSEvent.ModifierFlags = [.command]
    ) -> NSMenuItem {
        let item = NSMenuItem(title: title, action: Selector(action), keyEquivalent: key)
        item.keyEquivalentModifierMask = modifiers
        return item
    }

    private func loadBundledSite() {
        logStartupDiagnostics()

        guard directoryExists(webDirectory) else {
            showErrorPage(
                title: "Could not launch Pari",
                message: "The bundled web directory was not found at \(webDirectory.path)."
            )
            return
        }

        guard fileExists(indexURL) else {
            showErrorPage(
                title: "Could not launch Pari",
                message: "The bundled index.html file was not found at \(indexURL.path)."
            )
            return
        }

        guard directoryExists(assetsDirectory) else {
            showErrorPage(
                title: "Could not launch Pari",
                message: "The bundled assets directory was not found at \(assetsDirectory.path)."
            )
            return
        }

        guard let localWebServerURL else {
            showErrorPage(
                title: "Could not launch Pari",
                message: "The private local web server was not ready."
            )
            return
        }

        let request = URLRequest(url: localWebServerURL.appendingPathComponent("index.html"))
        log("loading \(request.url?.absoluteString ?? "<nil>")")
        webView?.load(request)
    }

    private func startLocalWebServer() {
        let server = LocalWebServer(rootDirectory: webDirectory)
        localWebServer = server
        server.start { [weak self] result in
            DispatchQueue.main.async {
                guard let self else { return }
                switch result {
                case .success(let port):
                    self.localWebServerURL = URL(string: "http://localhost:\(port)/")
                    self.loadBundledSite()
                case .failure(let error):
                    self.showErrorPage(
                        title: "Could not launch Pari",
                        message: "The private local web server could not start: \(error.localizedDescription)"
                    )
                }
            }
        }
    }

    private func startAgentStyleBackend() {
        let backend = AgentStyleBackend(
            idleTimeout: agentStyleIdleTimeout(),
            onIdleShutdown: { [weak self] in
                self?.log("agent style backend stopped after inactivity")
                DispatchQueue.main.async {
                    exit(0)
                }
            }
        )
        agentStyleBackend = backend
        backend.start { [weak self] result in
            guard let self else { return }
            switch result {
            case .success(let port):
                self.log("agent style backend ready http://127.0.0.1:\(port) idleTimeoutSeconds=\(Int(self.agentStyleIdleTimeout()))")
                fflush(stdout)
            case .failure(let error):
                self.log("agent style backend failed \(error.localizedDescription)")
                exit(1)
            }
        }
    }

    private func agentStyleIdleTimeout() -> TimeInterval {
        guard let index = CommandLine.arguments.firstIndex(of: "--idle-timeout-seconds"),
              index + 1 < CommandLine.arguments.count,
              let seconds = Double(CommandLine.arguments[index + 1]),
              seconds.isFinite,
              seconds > 0
        else {
            return 600
        }
        return min(seconds, 86_400)
    }

    private func runHeadlessSmokeTest(attempt: Int = 0) {
        guard let webView else {
            finishHeadless(success: false, message: "web view was not created")
            return
        }

        let inputLiteral = javascriptStringLiteral(headlessInput)
        let customStyleLiteral = javascriptStringLiteral(headlessCustomStyleName)
        let customStyleSelection = headlessCustomStyle ? """
          const customStyle = [...document.querySelectorAll('button[role="radio"]')]
            .find((candidate) => candidate.textContent?.trim() === \(customStyleLiteral));
          if (!customStyle) return JSON.stringify({ ok: false, retry: true, error: "custom style was not loaded yet" });
          if (customStyle.getAttribute("aria-checked") !== "true") {
            customStyle.click();
            return JSON.stringify({ ok: false, retry: true, error: "custom style selected; waiting for the shared engine" });
          }
        """ : ""
        let script = """
        (() => {
          \(customStyleSelection)
          const input = document.querySelector('textarea[aria-label="Original text"]');
          if (!input) return JSON.stringify({ ok: false, retry: true, error: "original text field was not found" });
          const setter = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value")?.set;
          if (!setter) return JSON.stringify({ ok: false, error: "textarea value setter was not found" });
          setter.call(input, \(inputLiteral));
          input.dispatchEvent(new Event("input", { bubbles: true }));
          const button = [...document.querySelectorAll("button")].find((candidate) => candidate.textContent?.trim() === "Paraphrase");
          if (!button) return JSON.stringify({ ok: false, retry: true, error: "paraphrase button was not found" });
          if (button.disabled) return JSON.stringify({ ok: false, retry: true, error: "paraphrase button is still disabled" });
          button.click();
          return JSON.stringify({ ok: true });
        })();
        """

        webView.evaluateJavaScript(script) { [weak self] result, error in
            guard let self else { return }
            if let error {
                self.finishHeadless(success: false, message: "could not submit smoke test: \(error.localizedDescription)")
                return
            }

            if let resultString = result as? String,
               let data = resultString.data(using: .utf8),
               let payload = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
               payload["ok"] as? Bool == false {
                if payload["retry"] as? Bool == true && attempt < 120 {
                    DispatchQueue.main.asyncAfter(deadline: .now() + 0.25) {
                        self.runHeadlessSmokeTest(attempt: attempt + 1)
                    }
                    return
                }
                self.finishHeadless(success: false, message: payload["error"] as? String ?? "unknown submission error")
                return
            }

            self.pollHeadlessSmoke(attempt: 0)
        }
    }

    private func pollHeadlessSmoke(attempt: Int) {
        guard let webView else {
            finishHeadless(success: false, message: "web view disappeared during smoke test")
            return
        }

        let script = """
        (() => {
          const editor = document.querySelector('[aria-label="Editable paraphrased text with inline word tools"]');
          const output = editor?.innerText?.trim() || "";
          const token = editor?.querySelector('[data-inline-token]');
          const popover = document.querySelector('[data-testid="synonym-popover"]');
          const generationSource = document.querySelector('[data-generation-source]')?.getAttribute('data-generation-source') || "";
          const activeMode = [...document.querySelectorAll('button[role="radio"]')]
            .find((candidate) => candidate.getAttribute("aria-checked") === "true")?.textContent?.trim() || "";
          const notice = document.querySelector('.notice')?.textContent?.trim() || "";
          const warningStatus = document.querySelector('.quality-chip-warning')?.textContent?.trim() || "";
          const legendCount = document.querySelectorAll('[data-testid="quality-legend"] .legend-item').length || 0;
          const tokenHasDialogSemantics = Boolean(token
            && token.getAttribute('role') === 'button'
            && token.getAttribute('aria-haspopup') === 'dialog'
            && token.getAttribute('aria-controls') === 'synonym-popover');
          return JSON.stringify({
            output,
            tokenCount: editor?.querySelectorAll('[data-inline-token]').length || 0,
            warningCount: editor?.querySelectorAll('[data-grammar-warning-token]').length || 0,
            warningStatus,
            generationSource,
            activeMode,
            notice,
            optionCount: popover?.querySelectorAll('button').length || 0,
            hasToken: Boolean(token),
            legendCount,
            tokenHasDialogSemantics,
            popoverRole: popover?.getAttribute('role') || ""
          });
        })();
        """

        webView.evaluateJavaScript(script) { [weak self] result, error in
            guard let self else { return }
            if let error {
                self.finishHeadless(success: false, message: "could not inspect smoke test: \(error.localizedDescription)")
                return
            }

            guard let resultString = result as? String,
                  let data = resultString.data(using: .utf8),
                  let payload = try? JSONSerialization.jsonObject(with: data) as? [String: Any]
            else {
                self.finishHeadless(success: false, message: "smoke test returned an unreadable result")
                return
            }

            let output = payload["output"] as? String ?? ""
            let tokenCount = payload["tokenCount"] as? Int ?? 0
            let optionCount = payload["optionCount"] as? Int ?? 0
            let notice = payload["notice"] as? String ?? ""
            let hasToken = payload["hasToken"] as? Bool ?? false
            let warningCount = payload["warningCount"] as? Int ?? 0
            let warningStatus = payload["warningStatus"] as? String ?? ""
            let generationSource = payload["generationSource"] as? String ?? ""
            let activeMode = payload["activeMode"] as? String ?? ""
            let legendCount = payload["legendCount"] as? Int ?? 0
            let tokenHasDialogSemantics = payload["tokenHasDialogSemantics"] as? Bool ?? false
            let popoverRole = payload["popoverRole"] as? String ?? ""

            if !output.isEmpty && hasToken && (legendCount < 3 || !tokenHasDialogSemantics) {
                self.finishHeadless(success: false, message: "installed editor highlighting semantics are incomplete; legendCount=\(legendCount) tokenDialog=\(tokenHasDialogSemantics)")
                return
            }

            if !output.isEmpty && output != self.headlessInput && !self.headlessContextRequested && hasToken {
                if self.headlessCustomStyle && activeMode != self.headlessCustomStyleName {
                    self.finishHeadless(success: false, message: "installed app did not select custom style \(self.headlessCustomStyleName); activeMode=\(activeMode)")
                    return
                }
                let expectedSource = self.headlessMissingModel
                    ? "local-safe-engine"
                    : self.headlessExpectedGenerationSource
                if !generationSource.isEmpty && generationSource != expectedSource {
                    self.finishHeadless(success: false, message: "installed app used \(generationSource) instead of expected \(expectedSource); notice=\(notice)")
                    return
                }
                if expectedSource == "local-safe-engine"
                    && !notice.localizedCaseInsensitiveContains("not connected")
                    && !notice.localizedCaseInsensitiveContains("incomplete") {
                    self.finishHeadless(success: false, message: "offline fallback did not expose the actionable model connection notice; notice=\(notice)")
                    return
                }
                self.headlessContextRequested = true
                let clickScript = "document.querySelector('[data-inline-token]')?.click();"
                webView.evaluateJavaScript(clickScript) { [weak self] _, clickError in
                    guard let self else { return }
                    if let clickError {
                        self.finishHeadless(success: false, message: "could not open contextual choices: \(clickError.localizedDescription)")
                        return
                    }
                    self.pollHeadlessSmoke(attempt: attempt + 1)
                }
                return
            }

            let contextualReady = self.headlessContextRequested
                && optionCount > 2
                && notice.contains("Local contextual alternatives are ready")
                && popoverRole == "dialog"
            if contextualReady && !self.headlessGrammarProbeStarted {
                self.headlessGrammarProbeStarted = true
                let grammarProbeScript = """
                (() => {
                  const editor = document.querySelector('[aria-label="Editable paraphrased text with inline word tools"]');
                  if (!editor) return JSON.stringify({ ok: false, error: "editor was not found for grammar probe" });
                  editor.textContent = "They is ready to revise the draft.";
                  editor.dispatchEvent(new InputEvent("input", { bubbles: true, inputType: "insertText" }));
                  return JSON.stringify({ ok: true });
                })();
                """
                webView.evaluateJavaScript(grammarProbeScript) { [weak self] _, probeError in
                    guard let self else { return }
                    if let probeError {
                        self.finishHeadless(success: false, message: "could not start grammar highlighting probe: \(probeError.localizedDescription)")
                        return
                    }
                    self.pollHeadlessSmoke(attempt: attempt + 1)
                }
                return
            }

            let expectedSource = self.headlessMissingModel
                ? "local-safe-engine"
                : self.headlessExpectedGenerationSource
            if self.headlessGrammarProbeStarted
                && generationSource == expectedSource
                && warningCount > 0
                && !warningStatus.isEmpty
                && !warningStatus.localizedCaseInsensitiveContains("checking") {
                self.finishHeadless(
                    success: true,
                    message: "outputWords=\(output.split(whereSeparator: { $0 == " " || $0 == "\n" }).count) generator=\(generationSource) activeMode=\(activeMode) contextualOptions=\(optionCount) contextualSource=grammar-highlight-probe warnings=\(warningCount) status=\(warningStatus) tokens=\(tokenCount)"
                )
                return
            }

            if attempt >= 360 {
                self.finishHeadless(
                    success: false,
                    message: "timed out waiting for a changed rewrite and local contextual choices; output=\(output.prefix(120)) notice=\(notice)"
                )
                return
            }

            DispatchQueue.main.asyncAfter(deadline: .now() + 0.25) {
                self.pollHeadlessSmoke(attempt: attempt + 1)
            }
        }
    }

    private func finishHeadless(success: Bool, message: String) {
        log("headless \(success ? "PASS" : "FAIL") \(message)")
        DispatchQueue.main.async {
            exit(success ? 0 : 1)
        }
    }

    private func javascriptStringLiteral(_ value: String) -> String {
        guard let data = try? JSONSerialization.data(withJSONObject: [value]),
              let json = String(data: data, encoding: .utf8),
              let start = json.firstIndex(of: "["),
              let end = json.lastIndex(of: "]")
        else {
            return "\"\""
        }

        return String(json[json.index(after: start)..<end]).trimmingCharacters(in: .whitespacesAndNewlines)
    }

    private func logStartupDiagnostics() {
        let resourcePath = Bundle.main.resourceURL?.path ?? "<missing>"
        log("resource path \(resourcePath)")
        log("web path \(webDirectory.path)")
        log("index path \(indexURL.path)")
        log("index exists \(fileExists(indexURL))")
        log("assets exists \(directoryExists(assetsDirectory))")
        log("model directory exists \(directoryExists(modelDirectory))")
        if let nativeModelURL = nativeModelURL() {
            log("native model connected \(nativeModelURL.path)")
        } else {
            log("native model not connected; expected later at \(nativeModelInstallDirectory.path)")
        }
    }

    private func fileExists(_ url: URL) -> Bool {
        var isDirectory = ObjCBool(false)
        return FileManager.default.fileExists(atPath: url.path, isDirectory: &isDirectory) && !isDirectory.boolValue
    }

    private func directoryExists(_ url: URL) -> Bool {
        var isDirectory = ObjCBool(false)
        return FileManager.default.fileExists(atPath: url.path, isDirectory: &isDirectory) && isDirectory.boolValue
    }

    private func makeConsoleBridgeScript() -> String {
        """
        (() => {
          if (window.__OPEN_LOCAL_PHRASER_CONSOLE_BRIDGE__) return;
          window.__OPEN_LOCAL_PHRASER_CONSOLE_BRIDGE__ = true;

          const handler = window.webkit?.messageHandlers?.\(consoleHandlerName);
          if (!handler) return;

          const serialize = (value) => {
            if (typeof value === "string") return value;
            try {
              return JSON.stringify(value);
            } catch (error) {
              return String(value);
            }
          };

          for (const level of ["log", "info", "warn", "error"]) {
            const original = console[level]?.bind(console);
            console[level] = (...args) => {
              try {
                handler.postMessage({
                  level,
                  message: args.map(serialize).join(" ")
                });
              } catch (error) {
                // Ignore bridge errors and preserve the original console behavior.
              }

              if (original) {
                original(...args);
              }
            };
          }
        })();
        """
    }

    private func handleNativeMessage(_ message: WKScriptMessage) {
        guard let body = message.body as? [String: Any],
              let requestID = (body["id"] as? NSNumber)?.intValue,
              let action = body["action"] as? String
        else {
            return
        }

        if action == "generateParaphrase" {
            guard let payload = body["payload"] as? [String: Any] else {
                replyToGeneration(requestID: requestID, result: [
                    "ok": false,
                    "error": "The native paraphrase request was missing its payload.",
                ])
                return
            }
            nativeGenerationQueue.async { [weak self] in
                self?.runNativeParaphrase(requestID: requestID, payload: payload)
            }
            return
        }

        if action == "cancelParaphrase" {
            nativeGenerationQueue.async { [weak self] in
                guard let self, let process = self.nativeProcesses.removeValue(forKey: requestID) else { return }
                if process.isRunning {
                    process.terminate()
                }
            }
            return
        }

        do {
            let result: [String: Any]
            switch action {
            case "loadState":
                result = approvalPersistence.loadState()
            case "loadCustomStyles":
                result = agentStyleStore.listPayload()
            case "saveApproval":
                guard let payload = body["payload"] as? [String: Any] else {
                    throw NSError(domain: "OpenLocalPhraser.Persistence", code: 2, userInfo: [
                        NSLocalizedDescriptionKey: "Approval payload was missing."
                    ])
                }
                result = try approvalPersistence.saveApproval(payload: payload)
            default:
                throw NSError(domain: "OpenLocalPhraser.Persistence", code: 3, userInfo: [
                    NSLocalizedDescriptionKey: "Unknown native action."
                ])
            }
            replyToNative(requestID: requestID, result: result)
        } catch {
            replyToNative(requestID: requestID, result: [
                "ok": false,
                "error": error.localizedDescription,
            ])
        }
    }

    private func handleClipboardMessage(_ message: WKScriptMessage) {
        guard let body = message.body as? [String: Any],
              let requestID = (body["id"] as? NSNumber)?.intValue,
              let action = body["action"] as? String
        else {
            return
        }

        switch action {
        case "writeText":
            guard let text = body["text"] as? String else {
                replyToClipboard(requestID: requestID, result: [
                    "ok": false,
                    "error": "Clipboard text was missing.",
                ])
                return
            }

            NSPasteboard.general.clearContents()
            let didWrite = NSPasteboard.general.setString(text, forType: .string)
            replyToClipboard(requestID: requestID, result: [
                "ok": didWrite,
                "error": didWrite ? NSNull() : "Could not write to the macOS clipboard.",
            ])
        case "readText":
            let text = NSPasteboard.general.string(forType: .string) ?? ""
            replyToClipboard(requestID: requestID, result: [
                "ok": true,
                "text": text,
            ])
        default:
            replyToClipboard(requestID: requestID, result: [
                "ok": false,
                "error": "Unknown clipboard action.",
            ])
        }
    }

    private func replyToClipboard(requestID: Int, result: [String: Any]) {
        guard let data = try? JSONSerialization.data(withJSONObject: result),
              let json = String(data: data, encoding: .utf8)
        else {
            return
        }

        let script = "window.__openLocalPhraserClipboardResolve?.(\(requestID), \(json));"
        webView?.evaluateJavaScript(script, completionHandler: nil)
    }

    private func replyToNative(requestID: Int, result: [String: Any]) {
        guard let data = try? JSONSerialization.data(withJSONObject: result),
              let json = String(data: data, encoding: .utf8)
        else {
            return
        }

        let script = "window.__openLocalPhraserNativeResolve?.(\(requestID), \(json));"
        webView?.evaluateJavaScript(script, completionHandler: nil)
    }

    private func replyToGeneration(requestID: Int, result: [String: Any]) {
        guard let data = try? JSONSerialization.data(withJSONObject: result),
              let json = String(data: data, encoding: .utf8)
        else {
            return
        }

        DispatchQueue.main.async { [weak self] in
            self?.webView?.evaluateJavaScript(
                "window.__openLocalPhraserGenerationResolve?.(\(requestID), \(json));",
                completionHandler: nil
            )
        }
    }

    private func runNativeParaphrase(requestID: Int, payload: [String: Any]) {
        if freellmRequested {
            runFreeLLMParaphrase(requestID: requestID, payload: payload)
            return
        }
        if ollamaRequested {
            runOllamaParaphrase(requestID: requestID, payload: payload)
            return
        }

        let startedAt = Date()
        let resourceRoot = Bundle.main.resourceURL ?? URL(fileURLWithPath: "/")
        let environment = ProcessInfo.processInfo.environment
        let mtpDraftPath = nativeMtpDraftModelPath
        let useNativeMtp = mtpDraftPath != nil
        let workerPath = useNativeMtp ? nativeMtpWorkerRelativePath : nativeWorkerRelativePath
        let workerURL = resourceRoot.appendingPathComponent(workerPath)

        if useNativeMtp,
           let mtpDraftPath,
           !nativeMtpDraftModelIsComplete(at: URL(fileURLWithPath: mtpDraftPath)) {
            replyToGeneration(requestID: requestID, result: [
                "ok": false,
                "error": "The Qwen MTP drafter is incomplete or incompatible. Use the Qwen3.5-4B-MTP checkpoint with a matching Qwen3.5-4B target.",
            ])
            return
        }

        guard fileExists(workerURL) else {
            replyToGeneration(requestID: requestID, result: [
                "ok": false,
                "error": "The native paraphrase worker is missing from this Pari installation. Reinstall the app to restore the local runtime.",
            ])
            return
        }

        let modelURL = headlessMissingModel ? nil : nativeModelURL()
        guard let modelURL else {
            replyToGeneration(requestID: requestID, result: [
                "ok": false,
                "error": nativeModelUnavailableMessage(),
            ])
            return
        }

        guard let pythonURL = nativePythonURL() else {
            replyToGeneration(requestID: requestID, result: [
                "ok": false,
                "error": useNativeMtp
                    ? "The Qwen MTP runtime is unavailable. Set PARI_NATIVE_PYTHON_PATH to Python with mlx-vlm installed."
                    : "The native generator runtime is unavailable. Install mlx-lm for the selected Python 3 runtime, then rebuild or relaunch Pari.",
            ])
            return
        }

        guard let originalText = payload["originalText"] as? String, !originalText.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else {
            replyToGeneration(requestID: requestID, result: [
                "ok": false,
                "error": "The native paraphrase request contained no text.",
            ])
            return
        }

        let protectedSpans = payload["protectedSpans"] as? [String] ?? []
        let mode = payload["mode"] as? String ?? "personal"
        let strength = (payload["strength"] as? NSNumber)?.intValue ?? 56
        let maxTokens = (payload["maxTokens"] as? NSNumber)?.intValue ?? 768
        let repairPass = payload["repairPass"] as? Bool ?? false
        let temperature = (payload["temperature"] as? NSNumber)?.doubleValue
        let styleInstructions = payload["styleInstructions"] as? String
        let styleTweaks = payload["styleTweaks"] as? [String: Any]
        let styleContext = payload["styleContext"] as? [String: Any]
        var request: [String: Any] = [
            "model_path": modelURL.path,
            "original_text": originalText,
            "protected_spans": protectedSpans,
            "mode": mode,
            "strength": strength,
            "max_tokens": maxTokens,
        ]
        if repairPass { request["repair_pass"] = true }
        // Best-of-N: extra candidates are cheap once the model is loaded; the
        // web layer ranks them with its meaning/grammar gates.
        if let candidateCount = (payload["candidates"] as? NSNumber)?.intValue, candidateCount > 1 {
            request["candidates"] = max(1, min(candidateCount, 4))
        }
        if let temperature { request["temperature"] = temperature }
        if let styleInstructions, !styleInstructions.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
            request["custom_instructions"] = styleInstructions
        }
        if let styleTweaks { request["style_tweaks"] = styleTweaks }
        if let styleContext { request["style_context"] = styleContext }

        // Opt-in MLX-LM speculative decoding. The draft path is deliberately
        // environment-only: no extra model is silently downloaded or bundled,
        // and the worker falls back to the normal target-only generation when
        // this variable is absent.
        if useNativeMtp, let mtpDraftPath {
            request["mtp_draft_model_path"] = mtpDraftPath
        } else if let draftPath = environment["PARI_NATIVE_DRAFT_MODEL_PATH"],
           !draftPath.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty,
           FileManager.default.fileExists(atPath: draftPath) {
            request["draft_model_path"] = draftPath
            if let rawDraftTokens = environment["PARI_NATIVE_NUM_DRAFT_TOKENS"],
               let draftTokens = Int(rawDraftTokens.trimmingCharacters(in: .whitespacesAndNewlines)) {
                request["num_draft_tokens"] = max(1, min(draftTokens, 10))
            }
        }

        guard let requestData = try? JSONSerialization.data(withJSONObject: request) else {
            replyToGeneration(requestID: requestID, result: [
                "ok": false,
                "error": "The native paraphrase request could not be serialized.",
            ])
            return
        }

        let process = Process()
        let inputPipe = Pipe()
        let outputPipe = Pipe()
        let errorPipe = Pipe()
        process.executableURL = pythonURL
        process.arguments = [workerURL.path]
        process.standardInput = inputPipe
        process.standardOutput = outputPipe
        process.standardError = errorPipe
        var processEnvironment = ProcessInfo.processInfo.environment
        processEnvironment["PYTHONDONTWRITEBYTECODE"] = "1"
        process.environment = processEnvironment

        nativeProcesses[requestID] = process
        defer {
            nativeProcesses.removeValue(forKey: requestID)
        }

        do {
            try process.run()
            inputPipe.fileHandleForWriting.write(requestData)
            inputPipe.fileHandleForWriting.closeFile()
            let outputData = outputPipe.fileHandleForReading.readDataToEndOfFile()
            let errorData = errorPipe.fileHandleForReading.readDataToEndOfFile()
            process.waitUntilExit()

            let response = parseNativeWorkerResponse(outputData)
            let elapsedMs = Int(Date().timeIntervalSince(startedAt) * 1000)
            if process.terminationStatus == 0,
               let response,
               response["ok"] as? Bool == true,
               let text = response["text"] as? String,
               !text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
                var reply: [String: Any] = [
                    "ok": true,
                    "text": text,
                    "durationMs": elapsedMs,
                    "modelId": nativeModelID,
                ]
                // Forward every candidate so the web layer can rank them.
                if let candidates = response["candidates"] as? [[String: Any]] {
                    reply["candidates"] = candidates
                }
                replyToGeneration(requestID: requestID, result: reply)
                return
            }

            let workerError = response?["error"] as? String
            let stderr = String(data: errorData, encoding: .utf8)?.trimmingCharacters(in: .whitespacesAndNewlines)
            let detail = workerError ?? (stderr?.isEmpty == false ? stderr! : "The MLX worker exited without a usable paragraph.")
            replyToGeneration(requestID: requestID, result: [
                "ok": false,
                "error": "The local \(nativeModelID) generator could not produce a safe draft: \(detail)",
            ])
        } catch {
            replyToGeneration(requestID: requestID, result: [
                "ok": false,
                "error": "The local \(nativeModelID) generator could not start: \(error.localizedDescription)",
            ])
        }
    }

    private func runFreeLLMParaphrase(requestID: Int, payload: [String: Any]) {
        let startedAt = Date()
        let environment = ProcessInfo.processInfo.environment
        guard let apiKey = environment["PARI_FREELLM_API_KEY"], !apiKey.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else {
            replyToGeneration(requestID: requestID, result: [
                "ok": false,
                "error": "FreeLLMAPI routing is enabled, but PARI_FREELLM_API_KEY is not set. Pari stayed on its safe offline fallback.",
            ])
            return
        }

        let resourceRoot = Bundle.main.resourceURL ?? URL(fileURLWithPath: "/")
        let workerURL = resourceRoot.appendingPathComponent(freeLLMWorkerRelativePath)
        guard fileExists(workerURL) else {
            replyToGeneration(requestID: requestID, result: [
                "ok": false,
                "error": "The FreeLLMAPI worker is missing from this Pari installation. Rebuild or reinstall Pari to restore the optional API route.",
            ])
            return
        }

        guard let pythonURL = nativePythonURL() else {
            replyToGeneration(requestID: requestID, result: [
                "ok": false,
                "error": "The FreeLLMAPI route needs the selected Python 3 runtime. Install Python 3 and relaunch Pari.",
            ])
            return
        }

        guard let originalText = payload["originalText"] as? String, !originalText.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else {
            replyToGeneration(requestID: requestID, result: [
                "ok": false,
                "error": "The FreeLLMAPI paraphrase request contained no text.",
            ])
            return
        }

        let protectedSpans = payload["protectedSpans"] as? [String] ?? []
        let mode = payload["mode"] as? String ?? "personal"
        let strength = (payload["strength"] as? NSNumber)?.intValue ?? 56
        let maxTokens = (payload["maxTokens"] as? NSNumber)?.intValue ?? 768
        let repairPass = payload["repairPass"] as? Bool ?? false
        let styleInstructions = payload["styleInstructions"] as? String
        let styleTweaks = payload["styleTweaks"] as? [String: Any]
        let styleContext = payload["styleContext"] as? [String: Any]
        var request: [String: Any] = [
            "original_text": originalText,
            "protected_spans": protectedSpans,
            "mode": mode,
            "strength": strength,
            "max_tokens": maxTokens,
        ]
        if repairPass { request["repair_pass"] = true }
        if let styleInstructions, !styleInstructions.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
            request["custom_instructions"] = styleInstructions
        }
        if let styleTweaks { request["style_tweaks"] = styleTweaks }
        if let styleContext { request["style_context"] = styleContext }

        guard let requestData = try? JSONSerialization.data(withJSONObject: request) else {
            replyToGeneration(requestID: requestID, result: [
                "ok": false,
                "error": "The FreeLLMAPI paraphrase request could not be serialized.",
            ])
            return
        }

        let process = Process()
        let inputPipe = Pipe()
        let outputPipe = Pipe()
        let errorPipe = Pipe()
        process.executableURL = pythonURL
        process.arguments = [workerURL.path]
        process.standardInput = inputPipe
        process.standardOutput = outputPipe
        process.standardError = errorPipe
        var processEnvironment = ProcessInfo.processInfo.environment
        processEnvironment["PYTHONDONTWRITEBYTECODE"] = "1"
        process.environment = processEnvironment

        nativeProcesses[requestID] = process
        defer {
            nativeProcesses.removeValue(forKey: requestID)
        }

        do {
            try process.run()
            inputPipe.fileHandleForWriting.write(requestData)
            inputPipe.fileHandleForWriting.closeFile()
            let outputData = outputPipe.fileHandleForReading.readDataToEndOfFile()
            let errorData = errorPipe.fileHandleForReading.readDataToEndOfFile()
            process.waitUntilExit()

            let response = parseNativeWorkerResponse(outputData)
            let elapsedMs = Int(Date().timeIntervalSince(startedAt) * 1000)
            if process.terminationStatus == 0,
               let response,
               response["ok"] as? Bool == true,
               let text = response["text"] as? String,
               !text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
                let configuredModel = environment["PARI_FREELLM_MODEL"]?.trimmingCharacters(in: .whitespacesAndNewlines)
                var reply: [String: Any] = [
                    "ok": true,
                    "text": text,
                    "durationMs": elapsedMs,
                    "modelId": response["model_id"] as? String ?? "freellm:\(configuredModel?.isEmpty == false ? configuredModel! : "gemma-4-31b")",
                    "backend": "freellm-api",
                ]
                if let servedModel = response["served_model"] as? String {
                    reply["servedModel"] = servedModel
                }
                replyToGeneration(requestID: requestID, result: reply)
                return
            }

            let workerError = response?["error"] as? String
            let stderr = String(data: errorData, encoding: .utf8)?.trimmingCharacters(in: .whitespacesAndNewlines)
            let detail = workerError ?? (stderr?.isEmpty == false ? stderr! : "FreeLLMAPI returned no usable paragraph.")
            replyToGeneration(requestID: requestID, result: [
                "ok": false,
                "error": "The FreeLLMAPI generator could not produce a safe draft: \(detail)",
            ])
        } catch {
            replyToGeneration(requestID: requestID, result: [
                "ok": false,
                "error": "The FreeLLMAPI generator could not start: \(error.localizedDescription)",
            ])
        }
    }

    private func runOllamaParaphrase(requestID: Int, payload: [String: Any]) {
        let startedAt = Date()
        let environment = ProcessInfo.processInfo.environment
        let resourceRoot = Bundle.main.resourceURL ?? URL(fileURLWithPath: "/")
        let workerURL = resourceRoot.appendingPathComponent(ollamaWorkerRelativePath)
        guard fileExists(workerURL) else {
            replyToGeneration(requestID: requestID, result: [
                "ok": false,
                "error": "The Ollama worker is missing from this Pari installation. Rebuild or reinstall the app to restore the optional Ollama route.",
            ])
            return
        }

        guard let pythonURL = nativePythonURL() else {
            replyToGeneration(requestID: requestID, result: [
                "ok": false,
                "error": "The Ollama route needs the selected Python 3 runtime. Install Python 3 and relaunch Pari.",
            ])
            return
        }

        guard let originalText = payload["originalText"] as? String, !originalText.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else {
            replyToGeneration(requestID: requestID, result: [
                "ok": false,
                "error": "The Ollama paraphrase request contained no text.",
            ])
            return
        }

        let protectedSpans = payload["protectedSpans"] as? [String] ?? []
        let mode = payload["mode"] as? String ?? "personal"
        let strength = (payload["strength"] as? NSNumber)?.intValue ?? 56
        let maxTokens = (payload["maxTokens"] as? NSNumber)?.intValue ?? 768
        let repairPass = payload["repairPass"] as? Bool ?? false
        let styleInstructions = payload["styleInstructions"] as? String
        let styleTweaks = payload["styleTweaks"] as? [String: Any]
        let styleContext = payload["styleContext"] as? [String: Any]
        var request: [String: Any] = [
            "original_text": originalText,
            "protected_spans": protectedSpans,
            "mode": mode,
            "strength": strength,
            "max_tokens": maxTokens,
        ]
        if repairPass { request["repair_pass"] = true }
        if let styleInstructions, !styleInstructions.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
            request["custom_instructions"] = styleInstructions
        }
        if let styleTweaks { request["style_tweaks"] = styleTweaks }
        if let styleContext { request["style_context"] = styleContext }

        guard let requestData = try? JSONSerialization.data(withJSONObject: request) else {
            replyToGeneration(requestID: requestID, result: [
                "ok": false,
                "error": "The Ollama paraphrase request could not be serialized.",
            ])
            return
        }

        let process = Process()
        let inputPipe = Pipe()
        let outputPipe = Pipe()
        let errorPipe = Pipe()
        process.executableURL = pythonURL
        process.arguments = [workerURL.path]
        process.standardInput = inputPipe
        process.standardOutput = outputPipe
        process.standardError = errorPipe
        var processEnvironment = environment
        processEnvironment["PYTHONDONTWRITEBYTECODE"] = "1"
        process.environment = processEnvironment

        nativeProcesses[requestID] = process
        defer {
            nativeProcesses.removeValue(forKey: requestID)
        }

        do {
            try process.run()
            inputPipe.fileHandleForWriting.write(requestData)
            inputPipe.fileHandleForWriting.closeFile()
            let outputData = outputPipe.fileHandleForReading.readDataToEndOfFile()
            let errorData = errorPipe.fileHandleForReading.readDataToEndOfFile()
            process.waitUntilExit()

            let response = parseNativeWorkerResponse(outputData)
            let elapsedMs = Int(Date().timeIntervalSince(startedAt) * 1000)
            if process.terminationStatus == 0,
               let response,
               response["ok"] as? Bool == true,
               let text = response["text"] as? String,
               !text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
                var reply: [String: Any] = [
                    "ok": true,
                    "text": text,
                    "durationMs": elapsedMs,
                    "modelId": response["model_id"] as? String ?? "ollama:model",
                    "backend": "ollama",
                ]
                if let servedModel = response["served_model"] as? String {
                    reply["servedModel"] = servedModel
                }
                replyToGeneration(requestID: requestID, result: reply)
                return
            }

            let workerError = response?["error"] as? String
            let stderr = String(data: errorData, encoding: .utf8)?.trimmingCharacters(in: .whitespacesAndNewlines)
            let detail = workerError ?? (stderr?.isEmpty == false ? stderr! : "Ollama returned no usable paragraph.")
            replyToGeneration(requestID: requestID, result: [
                "ok": false,
                "error": "The Ollama generator could not produce a safe draft: \(detail)",
            ])
        } catch {
            replyToGeneration(requestID: requestID, result: [
                "ok": false,
                "error": "The Ollama generator could not start: \(error.localizedDescription)",
            ])
        }
    }

    private func parseNativeWorkerResponse(_ data: Data) -> [String: Any]? {
        let lines = String(data: data, encoding: .utf8)?.split(whereSeparator: \.isNewline).reversed() ?? []
        for line in lines {
            guard let jsonData = line.data(using: .utf8),
                  let object = try? JSONSerialization.jsonObject(with: jsonData),
                  let response = object as? [String: Any]
            else { continue }
            return response
        }
        return nil
    }

    private func nativePythonURL() -> URL? {
        if let override = ProcessInfo.processInfo.environment["PARI_NATIVE_PYTHON_PATH"],
            !override.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
            let url = URL(fileURLWithPath: override.trimmingCharacters(in: .whitespacesAndNewlines))
            return FileManager.default.isExecutableFile(atPath: url.path) ? url : nil
        }
        let candidates = [
            "/opt/homebrew/bin/python3",
            "/usr/local/bin/python3",
            "/Library/Frameworks/Python.framework/Versions/3.11/bin/python3",
            "/usr/bin/python3",
        ]
        return candidates
            .map(URL.init(fileURLWithPath:))
            .first(where: { fileExists($0) && FileManager.default.isExecutableFile(atPath: $0.path) })
    }

    private var nativeMtpDraftModelPath: String? {
        guard let raw = ProcessInfo.processInfo.environment["PARI_NATIVE_MTP_DRAFT_MODEL_PATH"] else {
            return nil
        }
        let value = raw.trimmingCharacters(in: .whitespacesAndNewlines)
        return value.isEmpty ? nil : value
    }

    private func nativeMtpDraftModelIsComplete(at url: URL) -> Bool {
        guard directoryExists(url),
              let data = try? Data(contentsOf: url.appendingPathComponent("config.json")),
              let config = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              config["model_type"] as? String == "qwen3_5_mtp"
        else { return false }

        let requiredFiles = [
            "config.json",
            "model.safetensors",
            "model.safetensors.index.json",
            "tokenizer.json",
            "tokenizer_config.json",
        ]
        return requiredFiles.allSatisfy { fileExists(url.appendingPathComponent($0)) }
    }

    private func nativeModelURL() -> URL? {
        nativeModelCandidates().first(where: { nativeModelIsComplete(at: $0) })
    }

    private func nativeModelCandidates() -> [URL] {
        var candidates = [URL]()

        if let nativeModelPathOverride {
            // An absolute override is a complete candidate, never a component
            // appended to Application Support or the app bundle.
            candidates.append(nativeModelPathOverride)
        } else {
            candidates.append(nativeModelInstallDirectory)

            let applicationSupport = FileManager.default.urls(
                for: .applicationSupportDirectory,
                in: .userDomainMask
            ).first ?? FileManager.default.temporaryDirectory
            candidates.append(
                applicationSupport
                    .appendingPathComponent("Open Local Phraser", isDirectory: true)
                    .appendingPathComponent("Models", isDirectory: true)
                    .appendingPathComponent(nativeModelRelativePath, isDirectory: true)
            )

            if let resourceRoot = Bundle.main.resourceURL {
                // Retain compatibility with development bundles built before
                // the checkpoint was moved out of Pari.app. New packages never copy it.
                candidates.append(resourceRoot.appendingPathComponent(nativeModelRelativePath, isDirectory: true))
            }
        }

        var seen = Set<String>()
        return candidates.filter { candidate in
            seen.insert(candidate.path).inserted
        }
    }

    private func nativeModelIsComplete(at url: URL) -> Bool {
        guard directoryExists(url) else { return false }
        if nativeMtpDraftModelPath != nil {
            guard let data = try? Data(contentsOf: url.appendingPathComponent("config.json")),
                  let config = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
                  config["model_type"] as? String == "qwen3_5"
            else { return false }

            let requiredFiles = Set(nativeModelRequiredFiles.filter { $0 != "manifest.json" })
            return requiredFiles.allSatisfy { fileExists(url.appendingPathComponent($0)) }
        }
        guard let data = try? Data(contentsOf: url.appendingPathComponent("manifest.json")),
              let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let manifestModelID = json["modelId"] as? String,
              manifestModelID == nativeModelID,
              let manifestFiles = json["files"] as? [String],
              !manifestFiles.isEmpty
        else { return false }

        let requiredFiles = Set(nativeModelRequiredFiles + manifestFiles)
        return requiredFiles.allSatisfy { fileExists(url.appendingPathComponent($0)) }
    }

    private func nativeModelUnavailableMessage() -> String {
        let incompleteCandidate = nativeModelCandidates().first(where: { directoryExists($0) })
        if let incompleteCandidate {
            return "The optional local \(nativeModelID) model at \(incompleteCandidate.path) is incomplete. Pari stayed on the deterministic local-safe engine. Run `npm run models:download:native` in the Pari checkout, or install a complete verified model at \(nativeModelInstallDirectory.path)."
        }

        return "The optional local \(nativeModelID) model is not connected. Pari stayed on the deterministic local-safe engine. Run `npm run models:download:native` in the Pari checkout, or install a complete verified model at \(nativeModelInstallDirectory.path)."
    }

    private func makeBootDiagnosticsScript() -> String {
        let webExists = directoryExists(webDirectory) ? "true" : "false"
        let indexExists = fileExists(indexURL) ? "true" : "false"
        let assetsExists = directoryExists(assetsDirectory) ? "true" : "false"
        let modelExists = directoryExists(modelDirectory) ? "true" : "false"

        return """
        window.__OPEN_LOCAL_PHRASER_BOOT__ = {
          diagnostics: {
            webDirectoryExists: \(webExists),
            indexExists: \(indexExists),
            assetsDirectoryExists: \(assetsExists),
            modelDirectoryExists: \(modelExists)
          }
        };
        """
    }

    private func showErrorPage(title: String, message: String) {
        let escapedTitle = escapeHTML(title)
        let escapedMessage = escapeHTML(message)
        let html = """
        <!doctype html>
        <html>
          <head>
            <meta charset="utf-8">
            <meta name="viewport" content="width=device-width, initial-scale=1">
            <style>
              body {
                margin: 0;
                min-height: 100vh;
                display: grid;
                place-items: center;
                background: linear-gradient(180deg, #f8fafc 0%, #edf5f1 100%);
                color: #0f172a;
                font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
              }
              .card {
                max-width: 720px;
                margin: 32px;
                padding: 28px;
                border-radius: 24px;
                background: rgba(255, 255, 255, 0.9);
                border: 1px solid rgba(148, 163, 184, 0.25);
                box-shadow: 0 24px 70px rgba(15, 23, 42, 0.12);
              }
              h1 {
                margin: 0 0 8px;
                font-size: 28px;
              }
              p {
                margin: 0;
                line-height: 1.6;
                color: #475569;
                white-space: pre-wrap;
              }
            </style>
          </head>
          <body>
            <div class="card">
              <h1>\(escapedTitle)</h1>
              <p>\(escapedMessage)</p>
            </div>
          </body>
        </html>
        """

        webView?.loadHTMLString(html, baseURL: nil)
    }

    private func log(_ message: String) {
        print("[OpenLocalPhraser] \(message)")
    }

    private func escapeHTML(_ value: String) -> String {
        value
            .replacingOccurrences(of: "&", with: "&amp;")
            .replacingOccurrences(of: "<", with: "&lt;")
            .replacingOccurrences(of: ">", with: "&gt;")
            .replacingOccurrences(of: "\"", with: "&quot;")
            .replacingOccurrences(of: "'", with: "&#39;")
    }
}

let app = NSApplication.shared
let delegate = AppDelegate()
app.delegate = delegate
app.run()
