/**
 * SENTINEL AI - Autonomous Doorbell Command Center Frontend Controller
 * Multiplexed WebSockets, 30 FPS HUD Video Stream, Web Audio 16kHz Intercom,
 * InsightFace Enrollment, and Real-Time Threat Auditing.
 */

class SentinelClient {
  constructor() {
    this.ws = null;
    this.wsUrl = `ws://${window.location.host}/ws/client-stream`;
    this.reconnectTimer = null;
    
    // Video streaming state
    this.cameraImg = document.getElementById("camera-stream");
    this.kioskImg = document.getElementById("kiosk-screen-img");
    this.currentCameraUrl = null;
    this.currentKioskUrl = null;
    this.fpsCounter = 0;
    this.lastFpsCalc = performance.now();
    
    // Audio Intercom (Web Audio API)
    this.audioCtx = null;
    this.isListening = true;
    this.isTalking = false;
    this.mediaStream = null;
    this.audioWorkletNode = null;
    this.micAudioProcessor = null;

    // Camera Hardware State
    this.currentLens = "back";
    this.sirenActive = false;

    this.initElements();
    this.initEventListeners();
    this.connectWebSocket();
    this.fetchEnrolledFaces();
    this.fetchSecurityEvents();
    this.fetchSystemStatus();
    setInterval(() => this.fetchSystemStatus(), 5000);
    this.startClock();
  }

  initElements() {
    // Buttons & Inputs
    this.btnListen = document.getElementById("btn-listen-mic");
    this.btnTalk = document.getElementById("btn-hold-to-talk");
    this.btnSnapshot = document.getElementById("btn-snapshot");
    this.btnToggleCamera = document.getElementById("btn-toggle-camera");
    this.cameraLensLabel = document.getElementById("camera-lens-label");
    this.btnEmergencySiren = document.getElementById("btn-emergency-siren");
    this.sirenText = document.getElementById("siren-text");
    this.btnFullscreen = document.getElementById("btn-fullscreen");
    
    // Modals
    this.enrollModal = document.getElementById("enroll-modal");
    this.btnOpenEnroll = document.getElementById("btn-open-enroll");
    this.btnCloseEnroll = document.getElementById("enroll-close-btn");
    this.btnCancelEnroll = document.getElementById("enroll-cancel-btn");
    this.enrollForm = document.getElementById("enroll-form");
    this.enrollPhotosInput = document.getElementById("enroll-photos");
    this.filePreviewList = document.getElementById("file-preview-list");
    this.dropZone = document.getElementById("drop-zone");

    this.snapshotModal = document.getElementById("snapshot-modal");
    this.modalCloseBtn = document.getElementById("modal-close-btn");
    this.modalSnapshotImg = document.getElementById("modal-snapshot-img");
    this.modalMeta = document.getElementById("modal-meta");

    // Lists & Containers
    this.facesList = document.getElementById("faces-list");
    this.eventsStream = document.getElementById("events-stream");
    this.eventFilter = document.getElementById("event-filter");
    this.toastContainer = document.getElementById("toast-container");
    this.noticeForm = document.getElementById("notice-form");
    this.noticeInput = document.getElementById("notice-input");
    this.noticeTtsCheckbox = document.getElementById("notice-tts");

    // Telemetry Elements
    this.batteryBadgeText = document.getElementById("phone-battery-text");
    this.phoneTempBadge = document.getElementById("phone-temp-badge");
    this.hudDecoderFps = document.getElementById("hud-decoder-fps");
    this.aiFpsBadge = document.getElementById("ai-fps-badge");
    this.streamStatusText = document.getElementById("stream-status-text");
    this.clockDisplay = document.getElementById("clock-display");
    this.lanIpText = document.getElementById("lan-ip-text");

    // Camera Enrollment Elements
    this.tabCameraBtn = document.getElementById("tab-camera-btn");
    this.tabUploadBtn = document.getElementById("tab-upload-btn");
    this.cameraPanel = document.getElementById("enroll-camera-panel");
    this.uploadPanel = document.getElementById("enroll-upload-panel");
    this.btnSnapDoorbell = document.getElementById("btn-snap-doorbell");
    this.btnStartWebcam = document.getElementById("btn-start-webcam");
    this.btnCaptureWebcam = document.getElementById("btn-capture-webcam");
    this.webcamPreview = document.getElementById("webcam-preview");
    this.webcamCanvas = document.getElementById("webcam-canvas");
    this.cameraCapturedImg = document.getElementById("camera-captured-preview");
    this.cameraPlaceholderMsg = document.getElementById("camera-placeholder-msg");
    this.cameraStatusMsg = document.getElementById("camera-status-msg");

    // Camera Enrollment State
    this.activeEnrollTab = "camera";
    this.webcamStream = null;
    this.capturedCameraBase64 = null;
    this.useDoorbellStreamFlag = false;
  }

