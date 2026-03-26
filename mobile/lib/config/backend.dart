import 'package:flutter/foundation.dart';

import 'api_config.dart';
import 'backend_web_stub.dart'
    if (dart.library.io) 'backend_io.dart' as backend_platform;

Future<String> resolveBackendUrl() async {
  if (kIsWeb) {
    return ApiConfig.normalize(await backend_platform.resolveBackendUrl());
  }

  return ApiConfig.normalize(await backend_platform.resolveBackendUrl());
}

Future<String?> getManualBackendUrl() {
  return backend_platform.getManualBackendUrl();
}

Future<void> setManualBackendUrl(String url) async {
  await backend_platform.setManualBackendUrl(url);
}

Future<void> clearManualBackendUrl() async {
  await backend_platform.clearManualBackendUrl();
}
