import 'dart:async';
import 'dart:convert';
import 'dart:math';

import 'package:device_info_plus/device_info_plus.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:http/http.dart' as http;
import 'package:shared_preferences/shared_preferences.dart';
import 'package:video_player/video_player.dart';

import 'config/app_config.dart';
import 'config/backend.dart';
import 'security/security_service.dart';

const String _deviceIdKey = 'device_id';
const String _deviceNameKey = 'device_name';
const String _devicePlatformKey = 'device_platform';
const String _tenantIdKey = 'tenant_id';
const String _mobileConfigCacheKey = 'mobile_config_cache';
const String _mobileConfigFetchedAtKey = 'mobile_config_fetched_at';
const Duration _mobileConfigRefreshInterval = Duration(hours: 12);
const String _appVersion = embeddedAppVersion;

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  runApp(const FootballStreamingApp());
}

class FootballStreamingApp extends StatefulWidget {
  const FootballStreamingApp({super.key});

  @override
  State<FootballStreamingApp> createState() => _FootballStreamingAppState();
}

class _FootballStreamingAppState extends State<FootballStreamingApp> {
  TenantBranding _branding = TenantBranding.fallback();

  void _updateBranding(TenantBranding branding) {
    if (!mounted) return;
    setState(() => _branding = branding);
  }

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: _branding.appName,
      debugShowCheckedModeBanner: false,
      navigatorKey: navigatorKey,
      theme: ThemeData(
        useMaterial3: true,
        scaffoldBackgroundColor: _branding.backgroundColor,
        colorScheme: ColorScheme.fromSeed(
          seedColor: _branding.primaryColor,
          brightness: Brightness.dark,
          surface: _branding.surfaceColor,
        ),
        textTheme: ThemeData.dark().textTheme.apply(
          bodyColor: _branding.textColor,
          displayColor: _branding.textColor,
        ),
      ),
      home: AppBootstrapPage(onBrandingChanged: _updateBranding),
    );
  }
}

class TenantBranding {
  const TenantBranding({
    required this.tenantId,
    required this.appName,
    required this.logoUrl,
    required this.primaryColor,
    required this.accentColor,
    required this.surfaceColor,
    required this.backgroundColor,
    required this.textColor,
    required this.apiBaseUrl,
    required this.mobileApiToken,
    required this.serverId,
  });

  final String tenantId;
  final String appName;
  final String logoUrl;
  final Color primaryColor;
  final Color accentColor;
  final Color surfaceColor;
  final Color backgroundColor;
  final Color textColor;
  final String apiBaseUrl;
  final String mobileApiToken;
  final String serverId;

  factory TenantBranding.fallback() => TenantBranding(
        tenantId: embeddedTenantId,
        appName: embeddedAppName,
        logoUrl: embeddedLogoPath == 'LOGO_PATH' ? '' : embeddedLogoPath,
        primaryColor: _parseHexColor(embeddedPrimaryColor, const Color(0xFF11B37C)),
        accentColor: _parseHexColor(embeddedSecondaryColor, const Color(0xFF7EE3AF)),
        surfaceColor: const Color(0xFF0D1E2B),
        backgroundColor: const Color(0xFF07141E),
        textColor: const Color(0xFFF2F8FF),
        apiBaseUrl: embeddedServerUrl,
        mobileApiToken: '',
        serverId: '',
      );

