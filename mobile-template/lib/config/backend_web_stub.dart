import 'app_config.dart';

Future<String> resolveBackendUrl() async => embeddedServerUrl;

Future<String?> getManualBackendUrl() async => null;

Future<void> setManualBackendUrl(String url) async {}

Future<void> clearManualBackendUrl() async {}
