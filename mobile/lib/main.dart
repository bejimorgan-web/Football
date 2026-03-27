import 'dart:async';
import 'dart:convert';
import 'dart:math';
import 'dart:ui' as ui;

import 'package:device_info_plus/device_info_plus.dart';
import 'package:dio/dio.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:http/http.dart' as http;
import 'package:install_plugin/install_plugin.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:video_player/video_player.dart';

import 'config/api_config.dart';
import 'config/backend.dart' as backend_config;
import 'config/network_config.dart';
import 'config/tenant_config.dart';
import 'services/tenant_service.dart';
import 'security/security_service.dart';

const String _deviceIdKey = 'device_id';
const String _deviceNameKey = 'device_name';
const String _devicePlatformKey = 'device_platform';
const String _tenantIdStorageKey = 'tenant_id';
const String _appVersion = '0.1.0';
const String _manualBackendUrlKey = 'manual_backend_url';
const String _controlPanelConfigEndpoint = '/api/config';
String get _bootstrapMasterWebBackendUrl => NetworkConfig.baseUrl;

class _ControlPanelApiConfig {
  const _ControlPanelApiConfig({
    required this.backendApiUrl,
    required this.backendApiToken,
    required this.publicApiUrl,
    required this.publicApiToken,
  });

  final String backendApiUrl;
  final String backendApiToken;
  final String publicApiUrl;
  final String publicApiToken;
}

Future<String?> _getBootstrapManualBackendUrl() async {
  try {
    final prefs = await SharedPreferences.getInstance();
    return prefs.getString(_manualBackendUrlKey);
  } catch (_) {
    return null;
  }
}

Future<void> _saveBootstrapTenantId(String tenant) async {
  try {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString(_tenantIdStorageKey, tenant.trim());
  } catch (_) {
    // Best-effort local persistence only.
  }
}

String _extractConfigString(Map<String, dynamic> source, List<String> keys) {
  for (final key in keys) {
    final value = '${source[key] ?? ''}'.trim();
    if (value.isNotEmpty) {
      return value;
    }
  }
  return '';
}

_ControlPanelApiConfig? _parseControlPanelApiConfig(Map<String, dynamic> payload) {
  final backendMap = payload['backend_api'] is Map<String, dynamic>
      ? payload['backend_api'] as Map<String, dynamic>
      : payload['backendApi'] is Map<String, dynamic>
          ? payload['backendApi'] as Map<String, dynamic>
          : const <String, dynamic>{};
  final publicMap = payload['public_api'] is Map<String, dynamic>
      ? payload['public_api'] as Map<String, dynamic>
      : payload['publicApi'] is Map<String, dynamic>
          ? payload['publicApi'] as Map<String, dynamic>
          : const <String, dynamic>{};

  final parsedBackendUrl = ApiConfig.normalize(_extractConfigString(backendMap, const ['url', 'backend_url']));
  final parsedPublicUrl = ApiConfig.normalize(
    _extractConfigString(publicMap, const ['url', 'api_base_url']).isNotEmpty
        ? _extractConfigString(publicMap, const ['url', 'api_base_url'])
        : _extractConfigString(payload, const ['apiBaseUrl', 'publicApiUrl', 'public_api_url']),
  );
  final backendApiUrlValue = parsedBackendUrl.isNotEmpty
      ? parsedBackendUrl
      : ApiConfig.normalize(_extractConfigString(payload, const ['backendUrl', 'backend_url', 'apiBaseUrl', 'publicApiUrl', 'public_api_url']));
  final publicApiUrlValue = parsedPublicUrl.isNotEmpty ? parsedPublicUrl : backendApiUrlValue;
  final backendApiTokenValue = _extractConfigString(
    backendMap,
    const ['api_token', 'apiToken', 'token'],
  ).isNotEmpty
      ? _extractConfigString(backendMap, const ['api_token', 'apiToken', 'token'])
      : _extractConfigString(payload, const ['backendApiToken', 'backend_api_token', 'api_token', 'apiToken']);
  final publicApiTokenValue = _extractConfigString(
    publicMap,
    const ['api_token', 'apiToken', 'token'],
  ).isNotEmpty
      ? _extractConfigString(publicMap, const ['api_token', 'apiToken', 'token'])
      : _extractConfigString(payload, const ['publicApiToken', 'public_api_token']);

  if (backendApiUrlValue.isEmpty && publicApiUrlValue.isEmpty) {
    return null;
  }

  return _ControlPanelApiConfig(
    backendApiUrl: backendApiUrlValue,
    backendApiToken: backendApiTokenValue,
    publicApiUrl: publicApiUrlValue,
    publicApiToken: publicApiTokenValue,
  );
}

Future<_ControlPanelApiConfig?> _fetchControlPanelApiConfig() async {
  final configUri = ApiConfig.uri(_bootstrapMasterWebBackendUrl, _controlPanelConfigEndpoint);
  final response = await http.get(configUri).timeout(const Duration(seconds: 3));
  if (response.statusCode != 200) {
    throw Exception('Control panel config request failed (${response.statusCode}).');
  }
  final payload = jsonDecode(response.body);
  if (payload is! Map<String, dynamic>) {
    throw Exception('Control panel config payload was invalid.');
  }
  return _parseControlPanelApiConfig(payload);
}

Future<Map<String, dynamic>> fetchControlPanelConfig() async {
  try {
    final parsed = await _fetchControlPanelApiConfig();
    if (parsed == null) {
      throw Exception('Control panel config did not include API URLs.');
    }
    return <String, dynamic>{
      'backend_api': <String, dynamic>{
        'url': parsed.backendApiUrl,
        'api_token': parsed.backendApiToken,
      },
      'public_api': <String, dynamic>{
        'url': parsed.publicApiUrl,
        'api_token': parsed.publicApiToken,
      },
    };
  } catch (_) {
    return <String, dynamic>{
      'backend_api': <String, dynamic>{
        'url': _bootstrapMasterWebBackendUrl,
        'api_token': '',
      },
      'public_api': <String, dynamic>{
        'url': _bootstrapMasterWebBackendUrl,
        'api_token': '',
      },
    };
  }
}