  factory TenantBranding.fromJson(Map<String, dynamic> json) {
    final branding = json['branding'] as Map<String, dynamic>? ?? const {};
    final mobileAuth = json['mobile_auth'] as Map<String, dynamic>? ?? const {};
    return TenantBranding(
      tenantId: '${json['tenant_id'] ?? embeddedTenantId}',
      appName: '${json['app_name'] ?? branding['app_name'] ?? json['name'] ?? embeddedAppName}',
      logoUrl: '${json['logo_url'] ?? branding['logo_url'] ?? branding['logo_file'] ?? (embeddedLogoPath == 'LOGO_PATH' ? '' : embeddedLogoPath)}',
      primaryColor: _parseHexColor('${json['theme_color'] ?? branding['primary_color'] ?? embeddedPrimaryColor}', const Color(0xFF11B37C)),
      accentColor: _parseHexColor('${json['secondary_color'] ?? branding['secondary_color'] ?? branding['accent_color'] ?? embeddedSecondaryColor}', const Color(0xFF7EE3AF)),
      surfaceColor: _parseHexColor('${branding['surface_color'] ?? '#0D1E2B'}', const Color(0xFF0D1E2B)),
      backgroundColor: _parseHexColor('${branding['background_color'] ?? '#07141E'}', const Color(0xFF07141E)),
      textColor: _parseHexColor('${branding['text_color'] ?? '#F2F8FF'}', const Color(0xFFF2F8FF)),
      apiBaseUrl: '${json['server_url'] ?? json['backend_url'] ?? branding['server_url'] ?? branding['api_base_url'] ?? embeddedServerUrl}',
      mobileApiToken: '${mobileAuth['api_token'] ?? ''}',
      serverId: '${mobileAuth['server_id'] ?? ''}',
    );
  }
}

class DeviceIdentity {
  const DeviceIdentity({
    required this.deviceId,
    required this.deviceName,
    required this.platform,
  });

  final String deviceId;
  final String deviceName;
  final String platform;
}

class DeviceStatus {
  const DeviceStatus({
    required this.deviceId,
    required this.deviceName,
    required this.displayName,
    required this.status,
    required this.message,
    required this.isAllowed,
    required this.trialEnd,
    required this.subscriptionEnd,
    required this.freeAccess,
  });

  final String deviceId;
  final String deviceName;
  final String displayName;
  final String status;
  final String message;
  final bool isAllowed;
  final String trialEnd;
  final String subscriptionEnd;
  final bool freeAccess;

  factory DeviceStatus.fromJson(Map<String, dynamic> json) {
    return DeviceStatus(
      deviceId: '${json['device_id'] ?? ''}',
      deviceName: '${json['device_name'] ?? ''}',
      displayName: '${json['display_name'] ?? json['device_name'] ?? ''}',
      status: '${json['status'] ?? 'expired'}',
      message: '${json['message'] ?? ''}',
      isAllowed: json['is_allowed'] == true,
      trialEnd: '${json['trial_end'] ?? ''}',
      subscriptionEnd: '${json['subscription_end'] ?? ''}',
      freeAccess: json['free_access'] == true,
    );
  }
}

class NationCatalog {
  const NationCatalog({
    required this.id,
    required this.name,
    required this.logo,
    required this.competitions,
  });

  final String id;
  final String name;
  final String logo;
  final List<CompetitionCatalog> competitions;

  factory NationCatalog.fromJson(Map<String, dynamic> json) {
    return NationCatalog(
      id: '${json['id'] ?? ''}',
      name: '${json['name'] ?? 'Nation'}',
      logo: '${json['logo'] ?? ''}',
      competitions: (json['competitions'] as List<dynamic>? ?? <dynamic>[])
          .whereType<Map<String, dynamic>>()
          .map(CompetitionCatalog.fromJson)
          .toList(),
    );
  }
}

class CompetitionCatalog {
  const CompetitionCatalog({
    required this.id,
    required this.name,
    required this.type,
    required this.logo,
    required this.matches,
  });

  final String id;
  final String name;
  final String type;
  final String logo;
  final List<MatchItem> matches;

  factory CompetitionCatalog.fromJson(Map<String, dynamic> json) {
    return CompetitionCatalog(
      id: '${json['id'] ?? ''}',
      name: '${json['name'] ?? 'Competition'}',
      type: '${json['type'] ?? 'league'}',
      logo: '${json['logo'] ?? ''}',
      matches: (json['matches'] as List<dynamic>? ?? <dynamic>[])
          .whereType<Map<String, dynamic>>()
          .map(MatchItem.fromJson)
          .toList(),
    );
  }
}

class MatchItem {
  const MatchItem({
    required this.streamId,
    required this.matchLabel,
    required this.streamUrl,
    required this.kickoffLabel,
    required this.competitionName,
    required this.competitionLogo,
    required this.homeTeamName,
    required this.homeTeamLogo,
    required this.awayTeamName,
    required this.awayTeamLogo,
  });

  final String streamId;
  final String matchLabel;
  final String streamUrl;
  final String kickoffLabel;
  final String competitionName;
  final String competitionLogo;
  final String homeTeamName;
  final String homeTeamLogo;
  final String awayTeamName;
  final String awayTeamLogo;

  factory MatchItem.fromJson(Map<String, dynamic> json) {
    final homeClub = json['home_club'] as Map<String, dynamic>? ?? const {};
    final awayClub = json['away_club'] as Map<String, dynamic>? ?? const {};
    return MatchItem(
      streamId: '${json['stream_id'] ?? ''}',
      matchLabel: '${json['match_label'] ?? 'Match'}',
      streamUrl: '${json['stream_url'] ?? json['url'] ?? ''}',
      kickoffLabel: '${json['kickoff_label'] ?? ''}',
      competitionName: '${json['competition_name'] ?? ''}',
      competitionLogo: '${json['competition_logo'] ?? ''}',
      homeTeamName: '${json['home_team_name'] ?? homeClub['name'] ?? 'Home'}',
      homeTeamLogo: '${json['home_team_logo'] ?? homeClub['logo'] ?? ''}',
      awayTeamName: '${json['away_team_name'] ?? awayClub['name'] ?? 'Away'}',
      awayTeamLogo: '${json['away_team_logo'] ?? awayClub['logo'] ?? ''}',
    );
  }
}

class AppSession {
  const AppSession({
    required this.backendUrl,
    required this.tenantId,
    required this.branding,
    required this.identity,
    required this.security,
    required this.status,
    required this.catalog,
  });

  final String backendUrl;
  final String tenantId;
  final TenantBranding branding;
  final DeviceIdentity identity;
  final SecuritySnapshot security;
  final DeviceStatus status;
  final List<NationCatalog> catalog;
}

class MobileApi {
  const MobileApi();

  Future<String> ensureTenantId() async {
    final prefs = await SharedPreferences.getInstance();
    final stored = prefs.getString(_tenantIdKey)?.trim();
    if (stored != null && stored.isNotEmpty) {
      return stored;
    }
    await prefs.setString(_tenantIdKey, embeddedTenantId);
    return embeddedTenantId;
  }

  Future<void> saveTenantId(String tenantId) async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString(_tenantIdKey, tenantId.trim().isEmpty ? embeddedTenantId : tenantId.trim());
  }

  Future<TenantBranding> fetchBranding(String backendUrl, String tenantId) async {
    final prefs = await SharedPreferences.getInstance();
    Future<TenantBranding> loadLegacyBranding() async {
      final legacyUri = Uri.parse('$backendUrl/config/branding').replace(queryParameters: {
        'tenant_id': tenantId,
      });
      final legacyResponse = await http.get(legacyUri);
      if (legacyResponse.statusCode != 200) {
        throw Exception(_extractDetail(legacyResponse.body, legacyResponse.statusCode));
      }
      final legacyPayload = jsonDecode(legacyResponse.body) as Map<String, dynamic>;
      await prefs.setString(_mobileConfigCacheKey, jsonEncode(legacyPayload));
      await prefs.setString(_mobileConfigFetchedAtKey, DateTime.now().toUtc().toIso8601String());
      return TenantBranding.fromJson(legacyPayload);
    }
    try {
      final runtimeUri = Uri.parse('$backendUrl/mobile/config/$tenantId');
      final runtimeResponse = await http.get(runtimeUri);
      if (runtimeResponse.statusCode == 200) {
        final runtimePayload = jsonDecode(runtimeResponse.body) as Map<String, dynamic>;
        await prefs.setString(_mobileConfigCacheKey, jsonEncode(runtimePayload));
        await prefs.setString(_mobileConfigFetchedAtKey, DateTime.now().toUtc().toIso8601String());
        return TenantBranding.fromJson(runtimePayload);
      }
      final uri = Uri.parse('$backendUrl/tenant/mobile-config').replace(queryParameters: {
        'tenant_id': tenantId,
      });
      final response = await http.get(uri);
      if (response.statusCode == 404) {
        return loadLegacyBranding();
      }
      if (response.statusCode != 200) {
        throw Exception(_extractDetail(response.body, response.statusCode));
      }
      final payload = jsonDecode(response.body) as Map<String, dynamic>;
      await prefs.setString(_mobileConfigCacheKey, jsonEncode(payload));
      await prefs.setString(_mobileConfigFetchedAtKey, DateTime.now().toUtc().toIso8601String());
      return TenantBranding.fromJson(payload);
    } catch (error) {
      final cached = prefs.getString(_mobileConfigCacheKey);
      if (cached != null && cached.isNotEmpty) {
        return TenantBranding.fromJson(jsonDecode(cached) as Map<String, dynamic>);
      }
      rethrow;
    }
  }

  Future<DeviceIdentity> ensureIdentity() async {
    final prefs = await SharedPreferences.getInstance();
    final storedId = prefs.getString(_deviceIdKey);
    final storedName = prefs.getString(_deviceNameKey);
    final storedPlatform = prefs.getString(_devicePlatformKey);
    if (storedId != null && storedName != null && storedPlatform != null) {
      return DeviceIdentity(
        deviceId: storedId,
        deviceName: storedName,
        platform: storedPlatform,
      );
    }

    final info = DeviceInfoPlugin();
    String deviceName = 'Mobile Device';
    String platform = defaultTargetPlatform.name;
    try {
      final android = await info.androidInfo;
      deviceName = '${android.manufacturer} ${android.model}'.trim();
      platform = 'android';
    } catch (_) {
      try {
        final ios = await info.iosInfo;
        deviceName = ios.utsname.machine?.trim().isNotEmpty == true ? ios.utsname.machine! : (ios.model ?? 'iPhone');
        platform = 'ios';
      } catch (_) {
        try {
          final windows = await info.windowsInfo;
          deviceName = windows.computerName;
          platform = 'windows';
        } catch (_) {
          platform = 'device';
        }
      }
    }

    final identity = DeviceIdentity(
      deviceId: _generateDeviceId(),
      deviceName: deviceName.trim().isEmpty ? 'Mobile Device' : deviceName.trim(),
      platform: platform,
    );
    await prefs.setString(_deviceIdKey, identity.deviceId);
    await prefs.setString(_deviceNameKey, identity.deviceName);
    await prefs.setString(_devicePlatformKey, identity.platform);
    return identity;
  }

  Future<void> registerDevice(
    String backendUrl,
    String tenantId,
    DeviceIdentity identity,
    SecuritySnapshot security,
    TenantBranding branding,
  ) async {
    final response = await http.post(
      Uri.parse('$backendUrl/device/register'),
      headers: _mobileHeaders(branding, tenantId, identity.deviceId),
      body: jsonEncode({
        'device_id': identity.deviceId,
        'tenant_id': tenantId,
        'device_name': identity.deviceName,
        'platform': identity.platform,
        'app_version': _appVersion,
        'device_fingerprint': security.deviceFingerprint,
        'country': security.preferredCountry,
        'vpn_active': security.vpnActive,
        'secure_device': security.secureDevice,
        'app_signature_valid': security.appSignatureValid,
      }),
    );
    if (response.statusCode >= 400) {
      throw Exception('Device registration failed with ${response.statusCode}.');
    }
  }

  Future<DeviceStatus> fetchStatus(
    String backendUrl,
    String tenantId,
    String deviceId,
    SecuritySnapshot security,
    TenantBranding branding,
  ) async {
    final uri = Uri.parse('$backendUrl/device/status').replace(queryParameters: {
      'tenant_id': tenantId,
      'device_id': deviceId,
      'country': security.preferredCountry,
      'device_fingerprint': security.deviceFingerprint,
      'vpn_active': '${security.vpnActive}',
      'secure_device': '${security.secureDevice}',
      'app_signature_valid': '${security.appSignatureValid}',
    });
    final response = await http.get(uri, headers: _mobileHeaders(branding, tenantId, deviceId));
    if (response.statusCode != 200) {
      throw Exception(_extractDetail(response.body, response.statusCode));
    }
    final payload = jsonDecode(response.body) as Map<String, dynamic>;
    return DeviceStatus.fromJson(payload['item'] as Map<String, dynamic>? ?? const {});
  }

  Future<List<NationCatalog>> fetchCatalog(String backendUrl, String tenantId, String deviceId, TenantBranding branding) async {
    final response = await http.get(
      Uri.parse('$backendUrl/streams/catalog?tenant_id=$tenantId&device_id=$deviceId&server_id=${Uri.encodeQueryComponent(branding.serverId)}'),
      headers: _mobileHeaders(branding, tenantId, deviceId),
    );
    if (response.statusCode != 200) {
      throw Exception(_extractDetail(response.body, response.statusCode));
    }
    final payload = jsonDecode(response.body) as Map<String, dynamic>;
    return (payload['items'] as List<dynamic>? ?? <dynamic>[])
        .whereType<Map<String, dynamic>>()
        .map(NationCatalog.fromJson)
        .where((nation) => nation.competitions.isNotEmpty)
        .toList();
  }

  Future<String> fetchStreamTokenUrl({
    required String backendUrl,
    required String tenantId,
    required String deviceId,
    required String streamId,
    required SecuritySnapshot security,
    required TenantBranding branding,
  }) async {
    final uri = Uri.parse('$backendUrl/streams/token/$streamId').replace(queryParameters: {
      'tenant_id': tenantId,
      'device_id': deviceId,
      'server_id': branding.serverId,
      'country': security.preferredCountry,
      'device_fingerprint': security.deviceFingerprint,
      'vpn_active': '${security.vpnActive}',
      'secure_device': '${security.secureDevice}',
      'app_signature_valid': '${security.appSignatureValid}',
    });
    final response = await http.get(uri, headers: _mobileHeaders(branding, tenantId, deviceId));
    if (response.statusCode != 200) {
      throw Exception(_extractDetail(response.body, response.statusCode));
    }
    final payload = jsonDecode(response.body) as Map<String, dynamic>;
    final relative = '${payload['stream_url'] ?? ''}';
    if (relative.isEmpty) {
      throw Exception('Tokenized stream URL missing.');
    }
    return relative.startsWith('http') ? relative : '$backendUrl$relative';
  }

  Future<void> startViewer({
    required String backendUrl,
    required String tenantId,
    required DeviceIdentity identity,
    required MatchItem match,
    required TenantBranding branding,
    String country = '',
  }) async {
    final response = await http.post(
      Uri.parse('$backendUrl/viewer/start'),
      headers: _mobileHeaders(branding, tenantId, identity.deviceId),
      body: jsonEncode({
        'device_id': identity.deviceId,
        'tenant_id': tenantId,
        'server_id': branding.serverId,
        'stream_id': match.streamId,
        'competition': match.competitionName,
        'home_club': match.homeTeamName,
        'away_club': match.awayTeamName,
        'timestamp': DateTime.now().toUtc().toIso8601String(),
        'country': country,
      }),
    );
    if (response.statusCode >= 400) {
      throw Exception(_extractDetail(response.body, response.statusCode));
    }
  }

  Future<void> stopViewer({
    required String backendUrl,
    required String tenantId,
    required DeviceIdentity identity,
    required String streamId,
    required TenantBranding branding,
  }) async {
    final response = await http.post(
      Uri.parse('$backendUrl/viewer/stop'),
      headers: _mobileHeaders(branding, tenantId, identity.deviceId),
      body: jsonEncode({
        'device_id': identity.deviceId,
        'tenant_id': tenantId,
        'server_id': branding.serverId,
        'stream_id': streamId,
        'timestamp': DateTime.now().toUtc().toIso8601String(),
      }),
    );
    if (response.statusCode >= 400) {
      throw Exception(_extractDetail(response.body, response.statusCode));
    }
  }

  String _extractDetail(String body, int statusCode) {
    try {
      final json = jsonDecode(body);
      if (json is Map<String, dynamic> && json['detail'] != null) {
        return '${json['detail']}';
      }
    } catch (_) {}
    return 'Backend request failed with $statusCode.';
  }

  String _generateDeviceId() {
    final random = Random.secure();
    final left = DateTime.now().millisecondsSinceEpoch.toRadixString(16);
    final right = random.nextInt(1 << 32).toRadixString(16);
    return 'device-$left-$right';
  }

  Map<String, String> _mobileHeaders(TenantBranding branding, String tenantId, String deviceId) {
    return {
      'Content-Type': 'application/json',
      'X-Api-Token': branding.mobileApiToken,
      'X-Tenant-Id': tenantId,
      'X-Device-Id': deviceId,
      'X-Server-Id': branding.serverId,
    };
  }
}

final GlobalKey<NavigatorState> navigatorKey = GlobalKey<NavigatorState>();

class AppBootstrapPage extends StatefulWidget {
  const AppBootstrapPage({super.key, required this.onBrandingChanged});

  final ValueChanged<TenantBranding> onBrandingChanged;

  @override
  State<AppBootstrapPage> createState() => _AppBootstrapPageState();
}

class _AppBootstrapPageState extends State<AppBootstrapPage> {
  final MobileApi _api = const MobileApi();
  late Future<AppSession> _sessionFuture;
  Timer? _brandingRefreshTimer;

  @override
  void initState() {
    super.initState();
    _sessionFuture = _loadSession();
    _brandingRefreshTimer = Timer.periodic(_mobileConfigRefreshInterval, (_) {
      if (!mounted) return;
      _refresh().catchError((_) {});
    });
  }

  @override
  void dispose() {
    _brandingRefreshTimer?.cancel();
    super.dispose();
  }

  Future<AppSession> _loadSession() async {
    final initialBackendUrl = await resolveBackendUrl();
    final tenantId = await _api.ensureTenantId();
    final branding = await _api.fetchBranding(initialBackendUrl, tenantId);
    widget.onBrandingChanged(branding);
    final backendUrl = branding.apiBaseUrl.isNotEmpty ? branding.apiBaseUrl : initialBackendUrl;
    final identity = await _api.ensureIdentity();
    final security = await SecurityService.getSecuritySnapshot();
    if (!security.appSignatureValid) {
      throw Exception('App signature verification failed. API requests were blocked.');
    }
    await _api.registerDevice(backendUrl, tenantId, identity, security, branding);
    final status = await _api.fetchStatus(backendUrl, tenantId, identity.deviceId, security, branding);
    final catalog = status.isAllowed ? await _api.fetchCatalog(backendUrl, tenantId, identity.deviceId, branding) : <NationCatalog>[];
    return AppSession(
      backendUrl: backendUrl,
      tenantId: tenantId,
      branding: branding,
      identity: identity,
      security: security,
      status: status,
      catalog: catalog,
    );
  }

  Future<void> _refresh() async {
    setState(() {
      _sessionFuture = _loadSession();
    });
    await _sessionFuture;
  }

  Future<void> _openBackendSettings() async {
    final currentManualOverride = await getManualBackendUrl() ?? '';
    final currentTenantId = await _api.ensureTenantId();
    if (!mounted) return;
    final controller = TextEditingController(text: currentManualOverride);
    final tenantController = TextEditingController(text: currentTenantId);
    final result = await showDialog<_BackendSettingsResult>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('Backend Settings'),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            TextField(
              controller: controller,
              decoration: const InputDecoration(
                labelText: 'Custom backend URL',
                hintText: 'http://192.168.1.25:8000',
                helperText: 'Leave blank to use automatic discovery.',
              ),
              keyboardType: TextInputType.url,
              autofocus: true,
            ),
            const SizedBox(height: 12),
            TextField(
              controller: tenantController,
              decoration: const InputDecoration(
                labelText: 'Tenant ID',
                hintText: 'default',
                helperText: 'Used for branding and subscription rules.',
              ),
            ),
          ],
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(context).pop(const _BackendSettingsResult.cancel()),
            child: const Text('Cancel'),
          ),
          TextButton(
            onPressed: () => Navigator.of(context).pop(const _BackendSettingsResult.clear()),
            child: const Text('Use Auto'),
          ),
          FilledButton(
            onPressed: () => Navigator.of(context).pop(_BackendSettingsResult.save('${controller.text.trim()}|${tenantController.text.trim()}')),
            child: const Text('Save'),
          ),
        ],
      ),
    );

    if (!mounted || result == null || result.action == _BackendSettingsAction.cancel) return;
    if (result.action == _BackendSettingsAction.clear || result.value.isEmpty) {
      await clearManualBackendUrl();
    } else {
      final parts = result.value.split('|');
      await setManualBackendUrl(parts.first);
      await _api.saveTenantId(parts.length > 1 ? parts[1] : 'default');
    }
    if (!mounted) return;
    await _refresh();
  }

  @override
  Widget build(BuildContext context) {
    return FutureBuilder<AppSession>(
      future: _sessionFuture,
      builder: (context, snapshot) {
        if (snapshot.connectionState == ConnectionState.waiting) {
          return const Scaffold(
            body: Center(child: CircularProgressIndicator()),
          );
        }

        if (snapshot.hasError) {
          return _InfoScreen(
            icon: Icons.cloud_off,
            title: 'Could not connect to the football backend',
            subtitle: '${snapshot.error}',
            actionLabel: 'Try Again',
            onPressed: _refresh,
            secondaryLabel: 'Backend Settings',
            onSecondaryPressed: _openBackendSettings,
          );
        }

        final session = snapshot.data!;
        if (session.status.status == 'blocked' || session.status.status == 'device_blocked' || session.status.status == 'vpn_blocked' || session.status.status == 'insecure_device') {
          return BlockedAccessPage(
            backendUrl: session.backendUrl,
            branding: session.branding,
            status: session.status,
            onRefresh: _refresh,
            onBackendSettings: _openBackendSettings,
          );
        }
        if (!session.status.isAllowed) {
          return SubscriptionPage(
            backendUrl: session.backendUrl,
            branding: session.branding,
            status: session.status,
            onRefresh: _refresh,
            onBackendSettings: _openBackendSettings,
          );
        }
        return MatchCatalogPage(
          session: session,
          onRefresh: _refresh,
          onBackendSettings: _openBackendSettings,
        );
      },
    );
  }
}

