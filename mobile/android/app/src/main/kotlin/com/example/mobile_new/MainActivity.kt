package com.example.mobile_new

import android.content.pm.PackageManager
import android.net.ConnectivityManager
import android.net.NetworkCapabilities
import android.os.Build
import android.provider.Settings
import android.view.WindowManager
import io.flutter.embedding.android.FlutterActivity
import io.flutter.embedding.engine.FlutterEngine
import io.flutter.plugin.common.EventChannel
import io.flutter.plugin.common.MethodChannel
import java.io.File
import java.security.MessageDigest
import java.util.Locale

class MainActivity : FlutterActivity() {
    companion object {
        private const val METHOD_CHANNEL = "football_streaming/security"
        private const val EVENT_CHANNEL = "football_streaming/security/events"
        private const val EXPECTED_SIGNATURE_SHA256 = ""
    }

    override fun configureFlutterEngine(flutterEngine: FlutterEngine) {
        super.configureFlutterEngine(flutterEngine)

        MethodChannel(flutterEngine.dartExecutor.binaryMessenger, METHOD_CHANNEL)
            .setMethodCallHandler { call, result ->
                when (call.method) {
                    "getSecuritySnapshot" -> result.success(
                        mapOf(
                            "deviceFingerprint" to deviceFingerprint(),
                            "secureDevice" to !isRooted(),
                            "vpnActive" to isVpnActive(),
                            "appSignatureValid" to isSignatureValid(),
                            "preferredCountry" to (Locale.getDefault().country ?: ""),
                        )
                    )
                    "enableSecurePlayback" -> {
                        window.addFlags(WindowManager.LayoutParams.FLAG_SECURE)
                        result.success(null)
                    }
                    "disableSecurePlayback" -> {
                        window.clearFlags(WindowManager.LayoutParams.FLAG_SECURE)
                        result.success(null)
                    }
                    else -> result.notImplemented()
                }
            }

        EventChannel(flutterEngine.dartExecutor.binaryMessenger, EVENT_CHANNEL)
            .setStreamHandler(object : EventChannel.StreamHandler {
                override fun onListen(arguments: Any?, events: EventChannel.EventSink?) {
                    // Android uses FLAG_SECURE for prevention, so no active event stream is emitted here.
                }

                override fun onCancel(arguments: Any?) {
                }
            })
    }

    private fun deviceFingerprint(): String {
        val androidId = Settings.Secure.getString(contentResolver, Settings.Secure.ANDROID_ID) ?: "unknown"
        return sha256("$androidId|$packageName|${signatureHash()}")
    }

    private fun isSignatureValid(): Boolean {
        val current = signatureHash()
        return EXPECTED_SIGNATURE_SHA256.isEmpty() || EXPECTED_SIGNATURE_SHA256.equals(current, ignoreCase = true)
    }

    private fun signatureHash(): String {
        return try {
            val info = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.P) {
                packageManager.getPackageInfo(packageName, PackageManager.GET_SIGNING_CERTIFICATES)
            } else {
                @Suppress("DEPRECATION")
                packageManager.getPackageInfo(packageName, PackageManager.GET_SIGNATURES)
            }
            val signatureBytes = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.P) {
                info.signingInfo?.apkContentsSigners?.firstOrNull()?.toByteArray()
            } else {
                @Suppress("DEPRECATION")
                info.signatures?.firstOrNull()?.toByteArray()
            } ?: ByteArray(0)
            sha256(signatureBytes)
        } catch (_: Exception) {
            ""
        }
    }

    private fun isVpnActive(): Boolean {
        val manager = getSystemService(CONNECTIVITY_SERVICE) as? ConnectivityManager ?: return false
        val capabilities = manager.getNetworkCapabilities(manager.activeNetwork) ?: return false
        return capabilities.hasTransport(NetworkCapabilities.TRANSPORT_VPN)
    }

    private fun isRooted(): Boolean {
        val tags = Build.TAGS ?: ""
        if (tags.contains("test-keys")) return true

        val suspiciousPaths = listOf(
            "/system/app/Superuser.apk",
            "/sbin/su",
            "/system/bin/su",
            "/system/xbin/su",
            "/data/local/xbin/su",
            "/data/local/bin/su",
            "/system/sd/xbin/su",
            "/system/bin/failsafe/su",
            "/data/local/su",
        )
        if (suspiciousPaths.any { File(it).exists() }) return true
        return false
    }

    private fun sha256(input: String): String = sha256(input.toByteArray())

    private fun sha256(input: ByteArray): String {
        val digest = MessageDigest.getInstance("SHA-256").digest(input)
        return digest.joinToString("") { "%02x".format(it) }
    }
}
