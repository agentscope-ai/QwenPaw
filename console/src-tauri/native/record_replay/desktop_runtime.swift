import AppKit
import Carbon
import ApplicationServices
import CoreGraphics
import Darwin
import Foundation

// Keep this boundary versioned and C-only. Rust owns transport, sessions,
// policy, retries, and storage; Swift owns mechanical macOS framework calls.
@_cdecl("qwenpaw_record_replay_abi_version")
public func qwenpawRecordReplayABIVersion() -> UInt32 {
    7
}

// Mechanical OS state only. Rust owns cancellation, failure publication and
// the Record lease. A generation remembers interruptions even if sleep/wake
// completes between two Rust checks, so an old recording never auto-resumes.
final class DesktopCaptureEnvironment {
    static let shared = DesktopCaptureEnvironment(center: NSWorkspace.shared.notificationCenter)
    private let lock = NSLock()
    private let center: NotificationCenter
    private var observers: [NSObjectProtocol] = []
    private var generation: UInt64 = 0
    private var suspended: Set<String> = []
    private var lastReason: UInt32 = 0
    private var foregroundPID: Int32 = 0
    private var applicationGeneration: UInt64 = 0

    init(center: NotificationCenter) {
        self.center = center
        for (name, key, blocked) in [
            (NSWorkspace.willSleepNotification, "sleep", true),
            (NSWorkspace.didWakeNotification, "sleep", false),
            (NSWorkspace.sessionDidResignActiveNotification, "session", true),
            (NSWorkspace.sessionDidBecomeActiveNotification, "session", false),
        ] {
            observers.append(center.addObserver(forName: name, object: nil, queue: nil) { [weak self] _ in
                self?.transition(key: key, blocked: blocked)
            })
        }
        observers.append(center.addObserver(forName: NSWorkspace.didActivateApplicationNotification,
                                           object: nil, queue: nil) { [weak self] note in
            let app = note.userInfo?[NSWorkspace.applicationUserInfoKey] as? NSRunningApplication
            self?.setForegroundPID(app?.processIdentifier ?? 0)
        })
    }

    deinit {
        observers.forEach(center.removeObserver)
    }

    private func transition(key: String, blocked: Bool) {
        lock.lock()
        defer { lock.unlock() }
        generation &+= 1
        if blocked { suspended.insert(key) } else { suspended.remove(key) }
    }

    func snapshot(reason: UInt32) -> (UInt64, UInt32) {
        lock.lock()
        defer { lock.unlock() }
        let current: UInt32 = suspended.isEmpty ? reason : 3
        if current != 0 && current != lastReason { generation &+= 1 }
        lastReason = current
        return (generation, current)
    }

    // Called by the EventTap: memory-only, no AX, session query or disk IO.
    func allowsDelivery(generation expected: UInt64) -> Bool {
        lock.lock()
        defer { lock.unlock() }
        return generation == expected && suspended.isEmpty && lastReason == 0
    }

    // App identity is captured in memory with each input primitive. The
    // worker must not attribute queued input using a later foreground app.
    func setForegroundPID(_ pid: Int32) {
        lock.lock()
        defer { lock.unlock() }
        if foregroundPID != pid { applicationGeneration &+= 1 }
        foregroundPID = pid
    }

    func applicationSnapshot() -> (pid: Int32, generation: UInt64) {
        lock.lock()
        defer { lock.unlock() }
        return (foregroundPID, applicationGeneration)
    }
}

private func refreshDesktopApplication() -> (pid: Int32, generation: UInt64) {
    let read = { () -> (pid: Int32, generation: UInt64) in
        let environment = DesktopCaptureEnvironment.shared
        environment.setForegroundPID(NSWorkspace.shared.frontmostApplication?.processIdentifier ?? 0)
        return environment.applicationSnapshot()
    }
    return Thread.isMainThread ? read() : DispatchQueue.main.sync(execute: read)
}

func desktopCaptureSessionReason(_ session: [String: Any]?) -> UInt32 {
    guard let session else { return 4 }
    // The SDK constant maps to "kCGSSessionOnConsoleKey", not its symbol
    // name. An absent/unknown console state must not allow recording.
    guard let onConsole = session[kCGSessionOnConsoleKey as String] as? NSNumber,
          onConsole.boolValue else { return 4 }
    guard let raw = session["CGSSessionScreenIsLocked"] else { return 0 }
    guard let locked = raw as? NSNumber else { return 4 }
    return locked.boolValue ? 1 : 0
}