class MatchCatalogPage extends StatelessWidget {
  const MatchCatalogPage({
    super.key,
    required this.session,
    required this.onRefresh,
    required this.onBackendSettings,
  });

  final AppSession session;
  final Future<void> Function() onRefresh;
  final Future<void> Function() onBackendSettings;

  @override
  Widget build(BuildContext context) {
    final nations = session.catalog;
    return Scaffold(
      body: SafeArea(
        child: RefreshIndicator(
          onRefresh: onRefresh,
          child: ListView(
            padding: const EdgeInsets.fromLTRB(16, 16, 16, 28),
            children: [
              _HeroHeader(
                backendUrl: session.backendUrl,
                branding: session.branding,
                status: session.status,
                onRefresh: onRefresh,
                onSettings: onBackendSettings,
              ),
              const SizedBox(height: 18),
              if (nations.isEmpty)
                _InfoPanel(
                  icon: Icons.sports_soccer,
                  title: 'No approved matches yet',
                  subtitle: 'Open the desktop admin app and approve streams in the Stream Approval panel.',
                ),
              for (final nation in nations) ...[
                _NationSection(backendUrl: session.backendUrl, nation: nation),
                const SizedBox(height: 18),
                for (final competition in nation.competitions) ...[
                  _CompetitionSection(
                    backendUrl: session.backendUrl,
                    competition: competition,
                    onOpenMatch: (match) {
                      Navigator.of(context).push(
                        MaterialPageRoute<void>(
                          builder: (_) => PlayerPage(
                            backendUrl: session.backendUrl,
                            tenantId: session.tenantId,
                            branding: session.branding,
                            identity: session.identity,
                            security: session.security,
                            status: session.status,
                            competition: competition,
                            match: match,
                          ),
                        ),
                      );
                    },
                  ),
                  const SizedBox(height: 18),
                ],
              ],
            ],
          ),
        ),
      ),
    );
  }
}