Future<void> bootstrap() async {
  backendApiUrl = '';
  backendApiToken = '';
  publicApiUrl = '';
  publicApiToken = '';
  activeBackendUrl = '';
  activeApiToken = '';
  if (kIsWeb) {
    tenantId = 'master';
    await _saveBootstrapTenantId(tenantId);
    backendApiUrl = ApiConfig.normalize(_bootstrapMasterWebBackendUrl);
    publicApiUrl = backendApiUrl;
    backendUrl = backendApiUrl;
  } else {
    tenantId = embeddedTenantId.trim().isEmpty ? 'default' : embeddedTenantId.trim();
    await _saveBootstrapTenantId(tenantId);
    publicApiUrl = ApiConfig.normalize(embeddedTenantBackendUrl);
    publicApiToken = embeddedTenantApiToken.trim();
    backendUrl = publicApiUrl;
  }

  final currentBackend = backendUrl.trim();
  final fallbackBackend = kIsWeb ? _bootstrapMasterWebBackendUrl : currentBackend;

  if (!kIsWeb) {
    try {
      final manualUrl = await _getBootstrapManualBackendUrl().timeout(const Duration(seconds: 2));
      final normalizedManualUrl = manualUrl?.trim() ?? '';
      if (normalizedManualUrl.isNotEmpty) {
        backendUrl = ApiConfig.normalize(normalizedManualUrl);
      }
    } catch (error) {
      if (backendUrl.trim().isEmpty) {
        backendUrl = ApiConfig.normalize(embeddedTenantBackendUrl);
      }
    }
  }

  if (kIsWeb) {
    try {
      final config = await fetchControlPanelConfig();
      final backendConfig = config['backend_api'] as Map<String, dynamic>? ?? const <String, dynamic>{};
      final publicConfig = config['public_api'] as Map<String, dynamic>? ?? const <String, dynamic>{};
      final configuredBackendUrl = '${backendConfig['url'] ?? ''}'.trim();
      final configuredPublicUrl = '${publicConfig['url'] ?? ''}'.trim();
      backendApiUrl = ApiConfig.normalize(configuredBackendUrl.isNotEmpty ? configuredBackendUrl : backendApiUrl);
      backendApiToken = '${backendConfig['api_token'] ?? ''}'.trim();
      publicApiUrl = ApiConfig.normalize(configuredPublicUrl.isNotEmpty ? configuredPublicUrl : backendApiUrl);
      publicApiToken = '${publicConfig['api_token'] ?? ''}'.trim();
    } catch (_) {}
    final manualUrl = (await _getBootstrapManualBackendUrl().timeout(const Duration(seconds: 2)).catchError((_) => null))?.trim() ?? '';
    if (backendApiUrl.trim().isEmpty) {
      backendApiUrl = ApiConfig.normalize(manualUrl.isNotEmpty ? manualUrl : _bootstrapMasterWebBackendUrl);
    }
    publicApiUrl = ApiConfig.normalize(publicApiUrl.isNotEmpty ? publicApiUrl : backendApiUrl);
    activeBackendUrl = backendApiUrl.isNotEmpty ? backendApiUrl : publicApiUrl;
    activeApiToken = backendApiToken;
    backendUrl = activeBackendUrl;
    return;
  }

  try {
    await loadTenantConfig().timeout(const Duration(seconds: 5));
  } catch (_) {
    final safeFallback = backendUrl.trim().isNotEmpty ? backendUrl : fallbackBackend;
    backendUrl = ApiConfig.normalize(safeFallback);
  }

  publicApiUrl = ApiConfig.normalize(backendUrl);
  activeBackendUrl = publicApiUrl;
  activeApiToken = publicApiToken;
}

void main() {
  WidgetsFlutterBinding.ensureInitialized();
  FlutterError.onError = (details) {
    FlutterError.presentError(details);
  };
  ui.PlatformDispatcher.instance.onError = (error, stack) {
    return true;
  };
  runApp(const _BootstrapApp());
}

class _BootstrapApp extends StatefulWidget {
  const _BootstrapApp();

  @override
  State<_BootstrapApp> createState() => _BootstrapAppState();
}