  initEventListeners() {
    // Fullscreen toggle
    this.btnFullscreen.addEventListener("click", () => {
      const container = document.getElementById("video-container");
      if (!document.fullscreenElement) {
        container.requestFullscreen().catch(err => console.error(err));
      } else {
        document.exitFullscreen();
      }
    });

    // Camera Snapshot
    this.btnSnapshot.addEventListener("click", () => this.triggerSnapshot());

    // Switch Camera Front / Back
    this.btnToggleCamera.addEventListener("click", () => this.toggleCameraLens());

    // Emergency Siren
    this.btnEmergencySiren.addEventListener("click", () => this.toggleEmergencySiren());

    // Listen Mic Toggle
    this.btnListen.addEventListener("click", () => this.toggleListenMic());

    // Hold-to-Talk Intercom
    this.btnTalk.addEventListener("mousedown", (e) => {
      e.preventDefault();
      this.startTalking();
    });
    window.addEventListener("mouseup", () => {
      if (this.isTalking) this.stopTalking();
    });

    // Spacebar PTT (Push-To-Talk)
    window.addEventListener("keydown", (e) => {
      if (e.code === "Space" && !this.isTalking && document.activeElement.tagName !== "INPUT" && document.activeElement.tagName !== "TEXTAREA") {
        e.preventDefault();
        this.startTalking();
      }
    });
    window.addEventListener("keyup", (e) => {
      if (e.code === "Space" && this.isTalking) {
        e.preventDefault();
        this.stopTalking();
      }
    });

    // Quick TTS Broadcasts
    document.querySelectorAll(".chip-btn").forEach(btn => {
      btn.addEventListener("click", () => {
        const text = btn.dataset.tts;
        if (text) this.sendQuickTts(text);
      });
    });

    // Notice Form
    this.noticeForm.addEventListener("submit", (e) => {
      e.preventDefault();
      const text = this.noticeInput.value.trim();
      const speakTts = this.noticeTtsCheckbox.checked;
      if (text) {
        this.pushKioskNotice(text, speakTts);
        this.noticeInput.value = "";
      }
    });

    // Enroll Modal
    this.btnOpenEnroll.addEventListener("click", () => {
      this.enrollModal.classList.remove("hidden");
      this.switchEnrollTab("camera");
    });
    this.btnCloseEnroll.addEventListener("click", () => {
      this.enrollModal.classList.add("hidden");
      this.stopWebcam();
    });
    this.btnCancelEnroll.addEventListener("click", () => {
      this.enrollModal.classList.add("hidden");
      this.stopWebcam();
    });
    this.modalCloseBtn.addEventListener("click", () => this.snapshotModal.classList.add("hidden"));

    // Camera Enrollment Tab Listeners
    if (this.tabCameraBtn && this.tabUploadBtn) {
      this.tabCameraBtn.addEventListener("click", () => this.switchEnrollTab("camera"));
      this.tabUploadBtn.addEventListener("click", () => this.switchEnrollTab("upload"));
    }
    if (this.btnSnapDoorbell) {
      this.btnSnapDoorbell.addEventListener("click", () => this.snapFromDoorbellStream());
    }
    if (this.btnStartWebcam) {
      this.btnStartWebcam.addEventListener("click", () => this.startWebcam());
    }
    if (this.btnCaptureWebcam) {
      this.btnCaptureWebcam.addEventListener("click", () => this.captureWebcamSnapshot());
    }

    // Photo Drop Zone
    this.dropZone.addEventListener("click", () => this.enrollPhotosInput.click());
    this.enrollPhotosInput.addEventListener("change", (e) => this.handlePhotoSelection(e.target.files));
    this.dropZone.addEventListener("dragover", (e) => { e.preventDefault(); this.dropZone.classList.add("hover"); });
    this.dropZone.addEventListener("dragleave", () => this.dropZone.classList.remove("hover"));
    this.dropZone.addEventListener("drop", (e) => {
      e.preventDefault();
      this.dropZone.classList.remove("hover");
      if (e.dataTransfer.files) this.handlePhotoSelection(e.dataTransfer.files);
    });

    // Form Submit
    this.enrollForm.addEventListener("submit", (e) => this.submitFaceEnrollment(e));

    // Event Filter
    this.eventFilter.addEventListener("change", () => this.fetchSecurityEvents());
  }

