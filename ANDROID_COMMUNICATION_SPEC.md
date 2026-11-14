# SENTINEL AI: Android Kiosk to Laptop Core Communication Specification
> **For Android Studio's Gemini & Android Engineers**  
> *Target Host Server: Lenovo Laptop (AMD Ryzen 7 250, 32GB DDR5, NVIDIA RTX 5060 8GB VRAM)*  
> *Target Client Device: Android Phone running in Kiosk / Smart Doorbell mode*

---

## 1. System Architecture & Connection Modes

The Android Doorbell Phone operates as an edge sensor/display node and communicates with the host laptop through **two distinct protocols**:

```
+-----------------------------------------------------------------------------------------+
|                               ANDROID DOORBELL PHONE (KIOSK)                            |
|                                                                                         |
|  [Hardware Sensors & I/O]                                                               |
|  - Camera2 / CameraX -> MediaCodec (H.264 Hardware Encoder 30 FPS)                      |
|  - AudioRecord (16kHz 16-bit Mono PCM Mic Stream)                                       |
|  - AudioTrack (16kHz 16-bit Mono Speaker Playback for Two-Way Intercom & Edge-TTS)     |
|  - NotificationListenerService (Captures WhatsApp, SMS, Deliveries)                     |
|  - Fullscreen Kiosk UI (Jetpack Compose / View Binding displaying greetings & notices)  |
+-----------------------------------------------------------------------------------------+
                    |                                                     |
    Channel Multiplexing (TCP Port 9000)                   LAN HTTP / REST (Port 8000)
    (Via USB `adb reverse` OR Direct Wi-Fi LAN)            (Via Wi-Fi LAN IP or USB reverse)
                    ▼                                                     ▼
+-----------------------------------------------------------------------------------------+
|                                SENTINEL LAPTOP CORE HOST                                |
|                        Primary LAN IP: http://10.220.59.55                              |
|                                                                                         |
|  [sbmp_server.py (Port 9000)]                    [FastAPI Server (Port 8000)]           |
|  - 9-Byte Binary Header Demuxer                  - /api/kiosk/discovery (Auto-config)   |
|  - Channel 0x01: PyAV H.264 C-Decoder            - /api/kiosk/ring (HTTP Doorbell Chime)|
|  - Channel 0x02: Mic Audio & Whisper Dispatch    - /api/kiosk/voice-note (WAV upload)   |
|  - Channel 0x03: Notifications & Screen Mirror   - /api/kiosk/telemetry (Battery/Health)|
|  - Channel 0x04: Intercom / TTS Downstream       - /api/kiosk/state (Notices/Siren)     |
|  - Channel 0x05: UI Display State Commands       - /api/faces/enroll-from-camera        |
|  - Channel 0x06: Chimes, Voice Notes, Telemetry  - /ws/kiosk-stream (WebSocket Option)  |
+-----------------------------------------------------------------------------------------+
```

### Connection Modes:
1. **Mode A: USB Tethered (Zero Latency, Auto-Healing Tunnel)**
   - Android connects via USB cable with **USB Debugging** enabled.
   - The laptop runs a background daemon executing `adb reverse tcp:9000 tcp:9000` every 5 seconds.
   - The Android app connects directly to: `localhost:9000` (TCP) and `http://localhost:8000` (HTTP).
2. **Mode B: Wireless Wi-Fi / LAN**
   - Android phone is connected to the same Wi-Fi router.
   - Laptop LAN IP is detected dynamically (e.g. `10.220.59.55`).
   - Android connects to: `10.220.59.55:9000` (TCP) and `http://10.220.59.55:8000` (HTTP).

---

## 2. SBMP (Sentinel Binary Multiplex Protocol) Specification

The SBMP protocol multiplexes video, audio, notifications, and UI states over a single, persistent TCP connection.

### 2.1 The 9-Byte Big-Endian Header
Every single packet sent between Android and the Host must begin with exactly 9 bytes:

```
 0                   1                   2                   3
 0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|  Channel ID   |                 Timestamp (ms)                |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|       Timestamp (cont.)       |         Payload Length        |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|     Payload Length (cont.)    |       Payload Bytes...        |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
```