class BlockedAccessPage extends StatelessWidget {
  const BlockedAccessPage({
    super.key,
    required this.backendUrl,
    required this.branding,
    required this.status,
    required this.onRefresh,
    required this.onBackendSettings,
  });

  final String backendUrl;
  final TenantBranding branding;
  final DeviceStatus status;
  final Future<void> Function() onRefresh;
  final Future<void> Function() onBackendSettings;

  @override
  Widget build(BuildContext context) {
    return _InfoScreen(
      icon: Icons.block,
      title: '${branding.appName} access disabled',
      subtitle: '${status.message}\n\nDevice: ${status.deviceName}\nBackend: $backendUrl',
      actionLabel: 'Refresh Status',
      onPressed: onRefresh,
      secondaryLabel: 'Backend Settings',
      onSecondaryPressed: onBackendSettings,
    );
  }
}

class SubscriptionPage extends StatelessWidget {
  const SubscriptionPage({
    super.key,
    required this.backendUrl,
    required this.branding,
    required this.status,
    required this.onRefresh,
    required this.onBackendSettings,
  });

  final String backendUrl;
  final TenantBranding branding;
  final DeviceStatus status;
  final Future<void> Function() onRefresh;
  final Future<void> Function() onBackendSettings;

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: Container(
        decoration: const BoxDecoration(
          gradient: LinearGradient(
            colors: [Color(0xFF07141E), Color(0xFF0C2030), Color(0xFF0E3A46)],
            begin: Alignment.topLeft,
            end: Alignment.bottomRight,
          ),
        ),
        child: SafeArea(
          child: ListView(
            padding: const EdgeInsets.all(20),
            children: [
              const SizedBox(height: 16),
              Text(
                '${branding.appName} trial has ended',
                style: const TextStyle(fontSize: 30, fontWeight: FontWeight.w900),
              ),
              const SizedBox(height: 10),
              Text(
                '${status.message}\nDevice: ${status.deviceName}\nTrial end: ${_displayDate(status.trialEnd)}',
                style: const TextStyle(color: Color(0xFFB8CBDA), height: 1.5),
              ),
              const SizedBox(height: 24),
              const _SubscriptionCard(
                title: '6 Months',
                subtitle: 'Single-device access for one registered device.',
                accent: Color(0xFF13B87B),
              ),
              const SizedBox(height: 14),
              const _SubscriptionCard(
                title: '1 Year',
                subtitle: 'Best value for uninterrupted football streaming on one device.',
                accent: Color(0xFFF2B94B),
              ),
              const SizedBox(height: 18),
              Container(
                padding: const EdgeInsets.all(18),
                decoration: BoxDecoration(
                  color: Colors.white.withOpacity(0.06),
                  borderRadius: BorderRadius.circular(24),
                ),
                child: const Text(
                  'Subscriptions are activated by the admin panel. Once the admin extends this device, refresh the app and access will open automatically.',
                  style: TextStyle(color: Color(0xFFE7F3FF), height: 1.5),
                ),
              ),
              const SizedBox(height: 20),
              FilledButton(
                onPressed: onRefresh,
                child: const Text('Refresh Access'),
              ),
              const SizedBox(height: 10),
              OutlinedButton(
                onPressed: onBackendSettings,
                child: const Text('Backend Settings'),
              ),
              const SizedBox(height: 8),
              Text(
                'Backend: $backendUrl',
                textAlign: TextAlign.center,
                style: const TextStyle(color: Color(0xFF9CB2C4)),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _HeroHeader extends StatelessWidget {
  const _HeroHeader({
    required this.backendUrl,
    required this.branding,
    required this.status,
    required this.onRefresh,
    required this.onSettings,
  });

  final String backendUrl;
  final TenantBranding branding;
  final DeviceStatus status;
  final Future<void> Function() onRefresh;
  final Future<void> Function() onSettings;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(22),
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(30),
        gradient: const LinearGradient(
          colors: [Color(0xFF0D7A54), Color(0xFF123C68), Color(0xFF071D2A)],
          begin: Alignment.topLeft,
          end: Alignment.bottomRight,
        ),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Container(
                padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
                decoration: BoxDecoration(
                  color: Colors.white.withOpacity(0.12),
                  borderRadius: BorderRadius.circular(999),
                ),
                child: Text(
                  status.status.toUpperCase(),
                  style: const TextStyle(fontSize: 12, fontWeight: FontWeight.w800, letterSpacing: 1.1),
                ),
              ),
              const Spacer(),
              IconButton(
                onPressed: onSettings,
                icon: const Icon(Icons.settings_ethernet),
              ),
              IconButton(
                onPressed: onRefresh,
                icon: const Icon(Icons.refresh),
              ),
            ],
          ),
          const SizedBox(height: 18),
          Text(
            branding.appName,
            style: const TextStyle(fontSize: 31, fontWeight: FontWeight.w900, height: 1.1),
          ),
          const SizedBox(height: 8),
          Text(
            'Live competitions organized by nation, with club branding and direct stream launch.',
            style: TextStyle(color: Colors.white.withOpacity(0.82), height: 1.45),
          ),
          const SizedBox(height: 18),
          Wrap(
            spacing: 12,
            runSpacing: 12,
            children: [
              _Tag(label: status.displayName),
              _Tag(label: status.freeAccess ? 'Free Access' : 'Single Device'),
              _Tag(label: 'Trial ends ${_displayDate(status.trialEnd)}'),
            ],
          ),
          const SizedBox(height: 16),
          Text(
            backendUrl,
            style: TextStyle(color: Colors.white.withOpacity(0.74), fontSize: 12),
          ),
        ],
      ),
    );
  }
}

