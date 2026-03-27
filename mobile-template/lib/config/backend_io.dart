import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:device_info_plus/device_info_plus.dart';
import 'package:http/http.dart' as http;
import 'package:shared_preferences/shared_preferences.dart';

import 'app_config.dart';

const String _localhostBackendUrl = embeddedServerUrl;
const String _defaultApiUrl = String.fromEnvironment(
  'API_BASE_URL',
  defaultValue: 'http://127.0.0.1:8000',
);
const String _androidEmulatorBackendUrl = _defaultApiUrl;
const String _manualBackendUrlPreferenceKey = 'manual_backend_url';
const String _detectedBackendUrlPreferenceKey = 'detected_backend_url';
const String _resolverBackendUrlPreferenceKey = 'resolver_backend_url';
const String _resolverBackendFetchedAtPreferenceKey = 'resolver_backend_fetched_at';
const List<String> _networkPrefixes = <String>['192.168.0', '192.168.1'];
const int _backendPort = 8000;
const Duration _resolverCacheTtl = Duration(hours: 12);

Future<String> resolveBackendUrl() async {
  final prefs = await SharedPreferences.getInstance();

  final manualOverride = prefs.getString(_manualBackendUrlPreferenceKey)?.trim();
  if (manualOverride != null && manualOverride.isNotEmpty) {
    return _normalizeBackendUrl(manualOverride);
  }

  if ((prefs.getString(_resolverBackendUrlPreferenceKey)?.trim().isEmpty ?? true)) {
    await prefs.setString(
      _resolverBackendUrlPreferenceKey,
      _normalizeBackendUrl(_localhostBackendUrl.isEmpty ? _defaultApiUrl : _localhostBackendUrl),
    );
  }

  final resolvedFromApiConfig = await _resolveApiBaseUrlFromResolver(prefs, _localhostBackendUrl);
  if (resolvedFromApiConfig != null) {
    return resolvedFromApiConfig;
  }

  final deviceInfo = DeviceInfoPlugin();

  if (Platform.isAndroid) {
    final androidInfo = await deviceInfo.androidInfo;
    if (!androidInfo.isPhysicalDevice) {
      return _androidEmulatorBackendUrl;
    }

    final detected = await _resolveRealDeviceBackendUrl(prefs);
    return detected ?? _localhostBackendUrl;
  }

  if (Platform.isIOS) {
    final iosInfo = await deviceInfo.iosInfo;
    if (!iosInfo.isPhysicalDevice) {
      return _localhostBackendUrl;
    }

    final detected = await _resolveRealDeviceBackendUrl(prefs);
    return detected ?? _localhostBackendUrl;
  }

  return _localhostBackendUrl;
}

Future<String?> getManualBackendUrl() async {
  final prefs = await SharedPreferences.getInstance();
  final value = prefs.getString(_manualBackendUrlPreferenceKey)?.trim();
  if (value == null || value.isEmpty) {
    return null;
  }
  return _normalizeBackendUrl(value);
}

Future<void> setManualBackendUrl(String url) async {
  final prefs = await SharedPreferences.getInstance();
  await prefs.setString(_manualBackendUrlPreferenceKey, _normalizeBackendUrl(url));
}

Future<void> clearManualBackendUrl() async {
  final prefs = await SharedPreferences.getInstance();
  await prefs.remove(_manualBackendUrlPreferenceKey);
}

Future<String?> _resolveRealDeviceBackendUrl(SharedPreferences prefs) async {
  final cached = prefs.getString(_detectedBackendUrlPreferenceKey)?.trim();
  if (cached != null && cached.isNotEmpty && await _isHealthyBackend(cached)) {
    return _normalizeBackendUrl(cached);
  }

  final discovered = await _scanLocalNetworkForBackend();
  if (discovered != null) {
    await prefs.setString(_detectedBackendUrlPreferenceKey, discovered);
  }
  return discovered;
}

