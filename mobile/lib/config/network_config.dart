const String _defaultBackendUrl = String.fromEnvironment(
  'API_BASE_URL',
  defaultValue: '',
);

class NetworkConfig {
  static String get baseUrl => _defaultBackendUrl.trim();
}