  startClock() {
    const update = () => {
      const now = new Date();
      this.clockDisplay.textContent = now.toTimeString().split(" ")[0];
    };
    update();
    setInterval(update, 1000);
  }

  // ========================================================================
  // WebSocket Multiplexed Protocol
  // ========================================================================

  connectWebSocket() {
    console.log(`Connecting to Sentinel Multiplexed WebSocket at ${this.wsUrl}...`);
    this.ws = new WebSocket(this.wsUrl);
    this.ws.binaryType = "arraybuffer";

    this.ws.onopen = () => {
      console.log("WebSocket connection established with host.");
      this.streamStatusText.textContent = "LIVE 30 FPS";
      clearTimeout(this.reconnectTimer);
    };

    this.ws.onmessage = (event) => {
      if (typeof event.data === "string") {
        this.handleJsonMessage(JSON.parse(event.data));
      } else if (event.data instanceof ArrayBuffer) {
        this.handleBinaryMessage(event.data);
      }
    };

    this.ws.onclose = () => {
      console.warn("WebSocket closed. Attempting reconnect in 2s...");
      this.streamStatusText.textContent = "OFFLINE (RECONNECTING)";
      this.reconnectTimer = setTimeout(() => this.connectWebSocket(), 2000);
    };

    this.ws.onerror = (err) => {
      console.error("WebSocket error:", err);
    };
  }

  handleBinaryMessage(buffer) {
    const view = new Uint8Array(buffer);
    if (view.length < 1) return;

    const channelTag = view[0];
    const payload = view.subarray(1);

    if (channelTag === 0x01) {
      // 30 FPS Annotated Camera JPEG
      const blob = new Blob([payload], { type: "image/jpeg" });
      const newUrl = URL.createObjectURL(blob);
      if (this.currentCameraUrl) URL.revokeObjectURL(this.currentCameraUrl);
      this.currentCameraUrl = newUrl;
      this.cameraImg.src = newUrl;

      // Update FPS calculation
      this.fpsCounter++;
      const now = performance.now();
      if (now - this.lastFpsCalc >= 1000) {
        this.hudDecoderFps.textContent = `FPS: ${this.fpsCounter.toFixed(1)}`;
        this.fpsCounter = 0;
        this.lastFpsCalc = now;
      }

    } else if (channelTag === 0x02) {
      // Live Doorway Mic PCM Audio Chunk (16kHz 16-bit Mono)
      if (this.isListening) {
        this.playPcmChunk(payload);
      }

    } else if (channelTag === 0x03) {
      // Doorbell Phone Kiosk Screen Mirror JPEG
      const blob = new Blob([payload], { type: "image/jpeg" });
      const newUrl = URL.createObjectURL(blob);
      if (this.currentKioskUrl) URL.revokeObjectURL(this.currentKioskUrl);
      this.currentKioskUrl = newUrl;
      this.kioskImg.src = newUrl;
    }
  }

