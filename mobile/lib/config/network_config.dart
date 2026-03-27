import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';

const String _defaultBackendUrl = String.fromEnvironment(
  'API_BASE_URL',
  defaultValue: 'http://127.0.0.1:8000',
);

class NetworkConfig {
  static String get baseUrl {
    if (kIsWeb) {
      return _defaultBackendUrl;
    }

    if (defaultTargetPlatform == TargetPlatform.android) {
      return _defaultBackendUrl;
    }

    return _defaultBackendUrl;
  }
}
