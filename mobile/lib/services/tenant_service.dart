import 'dart:convert';

import 'package:http/http.dart' as http;

import '../config/api_config.dart';
import '../config/tenant_config.dart';

Future<void> loadTenantConfig() async {
  final normalizedTenantId = tenantId.trim();
  if (normalizedTenantId.isEmpty) {
    throw Exception('Tenant ID is not configured.');
  }

  final response = await http.get(
    Uri.parse('$discoveryServer/tenant/$normalizedTenantId'),
  ).timeout(const Duration(seconds: 5));

  if (response.statusCode != 200) {
    throw Exception('Tenant discovery failed (${response.statusCode}).');
  }

  final config = jsonDecode(response.body) as Map<String, dynamic>;
  final discoveredBackend = '${config['backend'] ?? config['backend_url'] ?? ''}'.trim();
  if (discoveredBackend.isEmpty) {
    throw Exception('Tenant discovery did not return a backend URL.');
  }

  backendUrl = ApiConfig.normalize(discoveredBackend);
}