class _NationSection extends StatelessWidget {
  const _NationSection({
    required this.backendUrl,
    required this.nation,
  });

  final String backendUrl;
  final NationCatalog nation;

  @override
  Widget build(BuildContext context) {
    return Row(
      children: [
        _NetworkLogo(
          url: nation.logo,
          backendUrl: backendUrl,
          size: 48,
          fallbackIcon: Icons.flag,
        ),
        const SizedBox(width: 12),
        Expanded(
          child: Text(
            nation.name,
            style: const TextStyle(fontSize: 24, fontWeight: FontWeight.w800),
          ),
        ),
      ],
    );
  }
}

class _CompetitionSection extends StatelessWidget {
  const _CompetitionSection({
    required this.backendUrl,
    required this.competition,
    required this.onOpenMatch,
  });

  final String backendUrl;
  final CompetitionCatalog competition;
  final ValueChanged<MatchItem> onOpenMatch;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(18),
      decoration: BoxDecoration(
        color: const Color(0xFF0B1A25),
        borderRadius: BorderRadius.circular(28),
        border: Border.all(color: Colors.white.withOpacity(0.06)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              _NetworkLogo(
                url: competition.logo,
                backendUrl: backendUrl,
                size: 42,
                fallbackIcon: competition.type == 'cup' ? Icons.emoji_events : Icons.shield,
              ),
              const SizedBox(width: 12),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      competition.name,
                      style: const TextStyle(fontSize: 20, fontWeight: FontWeight.w800),
                    ),
                    Text(
                      competition.type == 'cup' ? 'Cup fixtures' : 'League fixtures',
                      style: const TextStyle(color: Color(0xFF95AFC3)),
                    ),
                  ],
                ),
              ),
            ],
          ),
          const SizedBox(height: 14),
          for (final match in competition.matches) ...[
            _MatchCard(
              backendUrl: backendUrl,
              match: match,
              onTap: () => onOpenMatch(match),
            ),
            const SizedBox(height: 12),
          ],
        ],
      ),
    );
  }
}

