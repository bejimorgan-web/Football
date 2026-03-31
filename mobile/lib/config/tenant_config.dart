import 'api_config.dart';
import 'network_config.dart';

const String singleTenantId = 'default';
String get embeddedTenantBackendUrl => NetworkConfig.baseUrl;

String backendUrl = '';
String backendApiUrl = '';
String backendApiToken = '';
String publicApiUrl = '';
String publicApiToken = '';
String activeBackendUrl = '';
String activeApiToken = '';

String resolveUrl(String path, {String? baseUrl}) {
  final normalizedPath = path.trim();
  if (normalizedPath.isEmpty) {
    return '';
  }
  final normalizedBaseUrl = ApiConfig.normalize((baseUrl ?? activeBackendUrl ?? backendUrl).trim());
  if (normalizedPath.startsWith('http')) {
    if (normalizedBaseUrl.isEmpty) {
      return normalizedPath;
    }
    final source = Uri.tryParse(normalizedPath);
    final target = Uri.tryParse(normalizedBaseUrl);
    final sourceHost = (source?.host ?? '').trim().toLowerCase();
    final isLocalOnlyHost = sourceHost == 'localhost' || sourceHost == '127.0.0.1' || sourceHost == '0.0.0.0';
    if (source != null && target != null && isLocalOnlyHost) {
      return source.replace(
        scheme: target.scheme,
        host: target.host,
        port: target.hasPort ? target.port : null,
      ).toString();
    }
    return normalizedPath;
  }
  if (normalizedBaseUrl.isEmpty) {
    return normalizedPath;
  }
  return normalizedPath.startsWith('/')
      ? '$normalizedBaseUrl$normalizedPath'
      : '$normalizedBaseUrl/$normalizedPath';
}