@_cdecl("qwenpaw_record_replay_capture_guard")
public func qwenpawRecordReplayCaptureGuard(_ generation: UnsafeMutablePointer<UInt64>?) -> UInt32 {
    let read = { () -> (UInt64, UInt32) in
        // Carbon declares Secure Event Input queries non-thread-safe: all OS
        // reads and singleton initialization are serialized on the main queue.
        var reason = desktopCaptureSessionReason(CGSessionCopyCurrentDictionary() as? [String: Any])
        if reason == 0 && IsSecureEventInputEnabled() { reason = 2 }
        if reason == 0 && (!CGPreflightListenEventAccess() || !AXIsProcessTrusted()) { reason = 5 }
        return DesktopCaptureEnvironment.shared.snapshot(reason: reason)
    }
    let value = Thread.isMainThread ? read() : DispatchQueue.main.sync(execute: read)
    generation?.pointee = value.0
    return value.1
}

public typealias QwenPawEmergencyStopCallback = @convention(c) () -> Void

private final class DesktopActivityPresenter: NSObject {
    static let shared = DesktopActivityPresenter()

    private var statusItem: NSStatusItem?
    private var emergencyStop: QwenPawEmergencyStopCallback?

    func set(
        activity: UInt32,
        emergencyStop: QwenPawEmergencyStopCallback?
    ) {
        self.emergencyStop = emergencyStop
        switch activity {
        case 1:
            let item = ensureStatusItem()
            item.button?.title = "◉ QwenPaw Control"
            item.menu = nil
        case 2:
            let item = ensureStatusItem()
            item.button?.title = "● QwenPaw Recording"
            let menu = NSMenu()
            let stop = NSMenuItem(
                title: "Stop Recording",
                action: #selector(stopRecording),
                keyEquivalent: ""
            )
            stop.target = self
            menu.addItem(stop)
            item.menu = menu
        default:
            if let statusItem {
                NSStatusBar.system.removeStatusItem(statusItem)
                self.statusItem = nil
            }
        }
    }

    private func ensureStatusItem() -> NSStatusItem {
        if let statusItem {
            return statusItem
        }
        let item = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
        item.button?.toolTip = "QwenPaw desktop automation activity"
        statusItem = item
        return item
    }

    @objc private func stopRecording() {
        guard let emergencyStop else {
            return
        }
        statusItem?.button?.title = "● Stopping QwenPaw Recording…"
        DispatchQueue.global(qos: .userInitiated).async {
            emergencyStop()
        }
    }
}

@_cdecl("qwenpaw_record_replay_indicator_set")
public func qwenpawRecordReplayIndicatorSet(
    _ activity: UInt32,
    _ emergencyStop: QwenPawEmergencyStopCallback?
) {
    let update = {
        DesktopActivityPresenter.shared.set(
            activity: activity,
            emergencyStop: emergencyStop
        )
    }
    if Thread.isMainThread {
        update()
    } else {
        DispatchQueue.main.async(execute: update)
    }
}

@_cdecl("qwenpaw_record_replay_input_monitoring_preflight")
public func qwenpawRecordReplayInputMonitoringPreflight() -> Bool {
    CGPreflightListenEventAccess()
}

@_cdecl("qwenpaw_record_replay_input_monitoring_request")
public func qwenpawRecordReplayInputMonitoringRequest() -> Bool {
    if Thread.isMainThread {
        return CGRequestListenEventAccess()
    }
    return DispatchQueue.main.sync {
        CGRequestListenEventAccess()
    }
}

@_cdecl("qwenpaw_record_replay_accessibility_preflight")
public func qwenpawRecordReplayAccessibilityPreflight() -> Bool {
    AXIsProcessTrusted()
}

@_cdecl("qwenpaw_record_replay_accessibility_request")
public func qwenpawRecordReplayAccessibilityRequest() -> Bool {
    let request = {
        let options = [
            kAXTrustedCheckOptionPrompt.takeUnretainedValue() as String: true,
        ] as CFDictionary
        return AXIsProcessTrustedWithOptions(options)
    }
    if Thread.isMainThread {
        return request()
    }
    return DispatchQueue.main.sync(execute: request)
}

