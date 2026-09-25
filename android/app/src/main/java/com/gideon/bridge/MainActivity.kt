package com.gideon.bridge

import android.Manifest
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Build
import android.os.Bundle
import android.widget.Button
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.TextView
import androidx.appcompat.app.AppCompatActivity
import androidx.core.app.ActivityCompat
import androidx.core.content.ContextCompat
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.Inet4Address
import java.net.NetworkInterface
import java.net.URL
import java.security.KeyPairGenerator
import java.security.KeyStore
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.Base64
import kotlin.concurrent.thread

class MainActivity : AppCompatActivity() {
    private lateinit var status: TextView
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val layout = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL; setPadding(36, 36, 36, 36) }
        val host = EditText(this).apply { hint = "Laptop URL, e.g. http://100.64.0.2:8766" }
        val code = EditText(this).apply { hint = "6-digit pairing code" }
        status = TextView(this).apply { text = if (getPreferences().contains("encrypted_token")) "Paired. Start the bridge after granting permissions." else "Not paired." }
        val pair = Button(this).apply { text = "Pair with laptop"; setOnClickListener { pair(host.text.toString(), code.text.toString()) } }
        val start = Button(this).apply { text = "Start bridge"; setOnClickListener { requestAndStart() } }
        val stop = Button(this).apply { text = "Stop bridge"; setOnClickListener { stopService(Intent(this@MainActivity, BridgeService::class.java)); status.text = "Bridge stopped." } }
        listOf(host, code, pair, start, stop, status).forEach(layout::addView); setContentView(layout)
    }

    private fun getPreferences() = getSharedPreferences("gideon", MODE_PRIVATE)
    private fun requestAndStart() {
        val permissions = mutableListOf(Manifest.permission.CAMERA)
        if (Build.VERSION.SDK_INT >= 33) permissions += Manifest.permission.POST_NOTIFICATIONS
        val missing = permissions.filter { ContextCompat.checkSelfPermission(this, it) != PackageManager.PERMISSION_GRANTED }
        if (missing.isNotEmpty()) ActivityCompat.requestPermissions(this, missing.toTypedArray(), 10)
        else startBridge()
    }
    override fun onRequestPermissionsResult(requestCode: Int, permissions: Array<out String>, results: IntArray) {
        super.onRequestPermissionsResult(requestCode, permissions, results)
        if (requestCode == 10 && results.all { it == PackageManager.PERMISSION_GRANTED }) startBridge()
        else status.text = "Camera and notification permissions are required for requested bridge actions."
    }
    private fun startBridge() { ContextCompat.startForegroundService(this, Intent(this, BridgeService::class.java)); status.text = "Bridge running on port 8767." }
    private fun localIp(): String = NetworkInterface.getNetworkInterfaces().toList().flatMap { it.inetAddresses.toList() }
        .firstOrNull { !it.isLoopbackAddress && it is Inet4Address }?.hostAddress ?: "127.0.0.1"
    private fun pairingPublicKey(): String {
        val store = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
        if (!store.containsAlias("gideon-pairing")) {
            val generator = KeyPairGenerator.getInstance(KeyProperties.KEY_ALGORITHM_RSA, "AndroidKeyStore")
            generator.initialize(KeyGenParameterSpec.Builder("gideon-pairing", KeyProperties.PURPOSE_DECRYPT)
                .setDigests(KeyProperties.DIGEST_SHA256, KeyProperties.DIGEST_SHA512)
                .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_RSA_OAEP).build())
            generator.generateKeyPair()
        }
        return Base64.encodeToString(store.getCertificate("gideon-pairing").publicKey.encoded, Base64.NO_WRAP)
    }
    private fun pair(base: String, code: String) = thread {
        try {
            val connection = URL(base.trimEnd('/') + "/v1/pair").openConnection() as HttpURLConnection
            connection.requestMethod = "POST"; connection.doOutput = true; connection.setRequestProperty("Content-Type", "application/json")
            val payload = JSONObject().put("code", code).put("name", Build.MODEL).put("base_url", "http://${localIp()}:8767").put("public_key", pairingPublicKey()).toString()
            connection.outputStream.use { it.write(payload.toByteArray()) }
            val result = JSONObject(connection.inputStream.bufferedReader().readText())
            getPreferences().edit().putString("encrypted_token", result.getString("encrypted_token")).apply()
            runOnUiThread { status.text = "Paired successfully. Tap Start bridge." }
        } catch (e: Exception) { runOnUiThread { status.text = "Pairing failed: ${e.message}" } }
    }
}