  handleJsonMessage(msg) {
    const type = msg.type;

    if (type === "notification_toast") {
      this.showToast({
        packageName: msg.packageName,
        title: msg.title,
        text: msg.text,
      });
    } else if (type === "intruder_alert") {
      this.showToast({
        packageName: "SECURITY ALERT",
        title: "Intruder Detected!",
        text: msg.message,
        isAlert: true,
      });
      this.fetchSecurityEvents();
    } else if (type === "doorbell_ring") {
      this.showToast({
        packageName: "DOORBELL CHIME",
        title: "Doorbell Rung!",
        text: "A visitor is waiting at the front door.",
        isAlert: true,
      });
      this.playChimeSound();
      this.fetchSecurityEvents();
    } else if (type === "voice_note_transcribed") {
      this.showToast({
        packageName: "WHISPER AI",
        title: "Voice Note Received",
        text: `"${msg.transcript}"`,
      });
      this.fetchSecurityEvents();
    } else if (type === "telemetry_update") {
      this.updateTelemetry(msg);
    }
  }

  updateTelemetry(telem) {
    if (telem.battery_pct !== undefined) {
      this.batteryBadgeText.textContent = `BATTERY: ${telem.battery_pct}% ${telem.is_charging ? '⚡' : ''}`;
    }
    if (telem.temp_c !== undefined) {
      this.phoneTempBadge.textContent = `${telem.temp_c.toFixed(1)}°C`;
    }
  }

  // ========================================================================
  // Audio Intercom & Web Audio API
  // ========================================================================

  initAudioContext() {
    if (!this.audioCtx) {
      this.audioCtx = new (window.AudioContext || window.webkitAudioContext)({ sampleRate: 16000 });
    }
    if (this.audioCtx.state === "suspended") {
      this.audioCtx.resume();
    }
  }

  playPcmChunk(int16Bytes) {
    this.initAudioContext();
    const int16Array = new Int16Array(int16Bytes.buffer, int16Bytes.byteOffset, int16Bytes.byteLength / 2);
    const float32Array = new Float32Array(int16Array.length);
    for (let i = 0; i < int16Array.length; i++) {
      float32Array[i] = int16Array[i] / 32768.0;
    }

    const audioBuffer = this.audioCtx.createBuffer(1, float32Array.length, 16000);
    audioBuffer.getChannelData(0).set(float32Array);

    const source = this.audioCtx.createBufferSource();
    source.buffer = audioBuffer;
    source.connect(this.audioCtx.destination);
    source.start();
  }

  playChimeSound() {
    this.initAudioContext();
    const osc = this.audioCtx.createOscillator();
    const gain = this.audioCtx.createGain();
    osc.frequency.setValueAtTime(587.33, this.audioCtx.currentTime); // D5
    osc.frequency.setValueAtTime(880, this.audioCtx.currentTime + 0.15); // A5
    gain.gain.setValueAtTime(0.3, this.audioCtx.currentTime);
    gain.gain.exponentialRampToValueAtTime(0.001, this.audioCtx.currentTime + 1.2);
    osc.connect(gain);
    gain.connect(this.audioCtx.destination);
    osc.start();
    osc.stop(this.audioCtx.currentTime + 1.2);
  }

  toggleListenMic() {
    this.isListening = !this.isListening;
    if (this.isListening) {
      this.btnListen.classList.add("active");
      document.getElementById("listen-text").textContent = "Listening to Doorway Mic";
    } else {
      this.btnListen.classList.remove("active");
      document.getElementById("listen-text").textContent = "Mic Audio Muted";
    }
  }