// AX data crosses the ABI only as an allowlisted JSON object. The native
// layer never reads AXValue, selected text, clipboard contents, or keyboard
// characters. Rust owns the returned allocation and must release it with the
// paired free function below.
private let allowedNamedRoles: Set<String> = [
    "AXButton",
    "AXCheckBox",
    "AXComboBox",
    "AXDisclosureTriangle",
    "AXLink",
    "AXMenuButton",
    "AXMenuItem",
    "AXPopUpButton",
    "AXRadioButton",
    "AXSlider",
    "AXTabGroup",
    "AXToolbar",
]
private let secureRoles: Set<String> = ["AXSecureTextField"]

// AppKit's NSSecureTextField exposes AXTextField plus AXSecureTextField
// subrole. Some providers use the secure role directly; accept either.
func desktopTargetIsSecure(role: String?, subrole: String?) -> Bool {
    role.map { secureRoles.contains($0) } == true
        || subrole.map { secureRoles.contains($0) } == true
}

private let contentBearingRoles: Set<String> = [
    "AXSecureTextField",
    "AXTextArea",
    "AXTextField",
]
private let pointerTargetEventTypes: Set<UInt32> = [
    CGEventType.leftMouseDown.rawValue,
    CGEventType.rightMouseDown.rawValue,
    CGEventType.scrollWheel.rawValue,
    CGEventType.otherMouseDown.rawValue,
]
private let deferredPointerEventTypes: Set<UInt32> = [
    CGEventType.leftMouseUp.rawValue,
    CGEventType.rightMouseUp.rawValue,
    CGEventType.leftMouseDragged.rawValue,
    CGEventType.rightMouseDragged.rawValue,
    CGEventType.otherMouseUp.rawValue,
    CGEventType.otherMouseDragged.rawValue,
]

private func limitedString(_ value: String?) -> String? {
    guard let value else {
        return nil
    }
    let normalized = value
        .replacingOccurrences(of: "\n", with: " ")
        .replacingOccurrences(of: "\r", with: " ")
        .trimmingCharacters(in: .whitespacesAndNewlines)
    guard !normalized.isEmpty else {
        return nil
    }
    return String(normalized.prefix(160))
}

private func stringAttribute(
    _ element: AXUIElement,
    _ attribute: CFString
) -> String? {
    var raw: CFTypeRef?
    guard AXUIElementCopyAttributeValue(element, attribute, &raw) == .success,
          let value = raw as? String else {
        return nil
    }
    return limitedString(value)
}

private func elementRole(_ element: AXUIElement) -> String? {
    stringAttribute(element, kAXRoleAttribute as CFString)
}

private func elementBounds(_ element: AXUIElement) -> [String: Double]? {
    var rawPosition: CFTypeRef?
    var rawSize: CFTypeRef?
    guard AXUIElementCopyAttributeValue(
        element,
        kAXPositionAttribute as CFString,
        &rawPosition
    ) == .success,
        AXUIElementCopyAttributeValue(
            element,
            kAXSizeAttribute as CFString,
            &rawSize
        ) == .success,
        let rawPosition,
        let rawSize,
        CFGetTypeID(rawPosition) == AXValueGetTypeID(),
        CFGetTypeID(rawSize) == AXValueGetTypeID() else {
        return nil
    }
    let positionValue = rawPosition as! AXValue
    let sizeValue = rawSize as! AXValue
    var point = CGPoint.zero
    var size = CGSize.zero
    guard AXValueGetValue(positionValue, .cgPoint, &point),
          AXValueGetValue(sizeValue, .cgSize, &size) else {
        return nil
    }
    return [
        "x": point.x,
        "y": point.y,
        "width": size.width,
        "height": size.height,
    ]
}

private func focusedElement(_ systemWide: AXUIElement) -> AXUIElement? {
    var raw: CFTypeRef?
    guard AXUIElementCopyAttributeValue(
        systemWide,
        kAXFocusedUIElementAttribute as CFString,
        &raw
    ) == .success,
        let raw else {
        return nil
    }
    return (raw as! AXUIElement)
}

