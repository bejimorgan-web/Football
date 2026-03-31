import 'dart:html' as html;
import 'dart:convert';

import 'api_config.dart';
import 'network_config.dart';

const String _manualBackendUrlStorageKey = 'manual_backend_url';
const Duration _resolverTimeout = Duration(seconds: 4);

Future<String> resolveBackendUrl() async {
  final manualOverride = html.window.localStorage[_manualBackendUrlStorageKey]?.trim();
  if (manualOverride != null && manualOverride.isNotEmpty) {
    return ApiConfig.normalize(manualOverride);
  }

  final configured = ApiConfig.normalize(NetworkConfig.baseUrl);
  if (configured.isNotEmpty) {
    final resolved = await _resolveBackendUrlFromConfig(configured);
    return resolved ?? configured;
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

Future<String?> _resolveBackendUrlFromConfig(String seedBackendUrl) async {
  if (seedBackendUrl.isEmpty) {
    return null;
  }

  try {
    final response = await html.HttpRequest.request(
      ApiConfig.uri(seedBackendUrl, '/api/config').toString(),
      method: 'GET',
    ).timeout(_resolverTimeout);
    if (response.status != 200 || response.responseText == null || response.responseText!.trim().isEmpty) {
      return null;
    }
    final payload = jsonDecode(response.responseText!);
    if (payload is! Map<String, dynamic>) {
      return null;
    }
    final resolved = ApiConfig.normalize(
      '${payload['backend_url'] ?? payload['backendApiUrl'] ?? payload['backend_api_url'] ?? payload['apiBaseUrl'] ?? ''}',
    );
    return resolved.isEmpty ? null : resolved;
  } catch (_) {
    return null;
  }
}
