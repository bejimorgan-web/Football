import CryptoKit
import Flutter
import UIKit

private let methodChannelName = "football_streaming/security"
private let eventChannelName = "football_streaming/security/events"
private let expectedBundleIdentifier = ""

final class SecurityEventStreamHandler: NSObject, FlutterStreamHandler {
  private var eventSink: FlutterEventSink?
  private var screenshotObserver: NSObjectProtocol?
  private var captureObserver: NSObjectProtocol?

  func onListen(withArguments arguments: Any?, eventSink events: @escaping FlutterEventSink) -> FlutterError? {
    eventSink = events
    screenshotObserver = NotificationCenter.default.addObserver(
      forName: UIApplication.userDidTakeScreenshotNotification,
      object: nil,
      queue: .main
    ) { [weak self] _ in
      self?.eventSink?("screen_capture_detected")
    }
    captureObserver = NotificationCenter.default.addObserver(
      forName: UIScreen.capturedDidChangeNotification,
      object: nil,
      queue: .main
    ) { [weak self] _ in
      if UIScreen.main.isCaptured {
        self?.eventSink?("screen_capture_detected")
      }
    }
    return nil
  }

  func onCancel(withArguments arguments: Any?) -> FlutterError? {
    if let observer = screenshotObserver {
      NotificationCenter.default.removeObserver(observer)
    }
    if let observer = captureObserver {
      NotificationCenter.default.removeObserver(observer)
    }
    screenshotObserver = nil
    captureObserver = nil
    eventSink = nil
    return nil
  }
}

@main
@objc class AppDelegate: FlutterAppDelegate, FlutterImplicitEngineDelegate {
  private let securityEvents = SecurityEventStreamHandler()

  override func application(
    _ application: UIApplication,
    didFinishLaunchingWithOptions launchOptions: [UIApplication.LaunchOptionsKey: Any]?
  ) -> Bool {
    let controller = window?.rootViewController as? FlutterViewController
    if let controller {
      let channel = FlutterMethodChannel(name: methodChannelName, binaryMessenger: controller.binaryMessenger)
      channel.setMethodCallHandler { [weak self] call, result in
        guard let self else { return }
        switch call.method {
        case "getSecuritySnapshot":
          result([
            "deviceFingerprint": self.deviceFingerprint(),
            "secureDevice": !self.isJailbroken(),
            "vpnActive": self.isVpnActive(),
            "appSignatureValid": self.isSignatureValid(),
            "preferredCountry": Locale.current.regionCode ?? "",
          ])
        case "enableSecurePlayback":
          result(nil)
        case "disableSecurePlayback":
          result(nil)
        default:
          result(FlutterMethodNotImplemented)
        }
      }

      let events = FlutterEventChannel(name: eventChannelName, binaryMessenger: controller.binaryMessenger)
      events.setStreamHandler(securityEvents)
    }
    return super.application(application, didFinishLaunchingWithOptions: launchOptions)
  }

  func didInitializeImplicitFlutterEngine(_ engineBridge: FlutterImplicitEngineBridge) {
    GeneratedPluginRegistrant.register(with: engineBridge.pluginRegistry)
  }

  private func deviceFingerprint() -> String {
    let identifier = UIDevice.current.identifierForVendor?.uuidString ?? "unknown-device"
    return sha256("\(identifier)|\(Bundle.main.bundleIdentifier ?? "")")
  }

  private func isSignatureValid() -> Bool {
    guard !expectedBundleIdentifier.isEmpty else { return true }
    return Bundle.main.bundleIdentifier == expectedBundleIdentifier
  }

  private func isJailbroken() -> Bool {
    #if targetEnvironment(simulator)
    return false
    #else
    let suspiciousPaths = [
      "/Applications/Cydia.app",
      "/Library/MobileSubstrate/MobileSubstrate.dylib",
      "/bin/bash",
      "/usr/sbin/sshd",
      "/etc/apt",
      "/private/var/lib/apt/",
    ]
    if suspiciousPaths.contains(where: { FileManager.default.fileExists(atPath: $0) }) {
      return true
    }
    if canOpen(path: "/Applications/Cydia.app") {
      return true
    }
    return false
    #endif
  }

  private func canOpen(path: String) -> Bool {
    return UIApplication.shared.canOpenURL(URL(fileURLWithPath: path))
  }

  private func isVpnActive() -> Bool {
    guard let settings = CFNetworkCopySystemProxySettings()?.takeRetainedValue() as? [String: Any],
          let scopes = settings["__SCOPED__"] as? [String: Any] else {
      return false
    }
    let keywords = ["tap", "tun", "ppp", "ipsec", "utun"]
    return scopes.keys.contains { key in
      keywords.contains(where: { key.localizedCaseInsensitiveContains($0) })
    }
  }

  private func sha256(_ text: String) -> String {
    let digest = SHA256.hash(data: Data(text.utf8))
    return digest.map { String(format: "%02x", $0) }.joined()
  }
}
