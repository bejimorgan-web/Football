import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:http/http.dart' as http;
import 'package:shared_preferences/shared_preferences.dart';

import 'api_config.dart';
import 'network_config.dart';
import 'tenant_config.dart';

const String _manualBackendUrlPreferenceKey = 'manual_backend_url';
const String _resolverBackendUrlPreferenceKey = 'resolver_backend_url';
const String _resolverBackendFetchedAtPreferenceKey = 'resolver_backend_fetched_at';
const Duration _resolverCacheTtl = Duration(hours: 12);

Future<String> resolveBackendUrl() async {
  final prefs = await SharedPreferences.getInstance();

  final manualOverride = prefs.getString(_manualBackendUrlPreferenceKey)?.trim();
  if (manualOverride != null && manualOverride.isNotEmpty) {
    return ApiConfig.normalize(manualOverride);
  }

  final seedBackendUrl = ApiConfig.normalize(
    embeddedTenantBackendUrl.trim().isNotEmpty ? embeddedTenantBackendUrl : NetworkConfig.baseUrl,
  );
  final resolvedFromConfig = await _resolveBackendUrlFromConfig(prefs, seedBackendUrl);
  if (resolvedFromConfig != null && resolvedFromConfig.isNotEmpty) {
    return resolvedFromConfig;
  }

  if (Platform.isAndroid) {
    return seedBackendUrl;
  }

  return seedBackendUrl;
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

Future<String?> _resolveBackendUrlFromConfig(SharedPreferences prefs, String seedBackendUrl) async {
  final cachedUrl = prefs.getString(_resolverBackendUrlPreferenceKey)?.trim();
  final fetchedAtRaw = prefs.getString(_resolverBackendFetchedAtPreferenceKey)?.trim();
  final fetchedAt = fetchedAtRaw == null || fetchedAtRaw.isEmpty ? null : DateTime.tryParse(fetchedAtRaw);
  if (cachedUrl != null &&
      cachedUrl.isNotEmpty &&
      fetchedAt != null &&
      DateTime.now().toUtc().difference(fetchedAt.toUtc()) <= _resolverCacheTtl) {
    return ApiConfig.normalize(cachedUrl);
  }

  try {
    final response = await http
        .get(ApiConfig.uri(seedBackendUrl, '/api/config'))
        .timeout(const Duration(seconds: 4));
    if (response.statusCode != 200) {
      return cachedUrl == null || cachedUrl.isEmpty ? null : ApiConfig.normalize(cachedUrl);
    }
    final payload = jsonDecode(response.body);
    if (payload is! Map<String, dynamic>) {
      return cachedUrl == null || cachedUrl.isEmpty ? null : ApiConfig.normalize(cachedUrl);
    }
    final resolvedBackendUrl = ApiConfig.normalize(
      '${payload['backend_url'] ?? payload['backendUrl'] ?? payload['apiBaseUrl'] ?? ''}',
    );
    if (resolvedBackendUrl.isEmpty) {
      return cachedUrl == null || cachedUrl.isEmpty ? null : ApiConfig.normalize(cachedUrl);
    }
    await prefs.setString(_resolverBackendUrlPreferenceKey, resolvedBackendUrl);
    await prefs.setString(_resolverBackendFetchedAtPreferenceKey, DateTime.now().toUtc().toIso8601String());
    return resolvedBackendUrl;
  } on TimeoutException {
    return cachedUrl == null || cachedUrl.isEmpty ? null : ApiConfig.normalize(cachedUrl);
  } on SocketException {
    return cachedUrl == null || cachedUrl.isEmpty ? null : ApiConfig.normalize(cachedUrl);
  } on HttpException {
    return cachedUrl == null || cachedUrl.isEmpty ? null : ApiConfig.normalize(cachedUrl);
  } on FormatException {
    return cachedUrl == null || cachedUrl.isEmpty ? null : ApiConfig.normalize(cachedUrl);
  }
}