  async startTalking() {
    this.isTalking = true;
    this.btnTalk.classList.add("talking");
    this.initAudioContext();

    try {
      this.mediaStream = await navigator.mediaDevices.getUserMedia({
        audio: { sampleRate: 16000, channelCount: 1, echoCancellation: true, noiseSuppression: true }
      });

      const source = this.audioCtx.createMediaStreamSource(this.mediaStream);
      const bufferSize = 2048;
      this.micAudioProcessor = this.audioCtx.createScriptProcessor(bufferSize, 1, 1);

      this.micAudioProcessor.onaudioprocess = (e) => {
        if (!this.isTalking || !this.ws || this.ws.readyState !== WebSocket.OPEN) return;
        const inputData = e.inputBuffer.getChannelData(0);
        const pcm16 = new Int16Array(inputData.length);
        for (let i = 0; i < inputData.length; i++) {
          const s = Math.max(-1, Math.min(1, inputData[i]));
          pcm16[i] = s < 0 ? s * 0x8000 : s * 0x7FFF;
        }

        // Send binary packet with Tag 0x04 (Intercom to Phone)
        const packet = new Uint8Array(1 + pcm16.buffer.byteLength);
        packet[0] = 0x04;
        packet.set(new Uint8Array(pcm16.buffer), 1);
        this.ws.send(packet.buffer);
      };

      source.connect(this.micAudioProcessor);
      this.micAudioProcessor.connect(this.audioCtx.destination);
    } catch (err) {
      console.error("Microphone access failed:", err);
      this.stopTalking();
    }
  }

  stopTalking() {
    this.isTalking = false;
    this.btnTalk.classList.remove("talking");
    if (this.micAudioProcessor) {
      this.micAudioProcessor.disconnect();
      this.micAudioProcessor = null;
    }
    if (this.mediaStream) {
      this.mediaStream.getTracks().forEach(track => track.stop());
      this.mediaStream = null;
    }
  }

  // ========================================================================
  // Hardware & REST Actions
  // ========================================================================