class _MatchCard extends StatelessWidget {
  const _MatchCard({
    required this.backendUrl,
    required this.match,
    required this.onTap,
  });

  final String backendUrl;
  final MatchItem match;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    return InkWell(
      onTap: onTap,
      borderRadius: BorderRadius.circular(24),
      child: Ink(
        padding: const EdgeInsets.all(16),
        decoration: BoxDecoration(
          borderRadius: BorderRadius.circular(24),
          gradient: const LinearGradient(
            colors: [Color(0xFF102432), Color(0xFF0D1821)],
            begin: Alignment.topLeft,
            end: Alignment.bottomRight,
          ),
        ),
        child: Column(
          children: [
            Row(
              children: [
                _NetworkLogo(
                  url: match.competitionLogo,
                  backendUrl: backendUrl,
                  size: 32,
                  fallbackIcon: Icons.emoji_events,
                ),
                const SizedBox(width: 8),
                Expanded(
                  child: Text(
                    match.competitionName,
                    style: const TextStyle(
                      color: Color(0xFFB8D6E8),
                      fontSize: 13,
                      fontWeight: FontWeight.w700,
                    ),
                  ),
                ),
                if (match.kickoffLabel.isNotEmpty)
                  Text(
                    match.kickoffLabel,
                    style: const TextStyle(
                      color: Color(0xFF7EE3AF),
                      fontSize: 12,
                      fontWeight: FontWeight.w700,
                    ),
                  ),
              ],
            ),
            const SizedBox(height: 16),
            Row(
              children: [
                Expanded(
                  child: _TeamBlock(
                    backendUrl: backendUrl,
                    teamName: match.homeTeamName,
                    teamLogo: match.homeTeamLogo,
                    alignEnd: false,
                  ),
                ),
                Container(
                  padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
                  decoration: BoxDecoration(
                    color: const Color(0xFF132837),
                    borderRadius: BorderRadius.circular(999),
                  ),
                  child: const Text(
                    'VS',
                    style: TextStyle(fontWeight: FontWeight.w900, color: Color(0xFF7BE1AE)),
                  ),
                ),
                Expanded(
                  child: _TeamBlock(
                    backendUrl: backendUrl,
                    teamName: match.awayTeamName,
                    teamLogo: match.awayTeamLogo,
                    alignEnd: true,
                  ),
                ),
              ],
            ),
          ],
        ),
      ),
    );
  }
}