private func focusedApplication(_ systemWide: AXUIElement) -> AXUIElement? {
    var raw: CFTypeRef?
    guard AXUIElementCopyAttributeValue(
        systemWide,
        kAXFocusedApplicationAttribute as CFString,
        &raw
    ) == .success,
        let raw else {
        return nil
    }
    return (raw as! AXUIElement)
}

private func elementAtPosition(
    _ systemWide: AXUIElement,
    x: Double,
    y: Double
) -> AXUIElement? {
    var element: AXUIElement?
    guard AXUIElementCopyElementAtPosition(
        systemWide,
        Float(x),
        Float(y),
        &element
    ) == .success else {
        return nil
    }
    return element
}

private func runningApplicationPayload(
    _ application: NSRunningApplication?
) -> [String: Any]? {
    guard let application else {
        return nil
    }
    var payload: [String: Any] = [
        "pid": application.processIdentifier,
    ]
    if let bundleID = limitedString(application.bundleIdentifier) {
        payload["bundle_id"] = bundleID
    }
    if let name = limitedString(application.localizedName) {
        payload["name"] = name
    }
    return payload
}

private func windowElement(
    target: AXUIElement?,
    application: AXUIElement
) -> AXUIElement? {
    if let target {
        var raw: CFTypeRef?
        if AXUIElementCopyAttributeValue(
            target,
            kAXWindowAttribute as CFString,
            &raw
        ) == .success,
            let raw {
            return (raw as! AXUIElement)
        }
    }
    var raw: CFTypeRef?
    guard AXUIElementCopyAttributeValue(
        application,
        kAXFocusedWindowAttribute as CFString,
        &raw
    ) == .success,
        let raw else {
        return nil
    }
    return (raw as! AXUIElement)
}

private func windowPayload(_ window: AXUIElement) -> [String: Any] {
    var payload: [String: Any] = [
        "role": elementRole(window) ?? "AXWindow",
    ]
    if let title = stringAttribute(window, kAXTitleAttribute as CFString) {
        payload["title"] = title
    }
    if let bounds = elementBounds(window) {
        payload["bounds"] = bounds
    }
    return payload
}

private func targetPayload(
    _ element: AXUIElement
) -> (payload: [String: Any], role: String?) {
    let role = elementRole(element)
    let subrole = stringAttribute(element, kAXSubroleAttribute as CFString)
    let secure = desktopTargetIsSecure(role: role, subrole: subrole)
    var payload: [String: Any] = [:]
    if let role {
        payload["role"] = role
    }
    if role != nil || subrole != nil {
        payload["secure"] = secure
    }
    if let subrole {
        payload["subrole"] = subrole
    }
    if let identifier = stringAttribute(
        element,
        kAXIdentifierAttribute as CFString
    ) {
        payload["identifier"] = identifier
    }
    if let role,
       !secure,
       !contentBearingRoles.contains(role),
       allowedNamedRoles.contains(role),
       let name = stringAttribute(element, kAXTitleAttribute as CFString)
            ?? stringAttribute(element, kAXDescriptionAttribute as CFString) {
        payload["name"] = name
    }
    if let bounds = elementBounds(element) {
        payload["bounds"] = bounds
    }
    return (payload, role)
}