class _BootstrapAppState extends State<_BootstrapApp> {
  Future<void>? _bootstrapFuture;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!mounted) return;
      setState(() {
        _bootstrapFuture = bootstrap();
      });
    });
  }

  @override
  Widget build(BuildContext context) {
    final bootstrapFuture = _bootstrapFuture;
    if (bootstrapFuture == null) {
      return const MaterialApp(
        debugShowCheckedModeBanner: false,
        home: Scaffold(
          body: Center(
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                CircularProgressIndicator(),
                SizedBox(height: 16),
                Text('Starting web client...'),
              ],
            ),
          ),
        ),
      );
    }

    return FutureBuilder<void>(
      future: bootstrapFuture,
      builder: (context, snapshot) {
        if (snapshot.connectionState != ConnectionState.done) {
          return const MaterialApp(
            debugShowCheckedModeBanner: false,
            home: Scaffold(
              body: Center(
                child: Column(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    CircularProgressIndicator(),
                    SizedBox(height: 16),
                    Text('Loading...'),
                  ],
                ),
              ),
            ),
          );
        }

        if (snapshot.hasError) {
          return MaterialApp(
            debugShowCheckedModeBanner: false,
            home: Scaffold(
              body: Center(
                child: Padding(
                  padding: const EdgeInsets.all(24),
                  child: Column(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      const Icon(Icons.cloud_off, size: 48),
                      const SizedBox(height: 16),
                      const Text(
                        'Startup failed',
                        style: TextStyle(fontSize: 22, fontWeight: FontWeight.w700),
                      ),
                      const SizedBox(height: 8),
                      Text(
                        '${snapshot.error}',
                        textAlign: TextAlign.center,
                      ),
                      const SizedBox(height: 16),
                      FilledButton(
                        onPressed: () {
                          setState(() {
                            _bootstrapFuture = bootstrap();
                          });
                        },
                        child: const Text('Retry'),
                      ),
                    ],
                  ),
                ),
              ),
            ),
          );
        }

        return const FootballStreamingApp();
      },
    );
  }
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
      locale: _branding.locale,
      supportedLocales: _branding.supportedLocales,
      localizationsDelegates: const [
        GlobalMaterialLocalizations.delegate,
        GlobalWidgetsLocalizations.delegate,
        GlobalCupertinoLocalizations.delegate,
      ],
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
    required this.defaultLanguage,
    required this.supportedLanguages,
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
  final String defaultLanguage;
  final List<String> supportedLanguages;

  Locale? get locale => defaultLanguage == 'system' ? null : Locale(defaultLanguage);

  List<Locale> get supportedLocales {
    final items = supportedLanguages.isEmpty ? const ['en', 'fr'] : supportedLanguages;
    return items.map((item) => Locale(item)).toList(growable: false);
  }

  factory TenantBranding.fallback() => TenantBranding(
        tenantId: 'default',
        appName: 'Football Streaming',
        logoUrl: '',
        primaryColor: const Color(0xFF11B37C),
        accentColor: const Color(0xFF7EE3AF),
        surfaceColor: const Color(0xFF0D1E2B),
        backgroundColor: const Color(0xFF07141E),
        textColor: const Color(0xFFF2F8FF),
        apiBaseUrl: '',
        mobileApiToken: '',
        serverId: '',
        defaultLanguage: 'system',
        supportedLanguages: const ['en', 'fr'],
      );

  factory TenantBranding.fromJson(Map<String, dynamic> json) {
    final branding = json['branding'] as Map<String, dynamic>? ?? const {};
    final mobileAuth = json['mobile_auth'] as Map<String, dynamic>? ?? const {};
    final language = json['language'] as Map<String, dynamic>? ?? const {};
    final supported = (language['supported'] as List<dynamic>? ?? const <dynamic>[])
        .map((item) => '$item'.trim().toLowerCase())
        .where((item) => item.isNotEmpty)
        .toList();
    return TenantBranding(
      tenantId: '${json['tenant_id'] ?? 'default'}',
      appName: '${branding['app_name'] ?? json['name'] ?? 'Football Streaming'}',
      logoUrl: '${branding['logo_url'] ?? ''}',
      primaryColor: _parseHexColor('${branding['primary_color'] ?? '#11B37C'}', const Color(0xFF11B37C)),
      accentColor: _parseHexColor('${branding['accent_color'] ?? '#7EE3AF'}', const Color(0xFF7EE3AF)),
      surfaceColor: _parseHexColor('${branding['surface_color'] ?? '#0D1E2B'}', const Color(0xFF0D1E2B)),
      backgroundColor: _parseHexColor('${branding['background_color'] ?? '#07141E'}', const Color(0xFF07141E)),
      textColor: _parseHexColor('${branding['text_color'] ?? '#F2F8FF'}', const Color(0xFFF2F8FF)),
      apiBaseUrl: ApiConfig.normalize('${json['backend_url'] ?? branding['api_base_url'] ?? ''}'),
      mobileApiToken: '${mobileAuth['api_token'] ?? ''}',
      serverId: '${mobileAuth['server_id'] ?? ''}',
      defaultLanguage: '${language['default'] ?? 'system'}',
      supportedLanguages: supported.isEmpty ? const ['en', 'fr'] : supported,
    );
  }
}

class FeatureFlags {
  const FeatureFlags({
    required this.liveScores,
    required this.standings,
    required this.schedules,
    required this.coreFeatureUpdates,
    required this.tenantLocked,
  });

  final bool liveScores;
  final bool standings;
  final bool schedules;
  final bool coreFeatureUpdates;
  final bool tenantLocked;

  factory FeatureFlags.fromJson(Map<String, dynamic> json) {
    return FeatureFlags(
      liveScores: json['live_scores'] == true,
      standings: json['standings'] == true,
      schedules: json['schedules'] == true,
      coreFeatureUpdates: json['core_feature_updates'] == true,
      tenantLocked: json['tenant_locked'] == true,
    );
  }
}

class RuntimeManifest {
  const RuntimeManifest({
    required this.currentVersion,
    required this.latestVersion,
    required this.minimumSupportedVersion,
    required this.isSupported,
    required this.forceUpdate,
    required this.updateUrl,
    required this.languageDefault,
    required this.supportedLanguages,
    required this.featureFlags,
  });

  final String currentVersion;
  final String latestVersion;
  final String minimumSupportedVersion;
  final bool isSupported;
  final bool forceUpdate;
  final String updateUrl;
  final String languageDefault;
  final List<String> supportedLanguages;
  final FeatureFlags featureFlags;

  factory RuntimeManifest.fromJson(Map<String, dynamic> json) {
    final mobile = json['mobile'] as Map<String, dynamic>? ?? const {};
    final language = mobile['language'] as Map<String, dynamic>? ?? const {};
    return RuntimeManifest(
      currentVersion: '${mobile['current_version'] ?? _appVersion}',
      latestVersion: '${mobile['latest_version'] ?? json['latest_version'] ?? _appVersion}',
      minimumSupportedVersion: '${mobile['minimum_supported_version'] ?? _appVersion}',
      isSupported: mobile['is_supported'] != false,
      forceUpdate: mobile['force_update'] == true || json['force_update'] == true,
      updateUrl: '${mobile['update_url'] ?? json['update_url'] ?? ''}',
      languageDefault: '${language['default'] ?? 'system'}',
      supportedLanguages: (language['supported'] as List<dynamic>? ?? const <dynamic>[])
          .map((item) => '$item'.trim().toLowerCase())
          .where((item) => item.isNotEmpty)
          .toList(),
      featureFlags: FeatureFlags.fromJson(mobile['feature_flags'] as Map<String, dynamic>? ?? const {}),
    );
  }
}

class LiveScoreEntry {
  const LiveScoreEntry({
    required this.homeTeam,
    required this.awayTeam,
    required this.score,
    required this.status,
  });

  final String homeTeam;
  final String awayTeam;
  final String score;
  final String status;

  factory LiveScoreEntry.fromJson(Map<String, dynamic> json) {
    final home = json['homeTeam'] as Map<String, dynamic>? ?? const {};
    final away = json['awayTeam'] as Map<String, dynamic>? ?? const {};
    final score = json['score'] as Map<String, dynamic>? ?? const {};
    final fullTime = score['fullTime'] as Map<String, dynamic>? ?? const {};
    return LiveScoreEntry(
      homeTeam: '${home['shortName'] ?? home['name'] ?? 'Home'}',
      awayTeam: '${away['shortName'] ?? away['name'] ?? 'Away'}',
      score: '${fullTime['home'] ?? '-'}:${fullTime['away'] ?? '-'}',
      status: '${json['status'] ?? 'LIVE'}',
    );
  }
}

class FixtureEntry {
  const FixtureEntry({
    required this.homeTeam,
    required this.awayTeam,
    required this.kickoff,
  });

  final String homeTeam;
  final String awayTeam;
  final String kickoff;

  factory FixtureEntry.fromJson(Map<String, dynamic> json) {
    final home = json['homeTeam'] as Map<String, dynamic>? ?? const {};
    final away = json['awayTeam'] as Map<String, dynamic>? ?? const {};
    return FixtureEntry(
      homeTeam: '${home['shortName'] ?? home['name'] ?? 'Home'}',
      awayTeam: '${away['shortName'] ?? away['name'] ?? 'Away'}',
      kickoff: _displayDateTime('${json['utcDate'] ?? ''}'),
    );
  }
}

class StandingEntry {
  const StandingEntry({
    required this.position,
    required this.team,
    required this.played,
    required this.points,
  });

  final int position;
  final String team;
  final int played;
  final int points;

  factory StandingEntry.fromJson(Map<String, dynamic> json) {
    final team = json['team'] as Map<String, dynamic>? ?? const {};
    return StandingEntry(
      position: int.tryParse('${json['position'] ?? 0}') ?? 0,
      team: '${team['shortName'] ?? team['name'] ?? 'Team'}',
      played: int.tryParse('${json['playedGames'] ?? 0}') ?? 0,
      points: int.tryParse('${json['points'] ?? 0}') ?? 0,
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
      logo: '${json['logo'] ?? json['logo_url'] ?? ''}',
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
      logo: '${json['logo'] ?? json['logo_url'] ?? ''}',
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
      homeTeamName: '${json['home_team_name'] ?? json['home_club_name'] ?? homeClub['name'] ?? 'Home'}',
      homeTeamLogo: '${json['home_team_logo'] ?? json['home_club_logo'] ?? homeClub['logo'] ?? homeClub['logo_url'] ?? ''}',
      awayTeamName: '${json['away_team_name'] ?? json['away_club_name'] ?? awayClub['name'] ?? 'Away'}',
      awayTeamLogo: '${json['away_team_logo'] ?? json['away_club_logo'] ?? awayClub['logo'] ?? awayClub['logo_url'] ?? ''}',
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
    required this.runtimeManifest,
    required this.liveScores,
    required this.fixtures,
    required this.standings,
  });

  final String backendUrl;
  final String tenantId;
  final TenantBranding branding;
  final DeviceIdentity identity;
  final SecuritySnapshot security;
  final DeviceStatus status;
  final List<NationCatalog> catalog;
  final RuntimeManifest runtimeManifest;
  final List<LiveScoreEntry> liveScores;
  final List<FixtureEntry> fixtures;
  final List<StandingEntry> standings;
}

bool _isVersionLower(String currentVersion, String latestVersion) {
  List<int> parse(String value) => value
      .split('.')
      .map((item) => int.tryParse(item.trim()) ?? 0)
      .toList(growable: false);

  final current = parse(currentVersion);
  final latest = parse(latestVersion);
  final length = max(current.length, latest.length);
  for (var index = 0; index < length; index += 1) {
    final currentPart = index < current.length ? current[index] : 0;
    final latestPart = index < latest.length ? latest[index] : 0;
    if (currentPart < latestPart) return true;
    if (currentPart > latestPart) return false;
  }
  return false;
}

class MobileApi {
  const MobileApi();

  Future<String> ensureTenantId() async {
    return tenantId.trim();
  }

  Future<void> saveTenantId(String newTenantId) async {
    // Tenant assignment is fixed at startup by embeddedTenantId or web master mode.
    return;
  }

  Future<TenantBranding> fetchBranding(String backendUrl, String tenantId) async {
    final uri = ApiConfig.uri(backendUrl, '/config/branding', {
      'tenant_id': tenantId,
    });
    final response = await http.get(uri).timeout(const Duration(seconds: 5));
    if (response.statusCode != 200) {
      throw Exception(_extractDetail(response.body, response.statusCode));
    }
    final payload = jsonDecode(response.body) as Map<String, dynamic>;
    return TenantBranding.fromJson(payload);
  }

  Future<RuntimeManifest> fetchRuntimeManifest(String backendUrl, String tenantId) async {
    final uri = ApiConfig.uri(backendUrl, '/api/version', {
      'tenant_id': tenantId,
      'current_version': _appVersion,
      'client': 'mobile',
      'platform': defaultTargetPlatform.name,
    });
    final response = await http.get(uri).timeout(const Duration(seconds: 5));
    if (response.statusCode != 200) {
      throw Exception(_extractDetail(response.body, response.statusCode));
    }
    final payload = jsonDecode(response.body) as Map<String, dynamic>;
    return RuntimeManifest.fromJson(payload);
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
        deviceName = ios.utsname.machine.trim().isNotEmpty == true ? ios.utsname.machine : (ios.model ?? 'iPhone');
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

  Future<void> checkServer(String backendUrl) async {
    try {
      final response = await http.get(ApiConfig.uri(backendUrl, '/api/version')).timeout(const Duration(seconds: 4));
      if (response.statusCode != 200) {}
    } catch (_) {}
  }

  Future<void> registerDevice(
    String backendUrl,
    String tenantId,
    DeviceIdentity identity,
    SecuritySnapshot security,
    TenantBranding branding,
  ) async {
    final response = await http.post(
      ApiConfig.uri(backendUrl, '/device/register'),
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
    final uri = ApiConfig.uri(backendUrl, '/device/status', {
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
      ApiConfig.uri(backendUrl, '/streams/catalog', {
        'tenant_id': tenantId,
        'device_id': deviceId,
        'server_id': branding.serverId,
      }),
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

  Future<List<LiveScoreEntry>> fetchLiveScores(String backendUrl) async {
    try {
      final response = await http.get(ApiConfig.uri(backendUrl, '/football/live'));
      if (response.statusCode != 200) {
        return const [];
      }
      final payload = jsonDecode(response.body) as Map<String, dynamic>;
      return (payload['matches'] as List<dynamic>? ?? const <dynamic>[])
          .whereType<Map<String, dynamic>>()
          .map(LiveScoreEntry.fromJson)
          .toList();
    } catch (_) {
      return const [];
    }
  }

  Future<List<FixtureEntry>> fetchFixtures(String backendUrl, {String competitionCode = 'PL'}) async {
    try {
      final response = await http.get(ApiConfig.uri(backendUrl, '/football/fixtures', {
        'competition_code': competitionCode,
      }));
      if (response.statusCode != 200) {
        return const [];
      }
      final payload = jsonDecode(response.body) as Map<String, dynamic>;
      return (payload['matches'] as List<dynamic>? ?? const <dynamic>[])
          .whereType<Map<String, dynamic>>()
          .take(5)
          .map(FixtureEntry.fromJson)
          .toList();
    } catch (_) {
      return const [];
    }
  }

  Future<List<StandingEntry>> fetchStandings(String backendUrl, {String competitionCode = 'PL'}) async {
    try {
      final response = await http.get(ApiConfig.uri(backendUrl, '/football/standings', {
        'competition_code': competitionCode,
      }));
      if (response.statusCode != 200) {
        return const [];
      }
      final payload = jsonDecode(response.body) as Map<String, dynamic>;
      final standings = payload['standings'] as List<dynamic>? ?? const <dynamic>[];
      final first = standings.whereType<Map<String, dynamic>>().firstWhere(
            (item) => item['table'] is List<dynamic>,
            orElse: () => <String, dynamic>{},
          );
      final table = first['table'] as List<dynamic>? ?? const <dynamic>[];
      return table.whereType<Map<String, dynamic>>().take(5).map(StandingEntry.fromJson).toList();
    } catch (_) {
      return const [];
    }
  }

  Future<String> fetchStreamTokenUrl({
    required String backendUrl,
    required String tenantId,
    required String deviceId,
    required String streamId,
    required SecuritySnapshot security,
    required TenantBranding branding,
  }) async {
    final uri = ApiConfig.uri(backendUrl, '/streams/token/$streamId', {
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
    return resolveUrl(relative, baseUrl: backendUrl);
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
      ApiConfig.uri(backendUrl, '/viewer/start'),
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
      ApiConfig.uri(backendUrl, '/viewer/stop'),
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
    const maxRandom = 1 << 32;
    final right = maxRandom <= 0 ? '0' : random.nextInt(maxRandom).toRadixString(16);
    return 'device-$left-$right';
  }

  Map<String, String> _mobileHeaders(TenantBranding branding, String tenantId, String deviceId) {
    final resolvedToken = branding.mobileApiToken.trim().isNotEmpty
        ? branding.mobileApiToken.trim()
        : activeApiToken.trim();
    return {
      'Content-Type': 'application/json',
      'X-Api-Token': resolvedToken,
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
  String get _masterWebBackendUrl => NetworkConfig.baseUrl;

  final MobileApi _api = const MobileApi();
  late Future<AppSession> _sessionFuture;
  bool _showBackendSettings = false;
  String _handledUpdateVersion = '';

  Future<String?> getManualBackendUrl() async {
    return backend_config.getManualBackendUrl();
  }

  Future<void> setManualBackendUrl(String url) async {
    await backend_config.setManualBackendUrl(url);
  }

  Future<void> clearManualBackendUrl() async {
    await backend_config.clearManualBackendUrl();
  }

  Future<String> resolveBackendUrl() async {
    final resolved = await backend_config.resolveBackendUrl();
    if (resolved.trim().isNotEmpty) {
      return ApiConfig.normalize(resolved);
    }
    if (kIsWeb) {
      return ApiConfig.normalize(_masterWebBackendUrl);
    }
    return ApiConfig.normalize(NetworkConfig.baseUrl);
  }

  @override
  void initState() {
    super.initState();
    _sessionFuture = _loadSession();
  }

  Future<AppSession> _loadSession() async {
    final initialBackendUrl = ApiConfig.normalize(await resolveBackendUrl());
    await _api.checkServer(initialBackendUrl);
    final resolvedTenantId = await _api.ensureTenantId();
    final canShowBackendSettings = kIsWeb && resolvedTenantId == 'master';
    if (mounted) {
      setState(() => _showBackendSettings = canShowBackendSettings);
    } else {
      _showBackendSettings = canShowBackendSettings;
    }
    final initialBranding = await _api.fetchBranding(initialBackendUrl, resolvedTenantId);
    final resolvedBackendUrl = initialBackendUrl;
    backendUrl = resolvedBackendUrl;
    activeBackendUrl = resolvedBackendUrl;
    tenantId = resolvedTenantId;
    await _saveBootstrapTenantId(resolvedTenantId);
    final runtimeManifest = await _api.fetchRuntimeManifest(resolvedBackendUrl, resolvedTenantId);
    final branding = TenantBranding(
      tenantId: initialBranding.tenantId,
      appName: initialBranding.appName,
      logoUrl: initialBranding.logoUrl,
      primaryColor: initialBranding.primaryColor,
      accentColor: initialBranding.accentColor,
      surfaceColor: initialBranding.surfaceColor,
      backgroundColor: initialBranding.backgroundColor,
      textColor: initialBranding.textColor,
      apiBaseUrl: resolvedBackendUrl,
      mobileApiToken: initialBranding.mobileApiToken.trim().isNotEmpty ? initialBranding.mobileApiToken : activeApiToken,
      serverId: initialBranding.serverId,
      defaultLanguage: runtimeManifest.languageDefault,
      supportedLanguages: runtimeManifest.supportedLanguages.isEmpty ? initialBranding.supportedLanguages : runtimeManifest.supportedLanguages,
    );
    widget.onBrandingChanged(branding);
    final identity = await _api.ensureIdentity();
    final security = await SecurityService.getSecuritySnapshot();
    if (!security.appSignatureValid) {
      throw Exception('App signature verification failed. API requests were blocked.');
    }
    if (!runtimeManifest.isSupported) {
      throw Exception('This mobile build is no longer supported. Install the latest app package from the master portal.');
    }
    await _api.registerDevice(resolvedBackendUrl, resolvedTenantId, identity, security, branding);
    final status = await _api.fetchStatus(resolvedBackendUrl, resolvedTenantId, identity.deviceId, security, branding);
    final catalog = status.isAllowed ? await _api.fetchCatalog(resolvedBackendUrl, resolvedTenantId, identity.deviceId, branding) : <NationCatalog>[];
    final liveScores = runtimeManifest.featureFlags.liveScores ? await _api.fetchLiveScores(resolvedBackendUrl) : const <LiveScoreEntry>[];
    final fixtures = runtimeManifest.featureFlags.schedules ? await _api.fetchFixtures(resolvedBackendUrl) : const <FixtureEntry>[];
    final standings = runtimeManifest.featureFlags.standings ? await _api.fetchStandings(resolvedBackendUrl) : const <StandingEntry>[];
    return AppSession(
      backendUrl: resolvedBackendUrl,
      tenantId: resolvedTenantId,
      branding: branding,
      identity: identity,
      security: security,
      status: status,
      catalog: catalog,
      runtimeManifest: runtimeManifest,
      liveScores: liveScores,
      fixtures: fixtures,
      standings: standings,
    );
  }

  Future<void> _refresh() async {
    setState(() {
      _sessionFuture = _loadSession();
    });
    await _sessionFuture;
  }

  Future<void> _downloadAndInstallUpdate(String url) async {
    const targetPath = '/storage/emulated/0/Download/app.apk';
    final dio = Dio();
    await dio.download(url, targetPath);
    await InstallPlugin.installApk(targetPath);
  }

  Future<void> _maybePromptForUpdate(AppSession session) async {
    if (!mounted || kIsWeb || defaultTargetPlatform != TargetPlatform.android) {
      return;
    }
    final manifest = session.runtimeManifest;
    final latestVersion = manifest.latestVersion.trim();
    final updateUrl = manifest.updateUrl.trim();
    if (latestVersion.isEmpty || updateUrl.isEmpty) {
      return;
    }
    if (!_isVersionLower(_appVersion, latestVersion)) {
      return;
    }
    if (_handledUpdateVersion == latestVersion) {
      return;
    }
    _handledUpdateVersion = latestVersion;
    WidgetsBinding.instance.addPostFrameCallback((_) async {
      if (!mounted) return;
      final shouldUpdate = await showDialog<bool>(
            context: context,
            barrierDismissible: !manifest.forceUpdate,
            builder: (context) => AlertDialog(
              title: const Text('Update Available'),
              content: Text('Version $latestVersion is available. Download and install it now?'),
              actions: [
                if (!manifest.forceUpdate)
                  TextButton(
                    onPressed: () => Navigator.of(context).pop(false),
                    child: const Text('Later'),
                  ),
                FilledButton(
                  onPressed: () => Navigator.of(context).pop(true),
                  child: const Text('Update'),
                ),
              ],
            ),
          ) ??
          false;
      if (!shouldUpdate || !mounted) return;
      try {
        await _downloadAndInstallUpdate(updateUrl);
      } catch (error) {
        if (!mounted) return;
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Update failed: $error')),
        );
      }
    });
  }

  Future<void> _openBackendSettings() async {
    final currentManualBackendUrl = await getManualBackendUrl();
    if (!mounted) return;
    final controller = TextEditingController(text: currentManualBackendUrl ?? backendUrl);
    final result = await showDialog<String>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('Backend Settings'),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            const Text(
              'Chrome master mode uses the master backend by default. '
              'Set a manual override here if you need to point the web client elsewhere.',
            ),
            const SizedBox(height: 12),
            TextField(
              controller: controller,
              decoration: const InputDecoration(
                labelText: 'Backend URL',
                hintText: 'http://127.0.0.1:8000',
              ),
              autofocus: true,
              keyboardType: TextInputType.url,
            ),
          ],
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(context).pop(),
            child: const Text('Cancel'),
          ),
          TextButton(
            onPressed: () => Navigator.of(context).pop('__USE_MASTER__'),
            child: const Text('Use Master'),
          ),
          FilledButton(
            onPressed: () => Navigator.of(context).pop(controller.text.trim()),
            child: const Text('Save'),
          ),
        ],
      ),
    );

    if (!mounted || result == null) return;
    if (result == '__USE_MASTER__' || result.isEmpty) {
      await clearManualBackendUrl();
      backendUrl = ApiConfig.normalize(activeBackendUrl.isNotEmpty ? activeBackendUrl : _masterWebBackendUrl);
    } else {
      await setManualBackendUrl(result);
      backendUrl = ApiConfig.normalize(result);
    }
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
            secondaryLabel: _showBackendSettings ? 'Backend Settings' : null,
            onSecondaryPressed: _showBackendSettings ? _openBackendSettings : null,
          );
        }

        final session = snapshot.data!;
        _maybePromptForUpdate(session);
        if (session.status.status == 'blocked' || session.status.status == 'device_blocked' || session.status.status == 'vpn_blocked' || session.status.status == 'insecure_device') {
          return BlockedAccessPage(
            backendUrl: session.backendUrl,
            branding: session.branding,
            status: session.status,
            onRefresh: _refresh,
            onBackendSettings: _showBackendSettings ? _openBackendSettings : null,
          );
        }
        if (!session.status.isAllowed) {
          return SubscriptionPage(
            backendUrl: session.backendUrl,
            branding: session.branding,
            status: session.status,
            onRefresh: _refresh,
            onBackendSettings: _showBackendSettings ? _openBackendSettings : null,
          );
        }
        return MatchCatalogPage(
          session: session,
          onRefresh: _refresh,
          onBackendSettings: null,
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
  final Future<void> Function()? onBackendSettings;

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
                branding: session.branding,
                onRefresh: onRefresh,
              ),
              const SizedBox(height: 18),
              if (nations.isEmpty)
                _InfoPanel(
                  icon: Icons.sports_soccer,
                  title: 'No matches available',
                  subtitle: 'Please check back shortly.',
                ),
              for (final nation in nations) ...[
                _CountryCard(
                  backendUrl: session.backendUrl,
                  nation: nation,
                  onTap: () {
                    Navigator.of(context).push(
                      MaterialPageRoute<void>(
                        builder: (_) => CompetitionListPage(
                          session: session,
                          nation: nation,
                        ),
                      ),
                    );
                  },
                ),
                const SizedBox(height: 14),
              ],
            ],
          ),
        ),
      ),
    );
  }
}

