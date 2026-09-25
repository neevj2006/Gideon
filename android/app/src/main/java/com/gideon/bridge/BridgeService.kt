package com.gideon.bridge

import android.app.*
import android.content.Context
import android.content.Intent
import android.hardware.camera2.CameraCharacteristics
import android.hardware.camera2.CameraManager
import android.media.AudioAttributes
import android.media.RingtoneManager
import android.os.BatteryManager
import android.os.Build
import android.os.IBinder
import android.provider.Settings
import androidx.core.app.NotificationCompat
import fi.iki.elonen.NanoHTTPD
import org.json.JSONObject
import java.net.URI
import java.security.MessageDigest
import java.security.KeyStore
import android.util.Base64
import javax.crypto.Cipher
import javax.crypto.Mac
import javax.crypto.spec.SecretKeySpec
import kotlin.concurrent.thread

class BridgeService : Service() {
    private var server: BridgeServer? = null
    private lateinit var camera: CameraActions
    override fun onCreate() {
        super.onCreate(); createChannel(); camera = CameraActions(this)
        startForeground(1, NotificationCompat.Builder(this, "bridge").setSmallIcon(android.R.drawable.ic_menu_camera)
            .setContentTitle("Gideon Bridge").setContentText("Listening for authenticated laptop commands").setOngoing(true).build())
        server = BridgeServer(this, camera).also { it.start(NanoHTTPD.SOCKET_READ_TIMEOUT, false) }
    }
    override fun onDestroy() { server?.stop(); camera.stopVideo(); super.onDestroy() }
    override fun onBind(intent: Intent?): IBinder? = null
    private fun createChannel() { if (Build.VERSION.SDK_INT >= 26) getSystemService(NotificationManager::class.java).createNotificationChannel(NotificationChannel("bridge", "Gideon Bridge", NotificationManager.IMPORTANCE_LOW)) }
}