Future<String?> _resolveApiBaseUrlFromResolver(SharedPreferences prefs, String seedBackendUrl) async {
  final cachedUrl = prefs.getString(_resolverBackendUrlPreferenceKey)?.trim();
  final fetchedAtRaw = prefs.getString(_resolverBackendFetchedAtPreferenceKey)?.trim();
  final fetchedAt = fetchedAtRaw == null || fetchedAtRaw.isEmpty ? null : DateTime.tryParse(fetchedAtRaw);
  if (cachedUrl != null &&
      cachedUrl.isNotEmpty &&
      fetchedAt != null &&
      DateTime.now().toUtc().difference(fetchedAt.toUtc()) <= _resolverCacheTtl) {
    return _normalizeBackendUrl(cachedUrl);
  }

  try {
    final response = await http
        .get(Uri.parse('${_normalizeBackendUrl(seedBackendUrl)}/api/config'))
        .timeout(const Duration(seconds: 4));
    if (response.statusCode != 200) {
      return cachedUrl == null || cachedUrl.isEmpty ? null : _normalizeBackendUrl(cachedUrl);
    }
    final payload = jsonDecode(response.body) as Map<String, dynamic>;
    final apiBaseUrl = _normalizeBackendUrl('${payload['backend_url'] ?? payload['backendUrl'] ?? payload['apiBaseUrl'] ?? ''}');
    if (apiBaseUrl.isEmpty) {
      return cachedUrl == null || cachedUrl.isEmpty ? null : _normalizeBackendUrl(cachedUrl);
    }
    await prefs.setString(_resolverBackendUrlPreferenceKey, apiBaseUrl);
    await prefs.setString(_resolverBackendFetchedAtPreferenceKey, DateTime.now().toUtc().toIso8601String());
    return apiBaseUrl;
  } on TimeoutException {
    return cachedUrl == null || cachedUrl.isEmpty ? null : _normalizeBackendUrl(cachedUrl);
  } on SocketException {
    return cachedUrl == null || cachedUrl.isEmpty ? null : _normalizeBackendUrl(cachedUrl);
  } on HttpException {
    return cachedUrl == null || cachedUrl.isEmpty ? null : _normalizeBackendUrl(cachedUrl);
  } catch (_) {
    return cachedUrl == null || cachedUrl.isEmpty ? null : _normalizeBackendUrl(cachedUrl);
  }
}

Future<String?> _scanLocalNetworkForBackend() async {
  final candidates = <String>[
    for (final prefix in _networkPrefixes)
      for (var host = 1; host <= 255; host += 1) 'http://$prefix.$host:$_backendPort',
  ];

  const batchSize = 20;
  for (var index = 0; index < candidates.length; index += batchSize) {
    final batch = candidates.skip(index).take(batchSize).toList();
    final result = await _scanBatch(batch);
    if (result != null) {
      return result;
    }
  }

  return null;
}

Future<String?> _scanBatch(List<String> batch) async {
  final completer = Completer<String?>();
  var completed = 0;

  for (final candidate in batch) {
    _isHealthyBackend(candidate).then((isHealthy) {
      if (completer.isCompleted) {
        return;
      }

      if (isHealthy) {
        completer.complete(_normalizeBackendUrl(candidate));
        return;
      }

      completed += 1;
      if (completed >= batch.length) {
        completer.complete(null);
      }
    });
  }

  return completer.future.timeout(
    const Duration(milliseconds: 1200),
    onTimeout: () => null,
  );
}

Future<bool> _isHealthyBackend(String backendUrl) async {
  try {
    final response = await http
        .get(Uri.parse('${_normalizeBackendUrl(backendUrl)}/streams/leagues'))
        .timeout(const Duration(milliseconds: 350));
    return response.statusCode == 200;
  } on TimeoutException {
    return false;
  } on SocketException {
    return false;
  } on HttpException {
    return false;
  } catch (_) {
    return false;
  }
}

String _normalizeBackendUrl(String url) {
  return (url.trim().isEmpty ? _defaultApiUrl : url.trim()).replaceFirst(RegExp(r'/+$'), '');
}