class CompetitionListPage extends StatelessWidget {
  const CompetitionListPage({
    super.key,
    required this.session,
    required this.nation,
  });

  final AppSession session;
  final NationCatalog nation;

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: Text(nation.name)),
      body: ListView(
        padding: const EdgeInsets.fromLTRB(16, 16, 16, 28),
        children: [
          _SectionIntroCard(
            eyebrow: 'Competitions',
            title: nation.name,
            subtitle: '${nation.competitions.length} competition${nation.competitions.length == 1 ? '' : 's'} ready to browse',
            leading: _NetworkLogo(
              url: nation.logo,
              backendUrl: session.backendUrl,
              size: 54,
              fallbackIcon: Icons.flag,
            ),
          ),
          const SizedBox(height: 18),
          for (final competition in nation.competitions) ...[
            _CompetitionCard(
              backendUrl: session.backendUrl,
              competition: competition,
              onTap: () {
                Navigator.of(context).push(
                  MaterialPageRoute<void>(
                    builder: (_) => MatchListPage(
                      session: session,
                      nation: nation,
                      competition: competition,
                    ),
                  ),
                );
              },
            ),
            const SizedBox(height: 14),
          ],
        ],
      ),
    );
  }
}

class MatchListPage extends StatelessWidget {
  const MatchListPage({
    super.key,
    required this.session,
    required this.nation,
    required this.competition,
  });