| Field | Size | Data Type | Description |
|---|---|---|---|
| `channel_id` | 1 Byte | `Byte` (0–255) | Channel identifier constant |
| `timestamp_ms` | 4 Bytes | `Int` (uint32) | `System.currentTimeMillis().toInt()` in big-endian |
| `payload_len` | 4 Bytes | `Int` (uint32) | Exact size of binary payload following the header in bytes |

In Kotlin:
```kotlin
val header = ByteBuffer.allocate(9).apply {
    order(ByteOrder.BIG_ENDIAN)
    put(channelId)
    putInt((System.currentTimeMillis() and 0xFFFFFFFFL).toInt())
    putInt(payload.size)
}.array()
```

---

### 2.2 Channel Directory & Formats

#### Channel `0x01`: Raw H.264 Annex-B Video Stream (Phone -> Host)
- **Content:** H.264 Annex-B NAL units from Android `MediaCodec` (must include SPS/PPS headers and start codes `00 00 00 01` or `00 00 01`).
- **Framerate:** 30 FPS.
- **Resolution:** 1280x720 or 640x360.
- **Host Decoding:** PyAV C-level hardware demuxer into thread-safe `FrameRingBuffer` for 30 FPS display and decoupled RTX 5060 AI inference.
- **Fallback:** Host also accepts direct JPEG byte buffers (`\xff\xd8...`) over this channel.

#### Channel `0x02`: Raw Doorway Mic Audio (Phone -> Host)
- **Content:** Uncompressed 16kHz, 16-bit, Mono PCM audio chunks.
- **Buffer Interval:** Send chunks every 50ms–100ms (1600–3200 bytes per chunk).
- **Host Action:**
  - Streams chunk live to connected homeowner client dashboards for live intercom listening.
  - If in `VOICE_NOTE_RECORDING` state, accumulates bytes into a `.wav` file for GPU Whisper transcription upon `VOICE_NOTE_END`.

#### Channel `0x03`: Phone Screen Mirror & Intercepted Android Notifications (Phone -> Host)
- **Sub-Type A — Intercepted OS Notification (JSON):**
  If payload bytes begin with `{` (ASCII `0x7B`), parse as UTF-8 JSON:
  ```json
  {
    "packageName": "com.whatsapp",
    "title": "Amazon Courier",
    "text": "Your package is arriving at the front door.",
    "postTime": 1729182390123
  }
  ```
  *Host Action:* Inserts notification into SQLite and pushes real-time toast alert to the Homeowner Dashboard.
- **Sub-Type B — Display Mirror Snapshot (Binary JPEG):**
  If payload is binary image bytes, host updates `kiosk_screen_preview.jpg` so the homeowner sees the phone screen live in the dashboard.

#### Channel `0x04`: Audio Stream from Host to Phone Speaker (Host -> Phone)
- **Content:** 16kHz, 16-bit, Mono PCM audio chunks.
- **Source:** Two-way intercom microphone audio from the homeowner or synthesized neural Edge-TTS voice greetings.
- **Android Action:** Write directly into `AudioTrack.write(pcmBytes, 0, pcmBytes.size)`.

#### Channel `0x05`: Phone UI State & Remote Control (Host -> Phone)
- **Content:** UTF-8 JSON dispatched from host to update phone kiosk display:
  - **Greeting for Recognized Resident:**
    ```json
    {
      "action": "DISPLAY_GREETING",
      "title": "WELCOME HOME",
      "name": "Dushyant Sharma",
      "role": "Family",
      "duration_sec": 6
    }
    ```
  - **Security Warning for Loitering Unknown Person:**
    ```json
    {
      "action": "DISPLAY_WARNING",
      "title": "SECURITY ALERT",
      "message": "Recording in Progress. Property Security Active.",
      "duration_sec": 8
    }
    ```
  - **Homeowner Custom Notice:**
    ```json
    {
      "action": "DISPLAY_NOTICE",
      "title": "HOMEOWNER NOTICE",
      "message": "Please leave packages on the porch table.",
      "duration_sec": 30
    }
    ```
  - **Camera Switch:**
    ```json
    {
      "action": "SWITCH_CAMERA",
      "lens": "front" // or "back"
    }
    ```
  - **Emergency Siren:**
    ```json
    {
      "action": "TRIGGER_SIREN",
      "state": true // or false
    }
    ```

