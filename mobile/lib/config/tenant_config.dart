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
  if (normalizedPath.startsWith('http')) {
    return normalizedPath;
  }
  final normalizedBaseUrl = ApiConfig.normalize((baseUrl ?? activeBackendUrl ?? backendUrl).trim());
  if (normalizedBaseUrl.isEmpty) {
    return normalizedPath;
  }
  return normalizedPath.startsWith('/')
      ? '$normalizedBaseUrl$normalizedPath'
      : '$normalizedBaseUrl/$normalizedPath';
}
