import ExpoModulesCore
import Network

public final class QwenPawOAuthLoopbackModule: Module {
  private let listenerQueue = DispatchQueue(
    label: "io.agentscope.qwenpaw.oauth-loopback"
  )
  private var listener: NWListener?
  private var startContinuation: CheckedContinuation<Int, Error>?

  public func definition() -> ModuleDefinition {
    Name("QwenPawOAuthLoopback")

    AsyncFunction("startAsync") { () async throws -> Int in
      try await self.start()
    }

    AsyncFunction("stopAsync") {
      self.stop()
    }

    OnDestroy {
      self.stop()
    }
  }

  private func start() async throws -> Int {
    stop()
    return try await withCheckedThrowingContinuation { continuation in
      listenerQueue.async {
        do {
          let parameters = NWParameters.tcp
          parameters.requiredLocalEndpoint = .hostPort(
            host: "127.0.0.1",
            port: .any
          )
          let listener = try NWListener(using: parameters)
          self.listener = listener
          self.startContinuation = continuation
          listener.stateUpdateHandler = { [weak self] state in
            self?.handleListenerState(state)
          }
          listener.newConnectionHandler = { [weak self] connection in
            self?.handle(connection)
          }
          listener.start(queue: self.listenerQueue)
        } catch {
          continuation.resume(throwing: error)
        }
      }
    }
  }

  private func handleListenerState(_ state: NWListener.State) {
    switch state {
    case .ready:
      guard let port = listener?.port?.rawValue else {
        failStart("OAuth callback listener did not receive a port")
        return
      }
      startContinuation?.resume(returning: Int(port))
      startContinuation = nil
    case .failed(let error):
      failStart(error.localizedDescription)
      stop()
    case .cancelled:
      failStart("OAuth callback listener was cancelled")
    default:
      break
    }
  }

  private func handle(_ connection: NWConnection) {
    connection.start(queue: listenerQueue)
    connection.receive(
      minimumIncompleteLength: 1,
      maximumLength: 16_384
    ) { [weak self] data, _, _, _ in
      guard let self,
            let data,
            let request = String(data: data, encoding: .utf8) else {
        connection.cancel()
        return
      }
      let requestParts = request
        .split(separator: "\r\n", maxSplits: 1)
        .first?
        .split(separator: " ", maxSplits: 2) ?? []
      guard requestParts.count == 3,
            requestParts[0] == "GET",
            let components = URLComponents(
              string: "http://127.0.0.1\(requestParts[1])"
            ),
            components.path == "/callback/qwenpaw-mobile" else {
        self.respond(
          connection,
          status: "404 Not Found",
          body: "Not found"
        )
        return
      }
      let query = components.percentEncodedQuery
      let callback = "qwenpaw://platform-auth" +
        (query.map { "?\($0)" } ?? "")
      self.respond(
        connection,
        status: "302 Found",
        body: "Returning to QwenPaw",
        location: callback,
        stopAfterResponse: true
      )
    }
  }

  private func respond(
    _ connection: NWConnection,
    status: String,
    body: String,
    location: String? = nil,
    stopAfterResponse: Bool = false
  ) {
    var headers = [
      "HTTP/1.1 \(status)",
      "Content-Type: text/plain; charset=utf-8",
      "Cache-Control: no-store",
      "Content-Length: \(body.utf8.count)",
      "Connection: close"
    ]
    if let location {
      headers.append("Location: \(location)")
    }
    let response = (headers + ["", body]).joined(separator: "\r\n")
    connection.send(
      content: response.data(using: .utf8),
      completion: .contentProcessed { [weak self] _ in
        connection.cancel()
        if stopAfterResponse {
          self?.stop()
        }
      }
    )
  }

  private func failStart(_ message: String) {
    guard let continuation = startContinuation else {
      return
    }
    continuation.resume(throwing: NSError(
      domain: "QwenPawOAuthLoopback",
      code: 1,
      userInfo: [NSLocalizedDescriptionKey: message]
    ))
    startContinuation = nil
  }

  private func stop() {
    listenerQueue.async {
      self.listener?.cancel()
      self.listener = nil
    }
  }
}