#### Channel `0x06`: Triggers & Telemetry (Phone -> Host)
- **Content:** UTF-8 JSON payloads:
  - **Doorbell Ring Pressed:**
    ```json
    { "event": "DOORBELL_RING" }
    ```
  - **Voice Note Recording Started (Button Pressed):**
    ```json
    { "event": "VOICE_NOTE_START" }
    ```
  - **Voice Note Recording Stopped (Button Released):**
    ```json
    { "event": "VOICE_NOTE_END" }
    ```
  - **Periodic Battery / Device Telemetry (every 10–30s):**
    ```json
    {
      "event": "TELEMETRY",
      "battery_pct": 88,
      "is_charging": true,
      "temp_c": 31.5
    }
    ```

---

## 3. LAN HTTP REST API Endpoints (Port 8000)

If your Android architecture uses Retrofit/OkHttp instead of or alongside raw TCP sockets, the host exposes these dedicated REST endpoints:

### 3.1 `GET /api/kiosk/discovery`
Call on Android app launch to auto-discover host endpoints:
```json
{
  "server_name": "Sentinel Laptop Core",
  "lan_ip": "10.220.59.55",
  "http_port": 8000,
  "sbmp_port": 9000,
  "ws_client_url": "ws://10.220.59.55:8000/ws/client-stream",
  "ws_kiosk_url": "ws://10.220.59.55:8000/ws/kiosk-stream",
  "endpoints": {
    "ring": "http://10.220.59.55:8000/api/kiosk/ring",
    "voice_note": "http://10.220.59.55:8000/api/kiosk/voice-note",
    "telemetry": "http://10.220.59.55:8000/api/kiosk/telemetry",
    "state": "http://10.220.59.55:8000/api/kiosk/state",
    "screen_mirror": "http://10.220.59.55:8000/api/kiosk/screen-mirror",
    "enroll_face": "http://10.220.59.55:8000/api/faces/enroll-from-camera"
  }
}
```

### 3.2 `POST /api/kiosk/ring`
Trigger doorbell chime over HTTP:
```json
POST http://10.220.59.55:8000/api/kiosk/ring
Content-Type: application/json

{
  "message": "Visitor rang physical doorbell button",
  "visitor_photo_base64": "data:image/jpeg;base64,/9j/..." // Optional Camera snapshot
}
```

### 3.3 `POST /api/kiosk/telemetry`
```json
POST http://10.220.59.55:8000/api/kiosk/telemetry
Content-Type: application/json

{
  "battery_pct": 91,
  "is_charging": true,
  "temp_c": 30.2,
  "wifi_rssi": -55
}
```

### 3.4 `GET /api/kiosk/state`
Poll active notices and camera directives:
```json
GET http://10.220.59.55:8000/api/kiosk/state
Response:
{
  "notice_text": "Please leave packages at the porch table.",
  "siren_active": false,
  "camera_lens": "back",
  "active_greeting": null
}
```

### 3.5 `POST /api/kiosk/voice-note` (Multipart Form)
- `file`: Audio file (`.wav`, `.m4a`, or `.aac`)
- `duration_sec`: Float (e.g. `4.5`)
- `sender_name`: String (e.g. `"Courier"`)
*Host runs Faster-Whisper on RTX 5060, saves transcript, and alerts dashboard.*

---

## 4. Camera-Based Face Enrollment from Android

The Android Kiosk app can enroll resident faces directly from its camera feed without needing file upload forms:

### Endpoint: `POST /api/faces/enroll-from-camera`
```http
POST http://10.220.59.55:8000/api/faces/enroll-from-camera
Content-Type: application/json

{
  "name": "Dushyant Sharma",
  "role": "Family",
  "custom_greeting": "Welcome home Dushyant! Alarm disarmed.",
  "photo_base64": "data:image/jpeg;base64,/9j/4AAQSkZJRgABAQAAAQABAAD...",
  "use_doorbell_stream": false
}
```
*Note: If `use_doorbell_stream` is `true`, the host captures whoever is standing in front of the active H.264 stream at that exact instant without needing `photo_base64`.*

---

## 5. Complete Kotlin Implementation Reference

