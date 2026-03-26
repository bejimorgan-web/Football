import 'dart:io';
import 'package:shared_preferences/shared_preferences.dart';

import 'api_config.dart';
import 'network_config.dart';

const String _manualBackendUrlPreferenceKey = 'manual_backend_url';

Future<String> resolveBackendUrl() async {
  final prefs = await SharedPreferences.getInstance();

  final manualOverride = prefs.getString(_manualBackendUrlPreferenceKey)?.trim();
  if (manualOverride != null && manualOverride.isNotEmpty) {
    return ApiConfig.normalize(manualOverride);
  }

  if (Platform.isAndroid) {
    return ApiConfig.normalize(NetworkConfig.baseUrl);
  }

  return ApiConfig.normalize(NetworkConfig.baseUrl);
}

Future<String?> getManualBackendUrl() async {
  final prefs = await SharedPreferences.getInstance();
  final value = prefs.getString(_manualBackendUrlPreferenceKey)?.trim();
  if (value == null || value.isEmpty) {
    return null;
  }
  return ApiConfig.normalize(value);
}

Future<void> setManualBackendUrl(String url) async {
  final prefs = await SharedPreferences.getInstance();
  await prefs.setString(_manualBackendUrlPreferenceKey, ApiConfig.normalize(url));
}

Future<void> clearManualBackendUrl() async {
  final prefs = await SharedPreferences.getInstance();
  await prefs.remove(_manualBackendUrlPreferenceKey);
}