  final AppSession session;
  final NationCatalog nation;
  final CompetitionCatalog competition;

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: Text(competition.name)),
      body: ListView(
        padding: const EdgeInsets.fromLTRB(16, 16, 16, 28),
        children: [
          _SectionIntroCard(
            eyebrow: nation.name,
            title: competition.name,
            subtitle: '${competition.matches.length} match${competition.matches.length == 1 ? '' : 'es'} available',
            leading: _NetworkLogo(
              url: competition.logo,
              backendUrl: session.backendUrl,
              size: 54,
              fallbackIcon: competition.type == 'cup' ? Icons.emoji_events : Icons.shield,
            ),
          ),
          const SizedBox(height: 18),
          for (final match in competition.matches) ...[
            _MatchCard(
              backendUrl: session.backendUrl,
              match: match,
              onTap: () {
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
            const SizedBox(height: 14),
          ],
        ],
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
  final Future<void> Function()? onBackendSettings;

  @override
  Widget build(BuildContext context) {
    return _InfoScreen(
      icon: Icons.block,
      title: '${branding.appName} access disabled',
      subtitle: status.message,
      actionLabel: 'Refresh Status',
      onPressed: onRefresh,
      secondaryLabel: null,
      onSecondaryPressed: null,
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
  final Future<void> Function()? onBackendSettings;

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
                '${branding.appName} access paused',
                style: const TextStyle(fontSize: 30, fontWeight: FontWeight.w900),
              ),
              const SizedBox(height: 10),
              Text(
                status.message,
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
            ],
          ),
        ),
      ),
    );
  }
}