private func enrichmentPayload(
    eventType: UInt32,
    eventTimestamp: UInt64,
    x: Double,
    y: Double
) -> [String: Any] {
    let started = DispatchTime.now().uptimeNanoseconds
    let frontmost = NSWorkspace.shared.frontmostApplication
    var running: NSRunningApplication?
    var target: AXUIElement?
    var targetStatus = AXIsProcessTrusted()
        ? "element_unavailable"
        : "accessibility_denied"

    if AXIsProcessTrusted() {
        let systemWide = AXUIElementCreateSystemWide()
        AXUIElementSetMessagingTimeout(systemWide, 0.20)
        if let focusedApplication = focusedApplication(systemWide) {
            var focusedPID: pid_t = 0
            if AXUIElementGetPid(focusedApplication, &focusedPID) == .success,
               focusedPID > 0 {
                running = NSRunningApplication(
                    processIdentifier: focusedPID
                ) ?? frontmost
            }
        }
        let pointer = pointerTargetEventTypes.contains(eventType)
            || deferredPointerEventTypes.contains(eventType)
        target = pointer
            ? elementAtPosition(systemWide, x: x, y: y)
            : focusedElement(systemWide)
        // Every pointer phase needs an actual hit-app identity. Falling back
        // to the foreground app would leak clicks in excluded background apps.
        if pointer { running = nil }
        if let target {
            AXUIElementSetMessagingTimeout(target, 0.20)
            var pid: pid_t = 0
            if AXUIElementGetPid(target, &pid) == .success, pid > 0 {
                running = NSRunningApplication(processIdentifier: pid)
            }
        }
    }

    var payload: [String: Any] = [:]
    if let app = runningApplicationPayload(running) {
        payload["app"] = app
    }
    if let target, !deferredPointerEventTypes.contains(eventType) {
        let result = targetPayload(target)
        if !result.payload.isEmpty {
            payload["target"] = result.payload
        }
        targetStatus = result.role == nil ? "role_unavailable" : "ok"
    }
    if let running, !deferredPointerEventTypes.contains(eventType) {
        let application = AXUIElementCreateApplication(
            running.processIdentifier
        )
        AXUIElementSetMessagingTimeout(application, 0.20)
        if let window = windowElement(target: target, application: application) {
            payload["window"] = windowPayload(window)
        }
    }

    if deferredPointerEventTypes.contains(eventType) {
        targetStatus = "deferred_to_pointer_down"
    }

    let completed = DispatchTime.now().uptimeNanoseconds
    let queueDelay = started >= eventTimestamp
        ? started - eventTimestamp
        : 0
    let totalLatency = completed >= eventTimestamp
        ? completed - eventTimestamp
        : completed - started
    payload["enrichment"] = [
        "status": targetStatus,
        "app_status": running == nil ? "unavailable" : "ok",
        "queue_delay_ms": Double(queueDelay) / 1_000_000.0,
        "duration_ms": Double(completed - started) / 1_000_000.0,
        "total_latency_ms": Double(totalLatency) / 1_000_000.0,
    ]
    return payload
}

@_cdecl("qwenpaw_record_replay_event_enrich_json")
public func qwenpawRecordReplayEventEnrichJSON(
    _ eventType: UInt32,
    _ eventTimestamp: UInt64,
    _ x: Double,
    _ y: Double,
    _ foregroundPID: Int64,
    _ applicationGeneration: UInt64
) -> UnsafeMutablePointer<CChar>? {
    let before = refreshDesktopApplication()
    guard foregroundPID > 0, Int64(before.pid) == foregroundPID,
          before.generation == applicationGeneration,
          let capturedApp = runningApplicationPayload(NSRunningApplication(processIdentifier: before.pid)) else {
        return nil
    }
    var payload = enrichmentPayload(
        eventType: eventType,
        eventTimestamp: eventTimestamp,
        x: x,
        y: y
    )
    let after = refreshDesktopApplication()
    guard after.pid == before.pid, after.generation == before.generation else { return nil }
    // Internal, ephemeral identity: Rust checks both capture and target apps,
    // then drops this field before writing the public evidence projection.
    payload["capture_app"] = capturedApp
    guard JSONSerialization.isValidJSONObject(payload),
          let data = try? JSONSerialization.data(
              withJSONObject: payload,
              options: [.sortedKeys]
          ),
          let json = String(data: data, encoding: .utf8) else {
        return nil
    }
    return strdup(json)
}

@_cdecl("qwenpaw_record_replay_string_free")
public func qwenpawRecordReplayStringFree(
    _ value: UnsafeMutablePointer<CChar>?
) {
    free(value)
}

public typealias QwenPawInputEventCallback = @convention(c) (
    UnsafeMutableRawPointer?,
    UInt32,
    UInt64,
    Int64,
    Double,
    Double,
    Double,
    Double,
    UInt64,
    UInt16,
    Int64,
    Int64,
    Int64,
    UInt64
) -> Void

