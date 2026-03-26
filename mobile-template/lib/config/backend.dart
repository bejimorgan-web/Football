import 'package:flutter/foundation.dart';

import 'app_config.dart';
import 'backend_web_stub.dart'
    if (dart.library.io) 'backend_io.dart' as backend_platform;

const String _localhostBackendUrl = embeddedServerUrl;

Future<String> resolveBackendUrl() async {
  if (kIsWeb) {
    return _localhostBackendUrl;
  }

  return backend_platform.resolveBackendUrl();
}

Future<String?> getManualBackendUrl() {
  if (kIsWeb) {
    return Future.value(null);
  }
  return backend_platform.getManualBackendUrl();
}

Future<void> setManualBackendUrl(String url) async {
  if (kIsWeb) {
    return;
  }
  await backend_platform.setManualBackendUrl(url);
}

Future<void> clearManualBackendUrl() async {
  if (kIsWeb) {
    return;
  }
  await backend_platform.clearManualBackendUrl();
}
