import 'dart:html' as html;

import 'api_config.dart';
import 'network_config.dart';

const String _manualBackendUrlStorageKey = 'manual_backend_url';

Future<String> resolveBackendUrl() async {
  final manualOverride = html.window.localStorage[_manualBackendUrlStorageKey]?.trim();
  if (manualOverride != null && manualOverride.isNotEmpty) {
    return ApiConfig.normalize(manualOverride);
  }
  final configured = NetworkConfig.baseUrl;
  if (configured.isNotEmpty) {
    return ApiConfig.normalize(configured);
  }
  return '';
}

Future<String?> getManualBackendUrl() async {
  final value = html.window.localStorage[_manualBackendUrlStorageKey]?.trim();
  if (value == null || value.isEmpty) {
    return null;
  }
  return ApiConfig.normalize(value);
}

Future<void> setManualBackendUrl(String url) async {
  final normalized = ApiConfig.normalize(url);
  if (normalized.isEmpty) {
    html.window.localStorage.remove(_manualBackendUrlStorageKey);
    return;
  }
  html.window.localStorage[_manualBackendUrlStorageKey] = normalized;
}

Future<void> clearManualBackendUrl() async {
  html.window.localStorage.remove(_manualBackendUrlStorageKey);
}
