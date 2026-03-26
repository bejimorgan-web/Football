import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';

class NetworkConfig {
  static String get baseUrl {
    if (kIsWeb) {
      return 'http://localhost:8000';
    }

    if (defaultTargetPlatform == TargetPlatform.android) {
      return 'http://10.0.2.2:8000';
    }

    return 'http://127.0.0.1:8000';
  }
}