class BridgeServer(private val context: Context, private val camera: CameraActions) : NanoHTTPD(8767) {
    private val usedNonces = LinkedHashMap<String, Long>()
    override fun serve(session: IHTTPSession): Response {
        if (session.method != Method.POST || session.uri != "/v1/action") return newFixedLengthResponse(Response.Status.NOT_FOUND, "application/json", "{}")
        val files = mutableMapOf<String, String>(); session.parseBody(files); val body = files["postData"] ?: "{}"
        if (!authenticate(session, body.toByteArray())) return newFixedLengthResponse(Response.Status.UNAUTHORIZED, "application/json", "{\"error\":\"unauthorized\"}")
        return try { val request = JSONObject(body); val message = action(request.getString("action"), request.optJSONObject("args") ?: JSONObject()); newFixedLengthResponse(Response.Status.OK, "application/json", JSONObject().put("message", message).toString()) }
        catch (e: Exception) { newFixedLengthResponse(Response.Status.INTERNAL_ERROR, "application/json", JSONObject().put("error", e.message).toString()) }
    }
    private fun authenticate(session: IHTTPSession, body: ByteArray): Boolean {
        val encrypted = context.getSharedPreferences("gideon", Context.MODE_PRIVATE).getString("encrypted_token", null) ?: return false
        val store = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
        val privateKey = store.getKey("gideon-pairing", null) ?: return false
        val cipher = Cipher.getInstance("RSA/ECB/OAEPWithSHA-256AndMGF1Padding").apply { init(Cipher.DECRYPT_MODE, privateKey) }
        val token = String(cipher.doFinal(Base64.decode(encrypted, Base64.NO_WRAP)))
        val timestamp = session.headers["x-gideon-time"] ?: return false; val nonce = session.headers["x-gideon-nonce"] ?: return false
        val received = session.headers["x-gideon-signature"] ?: return false
        if (kotlin.math.abs(System.currentTimeMillis() / 1000 - timestamp.toLongOrNull().orZero()) > 60) return false
        synchronized(usedNonces) { val now = System.currentTimeMillis(); usedNonces.entries.removeIf { now - it.value > 120000 }; if (usedNonces.containsKey(nonce)) return false; usedNonces[nonce] = now }
        val mac = Mac.getInstance("HmacSHA256"); mac.init(SecretKeySpec(token.toByteArray(), "HmacSHA256"))
        val expected = mac.doFinal(timestamp.toByteArray() + ".".toByteArray() + nonce.toByteArray() + ".".toByteArray() + body).joinToString("") { "%02x".format(it) }
        return MessageDigest.isEqual(expected.toByteArray(), received.toByteArray())
    }
    private fun Long?.orZero() = this ?: 0L
    private fun action(action: String, args: JSONObject): String = when (action) {
        "status" -> { val battery = context.getSystemService(BatteryManager::class.java); val level = battery.getIntProperty(BatteryManager.BATTERY_PROPERTY_CAPACITY); val charging = battery.isCharging; "Phone battery is $level percent, charging: $charging." }
        "ring" -> { val uri = RingtoneManager.getDefaultUri(RingtoneManager.TYPE_RINGTONE); RingtoneManager.getRingtone(context, uri).play(); "Phone is ringing." }
        "flashlight" -> { camera.flashlight(args.optBoolean("enabled")); "Flashlight updated." }
        "photo" -> { camera.photo(args.optString("camera", "back")); "Photo captured in the app's private media folder." }
        "video_start" -> { camera.startVideo(args.optString("camera", "back")); "Silent video recording started." }
        "video_stop" -> { camera.stopVideo(); "Silent video recording stopped." }
        "notification" -> { notify(args.optString("title", "Gideon"), args.optString("message")); "Notification shown." }
        "alarm_set" -> { schedule(args.optString("text"), true); "Alarm set." }
        "alarm_cancel" -> { cancelSchedule(true); "Alarm canceled." }
        "timer_set" -> { schedule(args.optString("text"), false); "Phone timer set." }
        "timer_cancel" -> { cancelSchedule(false); "Phone timer canceled." }
        "open" -> { openTarget(args.getString("target")); "Opened approved target." }
        else -> throw IllegalArgumentException("Unsupported action")
    }
    private fun notify(title: String, message: String) { val manager = context.getSystemService(NotificationManager::class.java); manager.notify(20, NotificationCompat.Builder(context, "bridge").setSmallIcon(android.R.drawable.ic_dialog_info).setContentTitle(title).setContentText(message).setPriority(NotificationCompat.PRIORITY_HIGH).build()) }
    private fun seconds(text: String): Long {
        val duration = Regex("(\\d+)\\s*(seconds?|minutes?|hours?)", RegexOption.IGNORE_CASE).find(text)
        if (duration != null) { val n = duration.groupValues[1].toLong(); return n * when { duration.groupValues[2].startsWith("hour", true) -> 3600; duration.groupValues[2].startsWith("minute", true) -> 60; else -> 1 } }
        val clock = Regex("(?:at\\s+)?(\\d{1,2})(?::(\\d{2}))?\\s*(am|pm)", RegexOption.IGNORE_CASE).find(text)
            ?: throw IllegalArgumentException("Duration or clock time required")
        var hour = clock.groupValues[1].toInt() % 12; if (clock.groupValues[3].equals("pm", true)) hour += 12
        val minute = clock.groupValues[2].ifEmpty { "0" }.toInt(); val calendar = java.util.Calendar.getInstance()
        val now = calendar.timeInMillis; calendar.set(java.util.Calendar.HOUR_OF_DAY, hour); calendar.set(java.util.Calendar.MINUTE, minute); calendar.set(java.util.Calendar.SECOND, 0)
        if (calendar.timeInMillis <= now) calendar.add(java.util.Calendar.DAY_OF_YEAR, 1)
        return (calendar.timeInMillis - now) / 1000
    }
    private fun schedule(text: String, alarm: Boolean) { val intent = Intent(context, AlarmReceiver::class.java).putExtra("alarm", alarm); val pending = PendingIntent.getBroadcast(context, if (alarm) 30 else 31, intent, PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE); val manager = context.getSystemService(AlarmManager::class.java); if (Build.VERSION.SDK_INT < 31 || manager.canScheduleExactAlarms()) manager.setExactAndAllowWhileIdle(AlarmManager.RTC_WAKEUP, System.currentTimeMillis() + seconds(text) * 1000, pending) else context.startActivity(Intent(Settings.ACTION_REQUEST_SCHEDULE_EXACT_ALARM).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)) }
    private fun cancelSchedule(alarm: Boolean) { val pending = PendingIntent.getBroadcast(context, if (alarm) 30 else 31, Intent(context, AlarmReceiver::class.java), PendingIntent.FLAG_NO_CREATE or PendingIntent.FLAG_IMMUTABLE); if (pending != null) context.getSystemService(AlarmManager::class.java).cancel(pending) }
    private fun openTarget(target: String) { val approvedApps = mapOf("spotify" to "com.spotify.music", "chrome" to "com.android.chrome", "maps" to "com.google.android.apps.maps"); val intent = if (target.startsWith("https://") || target.startsWith("http://")) Intent(Intent.ACTION_VIEW, android.net.Uri.parse(target)) else context.packageManager.getLaunchIntentForPackage(approvedApps[target.lowercase()] ?: throw IllegalArgumentException("App is not approved")); intent?.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK); context.startActivity(intent) }
}

class AlarmReceiver : android.content.BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) { val uri = if (intent.getBooleanExtra("alarm", false)) RingtoneManager.getDefaultUri(RingtoneManager.TYPE_ALARM) else RingtoneManager.getDefaultUri(RingtoneManager.TYPE_NOTIFICATION); RingtoneManager.getRingtone(context, uri).play() }
}