### 5.1 SBMP Network Client (`SbmpClient.kt`)
```kotlin
package com.sentinel.doorbell.network

import android.util.Log
import kotlinx.coroutines.*
import java.io.InputStream
import java.io.OutputStream
import java.net.Socket
import java.nio.ByteBuffer
import java.nio.ByteOrder

class SbmpClient(
    private val host: String = "127.0.0.1",
    private val port: Int = 9000,
    private val onAudioReceived: (ByteArray) -> Unit,
    private val onUiCommandReceived: (String) -> Unit
) {
    private var socket: Socket? = null
    private var outputStream: OutputStream? = null
    private var inputStream: InputStream? = null
    private var isRunning = false
    private val scope = CoroutineScope(Dispatchers.IO + SupervisorJob())

    fun connect() {
        scope.launch {
            while (isActive) {
                try {
                    Log.i("SbmpClient", "Connecting to SBMP server at $host:$port...")
                    socket = Socket(host, port).apply {
                        tcpNoDelay = true
                        soTimeout = 0 // Infinite read timeout
                    }
                    outputStream = socket!!.getOutputStream()
                    inputStream = socket!!.getInputStream()
                    isRunning = true
                    Log.i("SbmpClient", "SBMP Socket Connected!")

                    readIncomingLoop()
                } catch (e: Exception) {
                    Log.w("SbmpClient", "Connection error: ${e.message}. Reconnecting in 3s...")
                    closeConnection()
                    delay(3000)
                }
            }
        }
    }

    private fun readIncomingLoop() {
        val headerBuffer = ByteArray(9)
        while (isRunning && inputStream != null) {
            readFully(headerBuffer, 9)
            val byteBuf = ByteBuffer.wrap(headerBuffer).order(ByteOrder.BIG_ENDIAN)
            val channelId = byteBuf.get().toInt() and 0xFF
            val timestampMs = byteBuf.int.toLong() and 0xFFFFFFFFL
            val payloadLen = byteBuf.int

            val payload = ByteArray(payloadLen)
            readFully(payload, payloadLen)

            when (channelId) {
                0x04 -> onAudioReceived(payload) // 16kHz PCM audio chunk to speaker
                0x05 -> {
                    val jsonStr = String(payload, Charsets.UTF_8)
                    onUiCommandReceived(jsonStr) // UI Greeting, Notice, Camera Switch, Siren
                }
                else -> Log.d("SbmpClient", "Received channel 0x${channelId.toString(16)}")
            }
        }
    }

    private fun readFully(buffer: ByteArray, length: Int) {
        var totalRead = 0
        while (totalRead < length) {
            val bytesRead = inputStream?.read(buffer, totalRead, length - totalRead) ?: -1
            if (bytesRead == -1) throw Exception("Stream closed unexpectedly")
            totalRead += bytesRead
        }
    }

    @Synchronized
    fun sendPacket(channelId: Byte, payload: ByteArray) {
        if (!isRunning || outputStream == null) return
        try {
            val header = ByteBuffer.allocate(9).apply {
                order(ByteOrder.BIG_ENDIAN)
                put(channelId)
                putInt((System.currentTimeMillis() and 0xFFFFFFFFL).toInt())
                putInt(payload.size)
            }.array()

            outputStream?.write(header)
            outputStream?.write(payload)
            outputStream?.flush()
        } catch (e: Exception) {
            Log.e("SbmpClient", "Send failed: ${e.message}")
            closeConnection()
        }
    }

    // Convenience senders
    fun sendVideoFrame(h264NalBytes: ByteArray) = sendPacket(0x01.toByte(), h264NalBytes)
    fun sendAudioChunk(pcm16Bytes: ByteArray) = sendPacket(0x02.toByte(), pcm16Bytes)
    fun sendScreenMirror(jpegBytes: ByteArray) = sendPacket(0x03.toByte(), jpegBytes)
    fun sendNotification(jsonString: String) = sendPacket(0x03.toByte(), jsonString.toByteArray(Charsets.UTF_8))
    fun sendTrigger(jsonString: String) = sendPacket(0x06.toByte(), jsonString.toByteArray(Charsets.UTF_8))

    private fun closeConnection() {
        isRunning = false
        try { socket?.close() } catch (ignored: Exception) {}
        socket = null
        outputStream = null
        inputStream = null
    }

    fun disconnect() {
        scope.cancel()
        closeConnection()
    }
}
```

---

