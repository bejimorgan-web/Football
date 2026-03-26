import 'network_config.dart';

class ApiConfig {
  static String get baseUrl => NetworkConfig.baseUrl;

  static String normalize(String value) {
    var normalized = value.trim().replaceFirst(RegExp(r'^https//'), 'https://');
    normalized = normalized.replaceFirst(RegExp(r'^http//'), 'http://');
    return normalized.replaceFirst(RegExp(r'/+$'), '');
  }

  static Uri uri(String backendUrl, String path, [Map<String, String>? queryParameters]) {
    final normalizedBase = normalize(backendUrl.isEmpty ? baseUrl : backendUrl);
    final normalizedPath = path.startsWith('/') ? path : '/$path';
    return Uri.parse('$normalizedBase$normalizedPath').replace(queryParameters: queryParameters);
  }

  static String version() => '${normalize(baseUrl)}/api/version';
  static String streams() => '${normalize(baseUrl)}/streams';
  static String analytics() => '${normalize(baseUrl)}/analytics';
  static String config() => '${normalize(baseUrl)}/config';
}
