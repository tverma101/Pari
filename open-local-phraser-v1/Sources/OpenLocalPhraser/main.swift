import AppKit
import Foundation
import WebKit

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
        guard resolvedPath.path.hasPrefix(webDirPath) else {
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
                "Access-Control-Allow-Origin": "*",
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

final class AppDelegate: NSObject, NSApplicationDelegate, WKNavigationDelegate, WKScriptMessageHandler {
    private let appName = "Open Local Phraser V2"
    private let consoleHandlerName = "openLocalPhraserConsole"
    private let scheme = "app"

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

    private var window: NSWindow?
    private var webView: WKWebView?

    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.regular)
        buildWindow()
        loadBundledSite()
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool {
        true
    }

    deinit {
        webView?.configuration.userContentController.removeScriptMessageHandler(forName: consoleHandlerName)
    }

    func userContentController(_ userContentController: WKUserContentController, didReceive message: WKScriptMessage) {
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
    }

    func webView(
        _ webView: WKWebView,
        didFail navigation: WKNavigation!,
        withError error: Error
    ) {
        log("navigation failed \(error.localizedDescription)")
        showErrorPage(
            title: "Could not launch Open Local Phraser V2",
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
            title: "Could not launch Open Local Phraser V2",
            message: error.localizedDescription
        )
    }

    func webViewWebContentProcessDidTerminate(_ webView: WKWebView) {
        log("web content process terminated")
        showErrorPage(
            title: "Open Local Phraser V2 stopped unexpectedly",
            message: "The embedded web content process terminated before the app finished rendering."
        )
    }

    private func buildWindow() {
        let configuration = WKWebViewConfiguration()
        configuration.websiteDataStore = .default()
        configuration.defaultWebpagePreferences.allowsContentJavaScript = true
        configuration.preferences.javaScriptCanOpenWindowsAutomatically = true

        let schemeHandler = BundleSchemeHandler(webDirectory: webDirectory)
        configuration.setURLSchemeHandler(schemeHandler, forURLScheme: scheme)

        let contentController = WKUserContentController()
        contentController.add(self, name: consoleHandlerName)
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
        window.makeKeyAndOrderFront(nil)

        self.window = window
        self.webView = webView
        NSApp.activate(ignoringOtherApps: true)
    }

    private func loadBundledSite() {
        logStartupDiagnostics()

        guard directoryExists(webDirectory) else {
            showErrorPage(
                title: "Could not launch Open Local Phraser V2",
                message: "The bundled web directory was not found at \(webDirectory.path)."
            )
            return
        }

        guard fileExists(indexURL) else {
            showErrorPage(
                title: "Could not launch Open Local Phraser V2",
                message: "The bundled index.html file was not found at \(indexURL.path)."
            )
            return
        }

        guard directoryExists(assetsDirectory) else {
            showErrorPage(
                title: "Could not launch Open Local Phraser V2",
                message: "The bundled assets directory was not found at \(assetsDirectory.path)."
            )
            return
        }

        let request = URLRequest(url: URL(string: "\(scheme)://localhost/index.html")!)
        log("loading \(request.url?.absoluteString ?? "<nil>")")
        webView?.load(request)
    }

    private func logStartupDiagnostics() {
        let resourcePath = Bundle.main.resourceURL?.path ?? "<missing>"
        log("resource path \(resourcePath)")
        log("web path \(webDirectory.path)")
        log("index path \(indexURL.path)")
        log("index exists \(fileExists(indexURL))")
        log("assets exists \(directoryExists(assetsDirectory))")
        log("model directory exists \(directoryExists(modelDirectory))")
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