class _TeamBlock extends StatelessWidget {
  const _TeamBlock({
    required this.backendUrl,
    required this.teamName,
    required this.teamLogo,
    required this.alignEnd,
  });

  final String backendUrl;
  final String teamName;
  final String teamLogo;
  final bool alignEnd;

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: alignEnd ? CrossAxisAlignment.end : CrossAxisAlignment.start,
      children: [
        _NetworkLogo(
          url: teamLogo,
          backendUrl: backendUrl,
          size: 60,
          fallbackIcon: Icons.shield_outlined,
        ),
        const SizedBox(height: 8),
        Text(
          teamName,
          textAlign: alignEnd ? TextAlign.end : TextAlign.start,
          style: const TextStyle(fontSize: 17, fontWeight: FontWeight.w700),
        ),
      ],
    );
  }
}

class _SubscriptionCard extends StatelessWidget {
  const _SubscriptionCard({
    required this.title,
    required this.subtitle,
    required this.accent,
  });

  final String title;
  final String subtitle;
  final Color accent;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(18),
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(26),
        gradient: LinearGradient(
          colors: [accent.withOpacity(0.28), const Color(0xFF10212E)],
          begin: Alignment.topLeft,
          end: Alignment.bottomRight,
        ),
        border: Border.all(color: accent.withOpacity(0.45)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(title, style: const TextStyle(fontSize: 22, fontWeight: FontWeight.w900)),
          const SizedBox(height: 8),
          Text(subtitle, style: const TextStyle(color: Color(0xFFCAE0EF), height: 1.5)),
        ],
      ),
    );
  }
}

class _Tag extends StatelessWidget {
  const _Tag({required this.label});

  final String label;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
      decoration: BoxDecoration(
        color: Colors.white.withOpacity(0.12),
        borderRadius: BorderRadius.circular(999),
      ),
      child: Text(label, style: const TextStyle(fontWeight: FontWeight.w600)),
    );
  }
}

class _NetworkLogo extends StatelessWidget {
  const _NetworkLogo({
    required this.url,
    required this.backendUrl,
    required this.size,
    required this.fallbackIcon,
  });

  final String url;
  final String backendUrl;
  final double size;
  final IconData fallbackIcon;

  @override
  Widget build(BuildContext context) {
    final resolvedUrl = url.startsWith('http') ? url : '$backendUrl$url';
    return Container(
      width: size,
      height: size,
      decoration: BoxDecoration(
        color: const Color(0xFF112737),
        borderRadius: BorderRadius.circular(size / 2),
      ),
      child: url.isEmpty
          ? Icon(fallbackIcon, color: const Color(0xFFB6D4E3))
          : ClipRRect(
              borderRadius: BorderRadius.circular(size / 2),
              child: resolvedUrl.startsWith('assets/')
                  ? Image.asset(
                      resolvedUrl,
                      fit: BoxFit.cover,
                      errorBuilder: (_, __, ___) => Icon(fallbackIcon, color: const Color(0xFFB6D4E3)),
                    )
                  : Image.network(
                      resolvedUrl,
                      fit: BoxFit.cover,
                      errorBuilder: (_, __, ___) => Icon(fallbackIcon, color: const Color(0xFFB6D4E3)),
                    ),
            ),
    );
  }
}

class _InfoPanel extends StatelessWidget {
  const _InfoPanel({
    required this.icon,
    required this.title,
    required this.subtitle,
  });

  final IconData icon;
  final String title;
  final String subtitle;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(20),
      decoration: BoxDecoration(
        color: Colors.white.withOpacity(0.05),
        borderRadius: BorderRadius.circular(26),
      ),
      child: Column(
        children: [
          Icon(icon, size: 44, color: const Color(0xFF7EE3AF)),
          const SizedBox(height: 10),
          Text(title, style: const TextStyle(fontSize: 20, fontWeight: FontWeight.w800)),
          const SizedBox(height: 8),
          Text(
            subtitle,
            textAlign: TextAlign.center,
            style: const TextStyle(color: Color(0xFF9FB6C8), height: 1.5),
          ),
        ],
      ),
    );
  }
}

class _InfoScreen extends StatelessWidget {
  const _InfoScreen({
    required this.icon,
    required this.title,
    required this.subtitle,
    required this.actionLabel,
    required this.onPressed,
    this.secondaryLabel,
    this.onSecondaryPressed,
  });

  final IconData icon;
  final String title;
  final String subtitle;
  final String actionLabel;
  final Future<void> Function() onPressed;
  final String? secondaryLabel;
  final Future<void> Function()? onSecondaryPressed;

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: Center(
        child: Padding(
          padding: const EdgeInsets.all(24),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              Icon(icon, size: 54, color: const Color(0xFF93D9B4)),
              const SizedBox(height: 14),
              Text(title, textAlign: TextAlign.center, style: const TextStyle(fontSize: 24, fontWeight: FontWeight.w800)),
              const SizedBox(height: 8),
              Text(subtitle, textAlign: TextAlign.center, style: const TextStyle(color: Color(0xFF9FB7C7), height: 1.5)),
              const SizedBox(height: 18),
              FilledButton(onPressed: onPressed, child: Text(actionLabel)),
              if (secondaryLabel != null && onSecondaryPressed != null) ...[
                const SizedBox(height: 10),
                OutlinedButton(onPressed: onSecondaryPressed, child: Text(secondaryLabel!)),
              ],
            ],
          ),
        ),
      ),
    );
  }
}

class PlayerPage extends StatefulWidget {
  const PlayerPage({
    super.key,
    required this.backendUrl,
    required this.tenantId,
    required this.branding,
    required this.identity,
    required this.security,
    required this.status,
    required this.competition,
    required this.match,
  });

  final String backendUrl;
  final String tenantId;
  final TenantBranding branding;
  final DeviceIdentity identity;
  final SecuritySnapshot security;
  final DeviceStatus status;
  final CompetitionCatalog competition;
  final MatchItem match;

  @override
  State<PlayerPage> createState() => _PlayerPageState();
}

class _PlayerPageState extends State<PlayerPage> {
  final MobileApi _api = const MobileApi();
  VideoPlayerController? _controller;
  Object? _error;
  bool _viewerStarted = false;
  Timer? _watermarkTimer;
  StreamSubscription<String>? _securityEvents;
  Alignment _watermarkAlignment = Alignment.topLeft;
  bool _captureWarningVisible = false;