// Removing a source from a run loop only unschedules callbacks. Invalidate
// both CF objects to break their retained relationship and unregister the
// underlying port. Also handles a tap whose run-loop source failed to form.
// Internal visibility lets native tests exercise real CF resources without
// asking for event-listening access or capturing user input.
func invalidateDesktopInputTap(_ tap: CFMachPort, source: CFRunLoopSource?) {
    precondition(Thread.isMainThread)
    if let source {
        CFRunLoopRemoveSource(CFRunLoopGetMain(), source, .commonModes)
        CFRunLoopSourceInvalidate(source)
    }
    CFMachPortInvalidate(tap)
}

private final class DesktopInputSource {
    private enum Lifecycle {
        case idle
        case starting
        case running
        case stopping
    }

    private let condition = NSCondition()
    private var callbacksInFlight = 0
    private var lifecycle = Lifecycle.idle
    private var tap: CFMachPort?
    private var source: CFRunLoopSource?
    private var callback: QwenPawInputEventCallback?
    private var callbackContext: UnsafeMutableRawPointer?
    private var captureGeneration: UInt64 = 0

    func start(
        callback: @escaping QwenPawInputEventCallback,
        callbackContext: UnsafeMutableRawPointer?
    ) -> Int32 {
        guard CGPreflightListenEventAccess() else {
            return 13 // EACCES
        }
        var generation: UInt64 = 0
        guard qwenpawRecordReplayCaptureGuard(&generation) == 0 else {
            return 125 // ECANCELED: unsafe desktop environment
        }
        _ = refreshDesktopApplication()

        condition.lock()
        guard lifecycle == .idle, tap == nil, source == nil else {
            condition.unlock()
            return 16 // EBUSY
        }
        lifecycle = .starting
        self.callback = callback
        self.callbackContext = callbackContext
        captureGeneration = generation
        condition.unlock()

        let opaqueSelf = Unmanaged.passUnretained(self).toOpaque()
        let install = { () -> (CFMachPort, CFRunLoopSource)? in
            guard let newTap = CGEvent.tapCreate(
                tap: .cgSessionEventTap,
                place: .tailAppendEventTap,
                options: .listenOnly,
                eventsOfInterest: DesktopInputSource.eventMask(),
                callback: desktopInputCallback,
                userInfo: opaqueSelf
            ) else {
                return nil
            }
            guard let newSource = CFMachPortCreateRunLoopSource(
                kCFAllocatorDefault,
                newTap,
                0
            ) else {
                CGEvent.tapEnable(tap: newTap, enable: false)
                invalidateDesktopInputTap(newTap, source: nil)
                return nil
            }

            let mainRunLoop = CFRunLoopGetMain()
            CFRunLoopAddSource(mainRunLoop, newSource, .commonModes)
            CGEvent.tapEnable(tap: newTap, enable: true)
            CFRunLoopWakeUp(mainRunLoop)
            return (newTap, newSource)
        }
        let resources = Thread.isMainThread
            ? install()
            : DispatchQueue.main.sync(execute: install)

        condition.lock()
        guard let (newTap, newSource) = resources else {
            lifecycle = .idle
            self.callback = nil
            self.callbackContext = nil
            condition.broadcast()
            condition.unlock()
            return 5 // EIO
        }
        tap = newTap
        source = newSource
        lifecycle = .running
        condition.broadcast()
        condition.unlock()
        return 0
    }

    func stop() -> Int32 {
        condition.lock()
        while lifecycle == .starting || lifecycle == .stopping {
            condition.wait()
        }
        guard lifecycle == .running, let tap, let source else {
            callback = nil
            callbackContext = nil
            while callbacksInFlight > 0 {
                condition.wait()
            }
            condition.unlock()
            return 0
        }
        lifecycle = .stopping
        condition.unlock()

        let uninstall = {
            CGEvent.tapEnable(tap: tap, enable: false)
            invalidateDesktopInputTap(tap, source: source)
            CFRunLoopWakeUp(CFRunLoopGetMain())
        }
        if Thread.isMainThread {
            uninstall()
        } else {
            DispatchQueue.main.sync(execute: uninstall)
        }

        condition.lock()
        self.tap = nil
        self.source = nil
        callback = nil
        callbackContext = nil
        while callbacksInFlight > 0 {
            condition.wait()
        }
        lifecycle = .idle
        condition.broadcast()
        condition.unlock()
        return 0
    }