class _HeroHeader extends StatelessWidget {
  const _HeroHeader({
    required this.branding,
    required this.onRefresh,
  });

  final TenantBranding branding;
  final Future<void> Function() onRefresh;

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
              _NetworkLogo(
                url: branding.logoUrl,
                backendUrl: branding.apiBaseUrl,
                size: 56,
                fallbackIcon: Icons.sports_soccer,
              ),
              const SizedBox(width: 14),
              Expanded(
                child: Text(
                  branding.appName,
                  style: const TextStyle(fontSize: 31, fontWeight: FontWeight.w900, height: 1.1),
                ),
              ),
              IconButton(
                onPressed: onRefresh,
                icon: const Icon(Icons.refresh),
              ),
            ],
          ),
          const SizedBox(height: 18),
          Text(
            'Browse competitions, open matches, and start watching instantly.',
            style: TextStyle(color: Colors.white.withOpacity(0.82), height: 1.45),
          ),
        ],
      ),
    );
  }
}

class _FootballUpdatesPanel extends StatelessWidget {
  const _FootballUpdatesPanel({
    required this.liveScores,
    required this.fixtures,
    required this.standings,
  });

  final List<LiveScoreEntry> liveScores;
  final List<FixtureEntry> fixtures;
  final List<StandingEntry> standings;

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
          const Text(
            'Master Football Updates',
            style: TextStyle(fontSize: 22, fontWeight: FontWeight.w900),
          ),
          const SizedBox(height: 8),
          const Text(
            'Live scores, Premier League schedule, and table snapshots are delivered dynamically from the backend.',
            style: TextStyle(color: Color(0xFF9CB6C8), height: 1.45),
          ),
          const SizedBox(height: 16),
          if (liveScores.isNotEmpty) ...[
            const Text('Live Scores', style: TextStyle(fontWeight: FontWeight.w800)),
            const SizedBox(height: 10),
            for (final item in liveScores.take(3)) ...[
              _RuntimeTile(title: '${item.homeTeam} vs ${item.awayTeam}', subtitle: '${item.score}  •  ${item.status}'),
              const SizedBox(height: 8),
            ],
            const SizedBox(height: 10),
          ],
          if (fixtures.isNotEmpty) ...[
            const Text('Upcoming Schedule', style: TextStyle(fontWeight: FontWeight.w800)),
            const SizedBox(height: 10),
            for (final item in fixtures.take(3)) ...[
              _RuntimeTile(title: '${item.homeTeam} vs ${item.awayTeam}', subtitle: item.kickoff),
              const SizedBox(height: 8),
            ],
            const SizedBox(height: 10),
          ],
          if (standings.isNotEmpty) ...[
            const Text('Standings Snapshot', style: TextStyle(fontWeight: FontWeight.w800)),
            const SizedBox(height: 10),
            for (final item in standings.take(5)) ...[
              _RuntimeTile(title: '${item.position}. ${item.team}', subtitle: 'P ${item.played}  •  ${item.points} pts'),
              const SizedBox(height: 8),
            ],
          ],
          if (liveScores.isEmpty && fixtures.isEmpty && standings.isEmpty)
            const Text(
              'Dynamic football modules are enabled, but no live data is currently available from the backend feed.',
              style: TextStyle(color: Color(0xFF9CB6C8)),
            ),
        ],
      ),
    );
  }
}

