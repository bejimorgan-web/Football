import 'dart:async';

import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart';

class SecuritySnapshot {
  const SecuritySnapshot({
    required this.deviceFingerprint,
    required this.secureDevice,
    required this.vpnActive,
    required this.appSignatureValid,
    required this.preferredCountry,
  });

  final String deviceFingerprint;
  final bool secureDevice;
  final bool vpnActive;
  final bool appSignatureValid;
  final String preferredCountry;

  factory SecuritySnapshot.fromMap(Map<Object?, Object?> map) {
    return SecuritySnapshot(
      deviceFingerprint: '${map['deviceFingerprint'] ?? ''}',
      secureDevice: map['secureDevice'] != false,
      vpnActive: map['vpnActive'] == true,
      appSignatureValid: map['appSignatureValid'] != false,
      preferredCountry: '${map['preferredCountry'] ?? PlatformDispatcher.instance.locale.countryCode ?? ''}',
    );
  }
}

class SecurityService {
  SecurityService._();

  static const MethodChannel _channel = MethodChannel('football_streaming/security');
  static const EventChannel _events = EventChannel('football_streaming/security/events');

  static Stream<String> watchSecurityEvents() {
    if (kIsWeb) {
      return const Stream<String>.empty();
    }
    return _events.receiveBroadcastStream().map((event) => '$event');
  }

  static Future<SecuritySnapshot> getSecuritySnapshot() async {
    if (kIsWeb) {
      return SecuritySnapshot(
        deviceFingerprint: 'web-master-client',
        secureDevice: true,
        vpnActive: false,
        appSignatureValid: true,
        preferredCountry: PlatformDispatcher.instance.locale.countryCode ?? '',
      );
    }
    final payload = await _channel.invokeMethod<Map<Object?, Object?>>('getSecuritySnapshot') ?? <Object?, Object?>{};
    return SecuritySnapshot.fromMap(payload);
  }

  static Future<void> enableSecurePlayback() {
    if (kIsWeb) {
      return Future.value();
    }
    return _channel.invokeMethod<void>('enableSecurePlayback');
  }

  static Future<void> disableSecurePlayback() {
    if (kIsWeb) {
      return Future.value();
    }
    return _channel.invokeMethod<void>('disableSecurePlayback');
  }
}