### 5.2 16kHz PCM Audio Streamer & Player (`AudioController.kt`)
```kotlin
package com.sentinel.doorbell.audio

import android.annotation.SuppressLint
import android.media.*
import kotlinx.coroutines.*

class AudioController(private val onPcmChunkRecorded: (ByteArray) -> Unit) {
    private val sampleRate = 16000
    private var audioRecord: AudioRecord? = null
    private var audioTrack: AudioTrack? = null
    private var isRecording = false
    private val scope = CoroutineScope(Dispatchers.IO + SupervisorJob())

    init {
        initSpeakerPlayer()
    }

    private fun initSpeakerPlayer() {
        val minBufSize = AudioTrack.getMinBufferSize(
            sampleRate,
            AudioFormat.CHANNEL_OUT_MONO,
            AudioFormat.ENCODING_PCM_16BIT
        )
        audioTrack = AudioTrack.Builder()
            .setAudioAttributes(
                AudioAttributes.Builder()
                    .setUsage(AudioAttributes.USAGE_VOICE_COMMUNICATION)
                    .setContentType(AudioAttributes.CONTENT_TYPE_SPEECH)
                    .build()
            )
            .setAudioFormat(
                AudioFormat.Builder()
                    .setEncoding(AudioFormat.ENCODING_PCM_16BIT)
                    .setSampleRate(sampleRate)
                    .setChannelMask(AudioFormat.CHANNEL_OUT_MONO)
                    .build()
            )
            .setBufferSizeInBytes(minBufSize * 2)
            .setTransferMode(AudioTrack.MODE_STREAM)
            .build()

        audioTrack?.play()
    }

    @SuppressLint("MissingPermission")
    fun startMicrophoneRecording() {
        val bufferSize = AudioRecord.getMinBufferSize(
            sampleRate,
            AudioFormat.CHANNEL_IN_MONO,
            AudioFormat.ENCODING_PCM_16BIT
        )

        audioRecord = AudioRecord(
            MediaRecorder.AudioSource.VOICE_COMMUNICATION,
            sampleRate,
            AudioFormat.CHANNEL_IN_MONO,
            AudioFormat.ENCODING_PCM_16BIT,
            bufferSize * 2
        )

        isRecording = true
        audioRecord?.startRecording()

        scope.launch {
            val chunk = ByteArray(1600) // 100ms at 16kHz 16-bit Mono (16000 * 2 * 0.1 / 2 = 1600 bytes)
            while (isRecording && audioRecord != null) {
                val read = audioRecord!!.read(chunk, 0, chunk.size)
                if (read > 0) {
                    onPcmChunkRecorded(chunk.copyOf(read))
                }
            }
        }
    }

    fun stopMicrophoneRecording() {
        isRecording = false
        audioRecord?.stop()
        audioRecord?.release()
        audioRecord = null
    }

    // Playback Channel 0x04 audio chunks coming from homeowner intercom or Edge-TTS
    fun playSpeakerAudioChunk(pcmBytes: ByteArray) {
        audioTrack?.write(pcmBytes, 0, pcmBytes.size)
    }

    fun release() {
        stopMicrophoneRecording()
        audioTrack?.stop()
        audioTrack?.release()
        audioTrack = null
        scope.cancel()
    }
}
```

---

### 5.3 Notification Interceptor Service (`NotificationService.kt`)
Intercepts notifications from apps like WhatsApp, SMS, or delivery agents and forwards them to the Host via Channel `0x03`:

```kotlin
package com.sentinel.doorbell.service

import android.service.notification.NotificationListenerService
import android.service.notification.StatusBarNotification
import org.json.JSONObject

class NotificationInterceptorService : NotificationListenerService() {
    companion object {
        var onNotificationIntercepted: ((String) -> Unit)? = null
    }

    override fun onNotificationPosted(sbn: StatusBarNotification?) {
        super.onNotificationPosted(sbn)
        if (sbn == null) return

        val extras = sbn.notification.extras
        val title = extras.getString("android.title") ?: ""
        val text = extras.getCharSequence("android.text")?.toString() ?: ""
        val packageName = sbn.packageName ?: "unknown"

        if (title.isBlank() && text.isBlank()) return

        val json = JSONObject().apply {
            put("packageName", packageName)
            put("title", title)
            put("text", text)
            put("postTime", sbn.postTime)
        }

        // Forward to SBMP Channel 0x03
        onNotificationIntercepted?.invoke(json.toString())
    }
}
```

---