    func deliver(type: CGEventType, event: CGEvent) {
        guard DesktopCaptureEnvironment.shared.allowsDelivery(generation: captureGeneration) else {
            return
        }
        if type == .tapDisabledByTimeout || type == .tapDisabledByUserInput {
            // Disabled capture has an unknown evidence gap. Latch an
            // interruption for Rust to cancel instead of silently re-enabling.
            _ = DesktopCaptureEnvironment.shared.snapshot(reason: 4)
            return
        }

        condition.lock()
        let callback = callback
        let callbackContext = callbackContext
        guard let callback else {
            condition.unlock()
            return
        }
        callbacksInFlight += 1
        condition.unlock()
        let application = DesktopCaptureEnvironment.shared.applicationSnapshot()
        callback(
            callbackContext,
            type.rawValue,
            event.timestamp,
            event.getIntegerValueField(.eventSourceUnixProcessID),
            event.location.x,
            event.location.y,
            Double(event.getIntegerValueField(.scrollWheelEventDeltaAxis2)),
            Double(event.getIntegerValueField(.scrollWheelEventDeltaAxis1)),
            event.flags.rawValue,
            UInt16(
                truncatingIfNeeded: event.getIntegerValueField(
                    .keyboardEventKeycode
                )
            ),
            event.getIntegerValueField(.mouseEventButtonNumber),
            event.getIntegerValueField(.mouseEventClickState),
            Int64(application.pid),
            application.generation
        )
        condition.lock()
        callbacksInFlight -= 1
        if callbacksInFlight == 0 {
            condition.broadcast()
        }
        condition.unlock()
    }

    private static func eventMask() -> CGEventMask {
        let types: [CGEventType] = [
            .leftMouseDown,
            .leftMouseUp,
            .rightMouseDown,
            .rightMouseUp,
            .otherMouseDown,
            .otherMouseUp,
            .leftMouseDragged,
            .rightMouseDragged,
            .otherMouseDragged,
            .keyDown,
            .keyUp,
            .flagsChanged,
            .scrollWheel,
        ]
        return types.reduce(CGEventMask(0)) { mask, type in
            mask | (CGEventMask(1) << type.rawValue)
        }
    }
}

private let desktopInputCallback: CGEventTapCallBack = {
    _, type, event, userInfo in
    guard let userInfo else {
        return Unmanaged.passUnretained(event)
    }
    let retained = Unmanaged<DesktopInputSource>
        .fromOpaque(userInfo)
        .retain()
    let source = retained.takeUnretainedValue()
    source.deliver(type: type, event: event)
    retained.release()
    return Unmanaged.passUnretained(event)
}

@_cdecl("qwenpaw_record_replay_input_source_create")
public func qwenpawRecordReplayInputSourceCreate() -> UnsafeMutableRawPointer {
    Unmanaged.passRetained(DesktopInputSource()).toOpaque()
}

@_cdecl("qwenpaw_record_replay_input_source_start")
public func qwenpawRecordReplayInputSourceStart(
    _ rawSource: UnsafeMutableRawPointer?,
    _ callback: QwenPawInputEventCallback?,
    _ callbackContext: UnsafeMutableRawPointer?
) -> Int32 {
    guard let rawSource, let callback else {
        return 22 // EINVAL
    }
    let source = Unmanaged<DesktopInputSource>
        .fromOpaque(rawSource)
        .takeUnretainedValue()
    return source.start(
        callback: callback,
        callbackContext: callbackContext
    )
}

@_cdecl("qwenpaw_record_replay_input_source_stop")
public func qwenpawRecordReplayInputSourceStop(
    _ rawSource: UnsafeMutableRawPointer?
) -> Int32 {
    guard let rawSource else {
        return 22 // EINVAL
    }
    let source = Unmanaged<DesktopInputSource>
        .fromOpaque(rawSource)
        .takeUnretainedValue()
    return source.stop()
}

@_cdecl("qwenpaw_record_replay_input_source_destroy")
public func qwenpawRecordReplayInputSourceDestroy(
    _ rawSource: UnsafeMutableRawPointer?
) {
    guard let rawSource else {
        return
    }
    let retained = Unmanaged<DesktopInputSource>.fromOpaque(rawSource)
    _ = retained.takeUnretainedValue().stop()
    retained.release()
}