class _SectionIntroCard extends StatelessWidget {
  const _SectionIntroCard({
    required this.eyebrow,
    required this.title,
    required this.subtitle,
    required this.leading,
  });

  final String eyebrow;
  final String title;
  final String subtitle;
  final Widget leading;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(18),
      decoration: BoxDecoration(
        color: const Color(0xFF0B1A25),
        borderRadius: BorderRadius.circular(28),
        border: Border.all(color: Colors.white.withOpacity(0.06)),
      ),
      child: Row(
        children: [
          leading,
          const SizedBox(width: 14),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  eyebrow.toUpperCase(),
                  style: const TextStyle(
                    color: Color(0xFF7EE3AF),
                    fontSize: 12,
                    fontWeight: FontWeight.w800,
                    letterSpacing: 1.0,
                  ),
                ),
                const SizedBox(height: 6),
                Text(
                  title,
                  style: const TextStyle(fontSize: 24, fontWeight: FontWeight.w900),
                ),
                const SizedBox(height: 6),
                Text(
                  subtitle,
                  style: const TextStyle(color: Color(0xFF9CB6C8), height: 1.45),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

class _RuntimeTile extends StatelessWidget {
  const _RuntimeTile({
    required this.title,
    required this.subtitle,
  });

  final String title;
  final String subtitle;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: Colors.white.withOpacity(0.04),
        borderRadius: BorderRadius.circular(18),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(title, style: const TextStyle(fontWeight: FontWeight.w800)),
          const SizedBox(height: 4),
          Text(subtitle, style: const TextStyle(color: Color(0xFF9CB6C8))),
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

class _CountryCard extends StatelessWidget {
  const _CountryCard({
    required this.backendUrl,
    required this.nation,
    required this.onTap,
  });

  final String backendUrl;
  final NationCatalog nation;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final matchCount = nation.competitions.fold<int>(0, (sum, item) => sum + item.matches.length);
    return InkWell(
      onTap: onTap,
      borderRadius: BorderRadius.circular(28),
      child: Ink(
        padding: const EdgeInsets.all(18),
        decoration: BoxDecoration(
          borderRadius: BorderRadius.circular(28),
          gradient: const LinearGradient(
            colors: [Color(0xFF0F2434), Color(0xFF112F2F)],
            begin: Alignment.topLeft,
            end: Alignment.bottomRight,
          ),
          border: Border.all(color: Colors.white.withOpacity(0.06)),
        ),
        child: Row(
          children: [
            _NetworkLogo(
              url: nation.logo,
              backendUrl: backendUrl,
              size: 56,
              fallbackIcon: Icons.flag,
            ),
            const SizedBox(width: 14),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    nation.name,
                    style: const TextStyle(fontSize: 21, fontWeight: FontWeight.w900),
                  ),
                  const SizedBox(height: 6),
                  Text(
                    '${nation.competitions.length} competition${nation.competitions.length == 1 ? '' : 's'}  •  $matchCount match${matchCount == 1 ? '' : 'es'}',
                    style: const TextStyle(color: Color(0xFFB7D0DF)),
                  ),
                ],
              ),
            ),
            const SizedBox(width: 12),
            Container(
              width: 42,
              height: 42,
              decoration: BoxDecoration(
                color: Colors.white.withOpacity(0.08),
                borderRadius: BorderRadius.circular(999),
              ),
              child: const Icon(Icons.chevron_right),
            ),
          ],
        ),
      ),
    );
  }
}