### 5.4 Camera Face Enrollment Helper (`FaceEnrollmentHelper.kt`)
Enrolls a face by capturing a photo via Android camera and submitting to `/api/faces/enroll-from-camera`:

```kotlin
package com.sentinel.doorbell.enrollment

import android.graphics.Bitmap
import android.util.Base64
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONObject
import java.io.ByteArrayOutputStream

object FaceEnrollmentHelper {
    private val client = OkHttpClient()

    suspend fun enrollFace(
        serverBaseUrl: String, // e.g. "http://10.220.59.55:8000"
        name: String,
        role: String,
        customGreeting: String?,
        photoBitmap: Bitmap
    ): Result<String> = withContext(Dispatchers.IO) {
        try {
            // 1. Convert bitmap to JPEG Base64
            val stream = ByteArrayOutputStream()
            photoBitmap.compress(Bitmap.CompressFormat.JPEG, 85, stream)
            val base64Image = "data:image/jpeg;base64," + Base64.encodeToString(stream.toByteArray(), Base64.NO_WRAP)

            // 2. Build JSON payload
            val json = JSONObject().apply {
                put("name", name)
                put("role", role)
                put("custom_greeting", customGreeting)
                put("photo_base64", base64Image)
                put("use_doorbell_stream", false)
            }

            // 3. Post to endpoint
            val request = Request.Builder()
                .url("$serverBaseUrl/api/faces/enroll-from-camera")
                .post(json.toString().toRequestBody("application/json".toMediaType()))
                .build()

            val response = client.newCall(request).execute()
            if (response.isSuccessful) {
                Result.success(response.body?.string() ?: "Success")
            } else {
                Result.failure(Exception("HTTP ${response.code}: ${response.body?.string()}"))
            }
        } catch (e: Exception) {
            Result.failure(e)
        }
    }
}
```

---

## 6. AndroidManifest.xml & Network Configuration

Add the required permissions in `AndroidManifest.xml`:

```xml
<manifest xmlns:android="http://schemas.android.com/apk/res/android">

    <!-- Network & Hardware Permissions -->
    <uses-permission android:name="android.permission.INTERNET" />
    <uses-permission android:name="android.permission.ACCESS_NETWORK_STATE" />
    <uses-permission android:name="android.permission.RECORD_AUDIO" />
    <uses-permission android:name="android.permission.CAMERA" />
    <uses-feature android:name="android.hardware.camera" />
    <uses-feature android:name="android.hardware.camera.autofocus" android:required="false" />

    <application
        android:allowBackup="true"
        android:icon="@mipmap/ic_launcher"
        android:label="Sentinel Kiosk"
        android:usesCleartextTraffic="true" <!-- Required for HTTP/WS LAN communication -->
        android:theme="@style/Theme.Material3.Dark.NoActionBar">

        <!-- Notification Listener Service -->
        <service
            android:name=".service.NotificationInterceptorService"
            android:label="Sentinel Notification Interceptor"
            android:permission="android.permission.BIND_NOTIFICATION_LISTENER_SERVICE"
            android:exported="true">
            <intent-filter>
                <action android:name="android.service.notification.NotificationListenerService" />
            </intent-filter>
        </service>

    </application>
</manifest>
```

---

## 7. Quick Troubleshooting Checklist for Android Gemini

1. **`Connection refused` on `localhost:9000`?**
   - Ensure the phone is connected via USB and USB Debugging is allowed.
   - Verify that the laptop's `adb_tunnel_manager` has executed `adb reverse tcp:9000 tcp:9000`.
   - Alternatively, connect directly to the Wi-Fi LAN IP (e.g. `10.220.59.55:9000`).
2. **`CLEARTEXT_COMMUNICATION_NOT_PERMITTED`?**
   - Add `android:usesCleartextTraffic="true"` to `<application>` in `AndroidManifest.xml`.
3. **No video rendering on host?**
   - Verify that `MediaCodec` generates Annex-B NAL units with start codes `0x00 0x00 0x00 0x01`.
   - Ensure the first packet includes SPS (type 7) and PPS (type 8).
4. **Speaker audio distorted?**
   - Host sends strictly **16kHz, 16-bit Mono PCM**. Ensure your `AudioTrack` is configured with `16000Hz`, `CHANNEL_OUT_MONO`, and `ENCODING_PCM_16BIT`.