  @override
  void initState() {
    super.initState();
    _initialize();
  }

  Future<void> _initialize() async {
    try {
      await SecurityService.enableSecurePlayback();
      _securityEvents = SecurityService.watchSecurityEvents().listen(_handleSecurityEvent);
      _shuffleWatermark();
      _watermarkTimer = Timer.periodic(const Duration(seconds: 30), (_) => _shuffleWatermark());
      final playbackUrl = await _api.fetchStreamTokenUrl(
        backendUrl: widget.backendUrl,
        tenantId: widget.tenantId,
        deviceId: widget.identity.deviceId,
        streamId: widget.match.streamId,
        security: widget.security,
        branding: widget.branding,
      );
      final controller = VideoPlayerController.networkUrl(Uri.parse(playbackUrl));
      await controller.initialize();
      await controller.play();
      await controller.setLooping(true);
      await _startViewerIfNeeded();
      if (!mounted) {
        await _stopViewerIfNeeded();
        await controller.dispose();
        return;
      }
      setState(() => _controller = controller);
    } catch (error) {
      if (!mounted) return;
      setState(() => _error = error);
    }
  }

  @override
  void dispose() {
    _watermarkTimer?.cancel();
    _securityEvents?.cancel();
    _stopViewerIfNeeded();
    SecurityService.disableSecurePlayback();
    _controller?.dispose();
    super.dispose();
  }

  void _shuffleWatermark() {
    const positions = [
      Alignment.topLeft,
      Alignment.topRight,
      Alignment.bottomLeft,
      Alignment.bottomRight,
    ];
    setState(() {
      _watermarkAlignment = positions[Random().nextInt(positions.length)];
    });
  }

  void _handleSecurityEvent(String event) async {
    if (event != 'screen_capture_detected') return;
    final controller = _controller;
    if (controller != null && controller.value.isPlaying) {
      await controller.pause();
      await _stopViewerIfNeeded();
      if (mounted && !_captureWarningVisible) {
        _captureWarningVisible = true;
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('Screen recording is not allowed.')),
        );
        _captureWarningVisible = false;
        setState(() {});
      }
    }
  }

  Future<void> _startViewerIfNeeded() async {
    if (_viewerStarted) return;
    try {
      await _api.startViewer(
        backendUrl: widget.backendUrl,
        tenantId: widget.tenantId,
        identity: widget.identity,
        match: widget.match,
        branding: widget.branding,
      );
      _viewerStarted = true;
    } catch (_) {}
  }

  Future<void> _stopViewerIfNeeded() async {
    if (!_viewerStarted) return;
    try {
      await _api.stopViewer(
        backendUrl: widget.backendUrl,
        tenantId: widget.tenantId,
        identity: widget.identity,
        streamId: widget.match.streamId,
        branding: widget.branding,
      );
    } catch (_) {
    } finally {
      _viewerStarted = false;
    }
  }

  @override
  Widget build(BuildContext context) {
    final controller = _controller;
    final watermarkText = widget.status.displayName.isNotEmpty
        ? 'User: ${widget.status.displayName}'
        : 'Device: ${widget.identity.deviceId.substring(0, min(8, widget.identity.deviceId.length))}';
    return Scaffold(
      appBar: AppBar(title: Text(widget.match.matchLabel)),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          _CompetitionSection(
            backendUrl: widget.backendUrl,
            competition: CompetitionCatalog(
              id: widget.competition.id,
              name: widget.competition.name,
              type: widget.competition.type,
              logo: widget.competition.logo,
              matches: [widget.match],
            ),
            onOpenMatch: (_) {},
          ),
          const SizedBox(height: 18),
          if (controller == null)
            _error != null
                ? Text('Playback failed: $_error', textAlign: TextAlign.center)
                : const Center(child: CircularProgressIndicator())
          else ...[
            AspectRatio(
              aspectRatio: controller.value.aspectRatio == 0 ? 16 / 9 : controller.value.aspectRatio,
              child: Stack(
                children: [
                  ClipRRect(
                    borderRadius: BorderRadius.circular(22),
                    child: VideoPlayer(controller),
                  ),
                  AnimatedAlign(
                    duration: const Duration(milliseconds: 500),
                    alignment: _watermarkAlignment,
                    child: Container(
                      margin: const EdgeInsets.all(16),
                      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
                      decoration: BoxDecoration(
                        color: Colors.black.withOpacity(0.38),
                        borderRadius: BorderRadius.circular(14),
                      ),
                      child: Text(
                        watermarkText,
                        style: const TextStyle(
                          color: Colors.white70,
                          fontSize: 11,
                          fontWeight: FontWeight.w700,
                        ),
                      ),
                    ),
                  ),
                ],
              ),
            ),
            const SizedBox(height: 12),
            VideoProgressIndicator(controller, allowScrubbing: true),
            const SizedBox(height: 12),
            FilledButton.icon(
              onPressed: () async {
                if (controller.value.isPlaying) {
                  await controller.pause();
                  await _stopViewerIfNeeded();
                } else {
                  await controller.play();
                  await _startViewerIfNeeded();
                }
                setState(() {});
              },
              icon: Icon(controller.value.isPlaying ? Icons.pause : Icons.play_arrow),
              label: Text(controller.value.isPlaying ? 'Pause stream' : 'Play stream'),
            ),
          ],
        ],
      ),
    );
  }
}

String _displayDate(String value) {
  if (value.isEmpty) return '-';
  final parsed = DateTime.tryParse(value);
  if (parsed == null) return value;
  final local = parsed.toLocal();
  final month = local.month.toString().padLeft(2, '0');
  final day = local.day.toString().padLeft(2, '0');
  return '${local.year}-$month-$day';
}

Color _parseHexColor(String value, Color fallback) {
  final normalized = value.trim().replaceFirst('#', '');
  if (normalized.length != 6) return fallback;
  final parsed = int.tryParse('FF$normalized', radix: 16);
  return parsed == null ? fallback : Color(parsed);
}

enum _BackendSettingsAction { cancel, clear, save }

class _BackendSettingsResult {
  const _BackendSettingsResult._(this.action, this.value);

  const _BackendSettingsResult.cancel() : this._(_BackendSettingsAction.cancel, '');

  const _BackendSettingsResult.clear() : this._(_BackendSettingsAction.clear, '');

  const _BackendSettingsResult.save(String value) : this._(_BackendSettingsAction.save, value);

  final _BackendSettingsAction action;
  final String value;
}