class _CompetitionCard extends StatelessWidget {
  const _CompetitionCard({
    required this.backendUrl,
    required this.competition,
    required this.onTap,
  });

  final String backendUrl;
  final CompetitionCatalog competition;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    return InkWell(
      onTap: onTap,
      borderRadius: BorderRadius.circular(28),
      child: Ink(
        padding: const EdgeInsets.all(18),
        decoration: BoxDecoration(
          color: const Color(0xFF0B1A25),
          borderRadius: BorderRadius.circular(28),
          border: Border.all(color: Colors.white.withOpacity(0.06)),
        ),
        child: Row(
          children: [
            _NetworkLogo(
              url: competition.logo,
              backendUrl: backendUrl,
              size: 50,
              fallbackIcon: competition.type == 'cup' ? Icons.emoji_events : Icons.shield,
            ),
            const SizedBox(width: 14),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    competition.name,
                    style: const TextStyle(fontSize: 20, fontWeight: FontWeight.w800),
                  ),
                  const SizedBox(height: 4),
                  Text(
                    '${competition.type == 'cup' ? 'Cup' : 'League'}  •  ${competition.matches.length} match${competition.matches.length == 1 ? '' : 'es'}',
                    style: const TextStyle(color: Color(0xFF95AFC3)),
                  ),
                ],
              ),
            ),
            const SizedBox(width: 12),
            const Icon(Icons.chevron_right, color: Color(0xFF95AFC3)),
          ],
        ),
      ),
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
  static const String _defaultLogoUrl = 'https://via.placeholder.com/50';

  @override
  Widget build(BuildContext context) {
    final logoUrl = url.trim().isEmpty ? _defaultLogoUrl : url;
    final resolvedUrl = resolveUrl(logoUrl, baseUrl: backendUrl);
    return Container(
      width: size,
      height: size,
      decoration: BoxDecoration(
        color: const Color(0xFF112737),
        borderRadius: BorderRadius.circular(size / 2),
      ),
      child: ClipRRect(
        borderRadius: BorderRadius.circular(size / 2),
        child: Image.network(
          resolvedUrl,
          fit: BoxFit.cover,
          errorBuilder: (_, __, ___) => Icon(Icons.tv, color: const Color(0xFFB6D4E3)),
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
    if (positions.isEmpty) {
      return;
    }
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
        : widget.match.competitionName;
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
              aspectRatio: 16 / 9,
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

String _displayDateTime(String value) {
  if (value.isEmpty) return '-';
  final parsed = DateTime.tryParse(value);
  if (parsed == null) return value;
  final local = parsed.toLocal();
  final month = local.month.toString().padLeft(2, '0');
  final day = local.day.toString().padLeft(2, '0');
  final hour = local.hour.toString().padLeft(2, '0');
  final minute = local.minute.toString().padLeft(2, '0');
  return '${local.year}-$month-$day $hour:$minute';
}

Color _parseHexColor(String value, Color fallback) {
  final normalized = value.trim().replaceFirst('#', '');
  if (normalized.length != 6) return fallback;
  final parsed = int.tryParse('FF$normalized', radix: 16);
  return parsed == null ? fallback : Color(parsed);
}