  async triggerSnapshot() {
    try {
      const res = await fetch("/api/camera/control", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action: "snapshot" }),
      });
      const data = await res.json();
      if (data.snapshot_url) {
        this.openSnapshotModal(data.snapshot_url, "Manual Snapshot Captured");
      }
    } catch (e) {
      console.error("Snapshot failed:", e);
    }
  }

  async toggleCameraLens() {
    const nextLens = this.currentLens === "back" ? "front" : "back";
    try {
      const res = await fetch("/api/camera/control", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action: "switch_camera", lens: nextLens }),
      });
      if (res.ok) {
        this.currentLens = nextLens;
        this.cameraLensLabel.textContent = `Lens: ${nextLens === "back" ? "Back" : "Front"}`;
      }
    } catch (e) {
      console.error("Camera switch failed:", e);
    }
  }

  async toggleEmergencySiren() {
    this.sirenActive = !this.sirenActive;
    const action = this.sirenActive ? "siren_on" : "siren_off";
    try {
      await fetch("/api/camera/control", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action }),
      });
      if (this.sirenActive) {
        this.btnEmergencySiren.classList.add("active");
        this.sirenText.textContent = "DISARM SIREN";
      } else {
        this.btnEmergencySiren.classList.remove("active");
        this.sirenText.textContent = "TRIGGER EMERGENCY SIREN";
      }
    } catch (e) {
      console.error("Siren control failed:", e);
    }
  }

  async pushKioskNotice(text, speakTts) {
    try {
      await fetch("/api/kiosk/notice", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text, speak_tts: speakTts }),
      });
      this.showToast({
        packageName: "KIOSK NOTICE",
        title: "Notice Dispatched",
        text: `Displayed on phone: "${text}"`,
      });
    } catch (e) {
      console.error("Failed to push kiosk notice:", e);
    }
  }

  sendQuickTts(text) {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify({ action: "SPEAK_TTS", text }));
      this.showToast({
        packageName: "EDGE-TTS BROADCAST",
        title: "Voice Broadcast Sent",
        text: `"${text}"`,
      });
    }
  }

  // ========================================================================
  // Face ID Enrollment & Management
  // ========================================================================

  async fetchEnrolledFaces() {
    try {
      const res = await fetch("/api/faces");
      const faces = await res.json();
      this.renderFacesList(faces);
    } catch (e) {
      console.error("Failed to load enrolled faces:", e);
    }
  }

  renderFacesList(faces) {
    if (!faces || faces.length === 0) {
      this.facesList.innerHTML = `<div class="empty-state">No faces enrolled. Click "+ Enroll Face" to add.</div>`;
      return;
    }

    this.facesList.innerHTML = faces.map(f => `
      <div class="face-item" data-id="${f.id}">
        <div class="face-info">
          <img src="${f.photo_url || '/static/default_avatar.jpg'}" alt="${f.name}" class="face-avatar" onerror="this.src='/static/default_avatar.jpg'">
          <div class="face-name-role">
            <h4>${f.name}</h4>
            <span class="face-role-tag">${f.role}</span>
          </div>
        </div>
        <button class="btn-del-face" onclick="sentinel.deleteFace(${f.id})" title="Remove resident">&times;</button>
      </div>
    `).join("");
  }

  async deleteFace(id) {
    if (!confirm("Are you sure you want to remove this enrolled face?")) return;
    try {
      await fetch(`/api/faces/${id}`, { method: "DELETE" });
      this.fetchEnrolledFaces();
    } catch (e) {
      console.error("Failed to delete face:", e);
    }
  }

  handlePhotoSelection(files) {
    this.filePreviewList.innerHTML = "";
    const validFiles = Array.from(files).slice(0, 5);
    validFiles.forEach(file => {
      const reader = new FileReader();
      reader.onload = (e) => {
        const img = document.createElement("img");
        img.src = e.target.result;
        img.className = "thumb-preview";
        this.filePreviewList.appendChild(img);
      };
      reader.readAsDataURL(file);
    });
  }

  // ========================================================================
  // Camera-Based Face Enrollment & Webcam Methods
  // ========================================================================

  switchEnrollTab(mode) {
    this.activeEnrollTab = mode;
    if (mode === "camera") {
      if (this.tabCameraBtn) this.tabCameraBtn.classList.add("active");
      if (this.tabUploadBtn) this.tabUploadBtn.classList.remove("active");
      if (this.cameraPanel) this.cameraPanel.classList.remove("hidden");
      if (this.uploadPanel) this.uploadPanel.classList.add("hidden");
    } else {
      if (this.tabUploadBtn) this.tabUploadBtn.classList.add("active");
      if (this.tabCameraBtn) this.tabCameraBtn.classList.remove("active");
      if (this.uploadPanel) this.uploadPanel.classList.remove("hidden");
      if (this.cameraPanel) this.cameraPanel.classList.add("hidden");
      this.stopWebcam();
    }
  }

  async snapFromDoorbellStream() {
    if (this.cameraStatusMsg) this.cameraStatusMsg.textContent = "Grabbing live doorway camera frame...";
    try {
      const res = await fetch("/api/camera/control", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action: "snapshot" }),
      });
      const data = await res.json();
      if (data.snapshot_url) {
        this.cameraCapturedImg.src = data.snapshot_url;
        this.cameraCapturedImg.classList.remove("hidden");
        this.webcamPreview.classList.add("hidden");
        this.cameraPlaceholderMsg.classList.add("hidden");
        if (this.btnCaptureWebcam) this.btnCaptureWebcam.classList.add("hidden");
        this.useDoorbellStreamFlag = true;
        this.capturedCameraBase64 = null;
        if (this.cameraStatusMsg) this.cameraStatusMsg.textContent = "✓ Doorway camera frame captured successfully!";
      } else {
        if (this.cameraStatusMsg) this.cameraStatusMsg.textContent = "No live doorbell feed available.";
      }
    } catch (err) {
      console.error("Error grabbing doorbell snapshot:", err);
      if (this.cameraStatusMsg) this.cameraStatusMsg.textContent = "Error capturing from doorbell.";
    }
  }

  async startWebcam() {
    if (this.cameraStatusMsg) this.cameraStatusMsg.textContent = "Requesting webcam access...";
    try {
      if (this.webcamStream) {
        this.stopWebcam();
      }
      this.webcamStream = await navigator.mediaDevices.getUserMedia({
        video: { width: 640, height: 480, facingMode: "user" }
      });
      this.webcamPreview.srcObject = this.webcamStream;
      this.webcamPreview.classList.remove("hidden");
      this.cameraCapturedImg.classList.add("hidden");
      this.cameraPlaceholderMsg.classList.add("hidden");
      if (this.btnCaptureWebcam) this.btnCaptureWebcam.classList.remove("hidden");
      if (this.cameraStatusMsg) this.cameraStatusMsg.textContent = "Webcam active. Click 'Take Snapshot' when ready.";
    } catch (err) {
      console.error("Webcam access failed:", err);
      if (this.cameraStatusMsg) this.cameraStatusMsg.textContent = "Could not access webcam: " + err.message;
    }
  }

  captureWebcamSnapshot() {
    if (!this.webcamStream) return;
    const video = this.webcamPreview;
    const canvas = this.webcamCanvas;
    canvas.width = video.videoWidth || 640;
    canvas.height = video.videoHeight || 480;
    const ctx = canvas.getContext("2d");
    ctx.drawImage(video, 0, 0, canvas.width, canvas.height);

    const b64 = canvas.toDataURL("image/jpeg", 0.9);
    this.capturedCameraBase64 = b64;
    this.useDoorbellStreamFlag = false;

    // Show captured image preview
    this.cameraCapturedImg.src = b64;
    this.cameraCapturedImg.classList.remove("hidden");
    this.webcamPreview.classList.add("hidden");
    if (this.btnCaptureWebcam) this.btnCaptureWebcam.classList.add("hidden");
    if (this.cameraStatusMsg) this.cameraStatusMsg.textContent = "✓ Snapshot captured! Ready to extract 512-D embedding.";
    this.stopWebcam();
  }

  stopWebcam() {
    if (this.webcamStream) {
      this.webcamStream.getTracks().forEach(track => track.stop());
      this.webcamStream = null;
    }
    if (this.btnCaptureWebcam) {
      this.btnCaptureWebcam.classList.add("hidden");
    }
  }

  async fetchSystemStatus() {
    try {
      const res = await fetch("/api/system/status");
      const status = await res.json();
      if (status.lan_ip && this.lanIpText) {
        this.lanIpText.textContent = `LAN: ${status.lan_ip}:8000`;
      }
      if (status.inference_fps !== undefined && this.aiFpsBadge) {
        this.aiFpsBadge.textContent = `${status.inference_fps.toFixed(1)} FPS`;
      }
    } catch (e) {
      console.debug("Status fetch error:", e);
    }
  }

  async submitFaceEnrollment(e) {
    e.preventDefault();
    const name = document.getElementById("enroll-name").value.trim();
    const role = document.getElementById("enroll-role").value;
    const greeting = document.getElementById("enroll-greeting").value.trim();
    const submitBtn = document.getElementById("enroll-submit-btn");

    if (this.activeEnrollTab === "camera") {
      if (!this.capturedCameraBase64 && !this.useDoorbellStreamFlag) {
        alert("Please capture a photo first using 'Capture from Doorbell Stream' or 'Open Device Webcam'.");
        return;
      }

      submitBtn.disabled = true;
      try {
        const payload = {
          name: name,
          role: role,
          custom_greeting: greeting || null,
          photo_base64: this.capturedCameraBase64,
          use_doorbell_stream: this.useDoorbellStreamFlag,
        };

        const res = await fetch("/api/faces/enroll-from-camera", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        });

        if (res.ok) {
          this.enrollModal.classList.add("hidden");
          this.enrollForm.reset();
          this.stopWebcam();
          this.cameraCapturedImg.classList.add("hidden");
          this.cameraPlaceholderMsg.classList.remove("hidden");
          this.capturedCameraBase64 = null;
          this.useDoorbellStreamFlag = false;
          this.fetchEnrolledFaces();
          this.showToast({
            packageName: "FACE ID ENROLLMENT",
            title: "Resident Enrolled via Camera",
            text: `Successfully enrolled ${name} [${role}]`,
          });
        } else {
          const err = await res.json();
          alert(`Enrollment failed: ${err.detail || "Unknown error"}`);
        }
      } catch (err) {
        console.error("Camera enrollment error:", err);
      } finally {
        submitBtn.disabled = false;
      }
      return;
    }

    // Tab 2: File Upload
    const files = this.enrollPhotosInput.files;
    if (!files || files.length === 0) {
      alert("Please upload at least 1 photo for face extraction.");
      return;
    }

    const formData = new FormData();
    formData.append("name", name);
    formData.append("role", role);
    if (greeting) formData.append("custom_greeting", greeting);

    for (let i = 0; i < Math.min(files.length, 5); i++) {
      formData.append("files", files[i]);
    }

    submitBtn.disabled = true;

    try {
      const res = await fetch("/api/faces/enroll", {
        method: "POST",
        body: formData,
      });

      if (res.ok) {
        this.enrollModal.classList.add("hidden");
        this.enrollForm.reset();
        this.filePreviewList.innerHTML = "";
        this.fetchEnrolledFaces();
        this.showToast({
          packageName: "FACE ID ENROLLMENT",
          title: "Resident Enrolled",
          text: `Successfully enrolled ${name} [${role}]`,
        });
      } else {
        const err = await res.json();
        alert(`Enrollment failed: ${err.detail || "Unknown error"}`);
      }
    } catch (err) {
      console.error("Face enrollment request error:", err);
    } finally {
      submitBtn.disabled = false;
    }
  }

  // ========================================================================
  // Security Event Logs & Voice Notes
  // ========================================================================

  async fetchSecurityEvents() {
    const filter = this.eventFilter.value;
    const url = filter ? `/api/events?event_type=${filter}&limit=40` : `/api/events?limit=40`;
    try {
      const res = await fetch(url);
      const data = await res.json();
      this.renderEvents(data.events || []);
    } catch (e) {
      console.error("Failed to fetch events:", e);
    }
  }

  renderEvents(events) {
    if (!events || events.length === 0) {
      this.eventsStream.innerHTML = `<div class="empty-state">No events recorded.</div>`;
      return;
    }

    this.eventsStream.innerHTML = events.map(ev => {
      const timeStr = new Date(ev.created_at).toLocaleTimeString();
      const hasSnap = ev.snapshot_url;
      const meta = ev.metadata || {};
      const hasAudio = meta.audio_url;

      return `
        <div class="event-card-item ${ev.severity}">
          <div class="event-top-row">
            <span class="event-type-badge">${ev.event_type.replace('_', ' ')}</span>
            <span class="event-time">${timeStr}</span>
          </div>
          <p class="event-desc">${ev.message}</p>
          ${hasSnap ? `<img src="${ev.snapshot_url}" alt="Snapshot" class="event-snapshot-thumb" onclick="sentinel.openSnapshotModal('${ev.snapshot_url}', '${ev.message}')">` : ''}
          ${hasAudio ? `<audio controls src="${meta.audio_url}" class="audio-player-widget"></audio>` : ''}
        </div>
      `;
    }).join("");
  }

  openSnapshotModal(url, title) {
    this.modalSnapshotImg.src = url;
    document.getElementById("modal-title").textContent = title || "Security Snapshot";
    this.snapshotModal.classList.remove("hidden");
  }

  // ========================================================================
  // Real-Time Notification Toast System
  // ========================================================================

  showToast({ packageName, title, text, isAlert = false }) {
    const toast = document.createElement("div");
    toast.className = `toast ${isAlert ? 'toast-alert' : ''}`;
    toast.innerHTML = `
      <div class="toast-header">
        <span class="toast-pkg">${packageName}</span>
        <button class="icon-btn" onclick="this.parentElement.parentElement.remove()">&times;</button>
      </div>
      <div class="toast-title">${title}</div>
      <div class="toast-text">${text}</div>
    `;

    this.toastContainer.appendChild(toast);
    setTimeout(() => {
      toast.style.opacity = "0";
      setTimeout(() => toast.remove(), 400);
    }, 6000);
  }
}

// Global initialization
window.addEventListener("DOMContentLoaded", () => {
  window.sentinel = new SentinelClient();
});
