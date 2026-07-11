(function () {
  const API_BASE = window.location.origin;
  const pageType = document.body?.dataset?.page || "live";
  const isLivePage = pageType === "live";
  const isAdminPage = pageType === "admin";

  const el = (id) => document.getElementById(id);
  const stream = el("stream");
  const canvas = el("overlay");
  const ctx = canvas?.getContext?.("2d") ?? null;

  const stateEl = el("state");
  const detectionsEl = el("detections");
  const framesEl = el("frames");
  const registeredCountEl = el("registeredCount");
  const lastFaceEl = el("lastFace");
  const facesEl = el("faces");
  const rawEl = el("raw");
  const startBtn = el("startBtn");
  const stopBtn = el("stopBtn");
  const registerBtn = el("registerBtn");
  const clearBtn = el("clearBtn");
  const personNameEl = el("personName");
  const recognitionTextEl = el("recognitionText");
  const recognitionDotEl = el("recognitionDot");
  const knownCountEl = el("knownCount");
  const attendanceListEl = el("attendanceList");
  const cameraSelectEl = el("cameraSelect");
  const cameraRoleEl = el("cameraRole");
  const refreshCamerasBtn = el("refreshCamerasBtn");
  const cameraFormEl = el("cameraForm");
  const cameraListEl = el("cameraList");
  const syncStatusEl = el("syncStatus");
  const syncPendingEl = el("syncPending");
  const syncBtn = el("syncBtn");
  const syncNowBtn = el("syncNowBtn");
  const syncQueueEl = el("syncQueue");
  const checkUpdateBtn = el("checkUpdateBtn");
  const updateStatusEl = el("updateStatus");
  const downloadCsvBtn = el("downloadCsvBtn");
  const refreshAttendanceBtn = el("refreshAttendanceBtn");

  let latestStatus = null;
  let cameras = [];
  let syncState = null;
  let latestAttendance = [];
  let lastAlarmAt = 0;
  let alarmAudio = null;

  if (stream) {
    stream.crossOrigin = "anonymous";
    stream.src = `${API_BASE}/stream.mjpg`;
  }

  function resizeCanvas() {
    if (!stream || !canvas || !ctx) {
      return { width: 0, height: 0 };
    }
    const rect = stream.getBoundingClientRect();
    const dpr = window.devicePixelRatio || 1;
    canvas.width = rect.width * dpr;
    canvas.height = rect.height * dpr;
    canvas.style.width = `${rect.width}px`;
    canvas.style.height = `${rect.height}px`;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    return { width: rect.width, height: rect.height };
  }

  function setPill(node, value) {
    node.textContent = value;
    node.className = `pill ${value}`;
  }

  function activeCameraId() {
    return cameraSelectEl.value || null;
  }

  function activeCameraRole() {
    return cameraRoleEl?.value || null;
  }

  function renderState() {
    const state = latestStatus?.state || "idle";
    setPill(stateEl, state);
    detectionsEl.textContent = latestStatus?.detectionCount || 0;
    framesEl.textContent = `${latestStatus?.frames?.received || 0} / ${latestStatus?.frames?.accepted || 0}`;
    registeredCountEl.textContent = latestStatus?.registeredFaces || 0;
    const faces = latestStatus?.lastFaces || [];
    const known = faces.find((face) => face?.match?.label);
    lastFaceEl.textContent = known
      ? `Known: ${known.match.label}`
      : faces.length
        ? "Unknown"
        : "-";
    if (isLivePage && faces.length && !known) {
      void triggerUnknownAlarm();
    }
    rawEl.textContent = JSON.stringify(latestStatus, null, 2);
  }

  function renderFacesList() {
    const faces = latestStatus?.lastFaces || [];
    if (!faces.length) {
      facesEl.textContent = "No faces yet";
      return;
    }

    facesEl.innerHTML = faces
      .map((face) => {
        const known = Boolean(face.match && face.match.label);
        return `
          <div class="face">
            <div><strong>${Math.round((face.confidence || 0) * 100)}%</strong> confidence</div>
            <div class="small">${JSON.stringify(face.box)}</div>
            <div class="match">
              <span class="match-dot ${known ? "known" : ""}"></span>
              <span>${known ? `Known: ${face.match.label}` : "Unknown"}</span>
            </div>
          </div>
        `;
      })
      .join("");
  }

  function drawServerDetections() {
    if (!isLivePage || !stream || !canvas || !ctx) {
      return;
    }
    const faces = latestStatus?.lastFaces || [];
    const { width, height } = resizeCanvas();
    ctx.clearRect(0, 0, width, height);

    if (!faces.length || !stream.naturalWidth || !stream.naturalHeight) {
      return;
    }

    const imgW = stream.naturalWidth;
    const imgH = stream.naturalHeight;
    const boxW = stream.clientWidth;
    const boxH = stream.clientHeight;
    const scale = Math.min(boxW / imgW, boxH / imgH);
    const drawnW = imgW * scale;
    const drawnH = imgH * scale;
    const offsetX = (boxW - drawnW) / 2;
    const offsetY = (boxH - drawnH) / 2;

    ctx.lineWidth = 3;
    ctx.font = "bold 14px Inter, sans-serif";

    faces.forEach((face) => {
      const known = Boolean(face.match && face.match.label);
      const x = offsetX + face.box.x * scale;
      const y = offsetY + face.box.y * scale;
      const w = face.box.width * scale;
      const h = face.box.height * scale;

      ctx.strokeStyle = known ? "#22c55e" : "#f87171";
      ctx.strokeRect(x, y, w, h);

      const label = known ? `Known: ${face.match.label}` : "Unknown";
      const labelText = `${label} · ${Math.round((face.match?.confidence ?? face.confidence) * 100)}%`;
      const labelWidth = ctx.measureText(labelText).width + 14;
      ctx.fillStyle = known ? "#166534" : "#7f1d1d";
      ctx.fillRect(x, Math.max(4, y - 22), labelWidth, 20);
      ctx.fillStyle = "#fff";
      ctx.fillText(labelText, x + 7, Math.max(18, y - 8));
    });
  }

  function renderCameras() {
    const options = cameras
      .map(
        (camera) =>
          `<option value="${camera.id}">${camera.name} ${camera.enabled ? "" : "(disabled)"}</option>`,
      )
      .join("");
    cameraSelectEl.innerHTML = `<option value="">Auto select</option>${options}`;

    cameraListEl.innerHTML = cameras.length
      ? cameras
          .map(
            (camera) => `
          <div class="camera-card">
                <div>
                  <div><strong>${camera.name}</strong></div>
                  <div class="small">Role: ${camera.camera_role || "general"}</div>
                  <div class="small">${camera.rtsp_url}</div>
                  <div class="small">${camera.enabled ? "Enabled" : "Disabled"}</div>
                </div>
                <div class="actions-inline">
                  <button data-camera-edit="${camera.id}">Edit</button>
                  <button data-camera-delete="${camera.id}">Delete</button>
                </div>
              </div>
            `,
          )
          .join("")
      : '<div class="small">No cameras saved yet.</div>';

    cameraListEl.querySelectorAll("[data-camera-edit]").forEach((button) => {
      button.addEventListener("click", () => {
        const camera = cameras.find(
          (item) => item.id === button.getAttribute("data-camera-edit"),
        );
        if (!camera) return;
        cameraFormEl.elements.namedItem("id").value = camera.id;
        cameraFormEl.elements.namedItem("name").value = camera.name;
        cameraFormEl.elements.namedItem("cameraRole").value =
          camera.camera_role || "general";
        cameraFormEl.elements.namedItem("rtspUrl").value = camera.rtsp_url;
        cameraFormEl.elements.namedItem("rtspUsername").value =
          camera.rtsp_username || "";
        cameraFormEl.elements.namedItem("rtspPassword").value =
          camera.rtsp_password || "";
        cameraFormEl.elements.namedItem("enabled").checked = Boolean(
          camera.enabled,
        );
      });
    });

    cameraListEl.querySelectorAll("[data-camera-delete]").forEach((button) => {
      button.addEventListener("click", async () => {
        const cameraId = button.getAttribute("data-camera-delete");
        if (!cameraId) return;
        await postJson(
          `${API_BASE}/cameras/${encodeURIComponent(cameraId)}`,
          null,
          "DELETE",
        );
        await loadCameras();
      });
    });
  }

  function renderSync() {
    syncStatusEl.textContent = syncState?.enabled ? "Enabled" : "Disabled";
    syncPendingEl.textContent = String(syncState?.pending ?? 0);
    syncQueueEl.textContent = JSON.stringify(syncState, null, 2);
    const update = latestStatus?.update || {};
    updateStatusEl.textContent = update.enabled
      ? update.updateAvailable
        ? `Update available: ${update.latestVersion || "unknown"}`
        : `Current: ${update.currentVersion || "unknown"}`
      : "Updater disabled";
  }

  function formatDateTime(value) {
    if (!value) {
      return "-";
    }

    const date = new Date(value);
    if (Number.isNaN(date.getTime())) {
      return String(value);
    }

    return new Intl.DateTimeFormat(undefined, {
      dateStyle: "medium",
      timeStyle: "medium",
    }).format(date);
  }

  function formatRole(role) {
    if (!role) {
      return "general";
    }
    return String(role).replaceAll("_", " ");
  }

  async function triggerUnknownAlarm() {
    const now = Date.now();
    if (now - lastAlarmAt < 5000) {
      return;
    }
    lastAlarmAt = now;

    if ("Notification" in window && Notification.permission === "default") {
      Notification.requestPermission().catch(() => {});
    }

    if ("Notification" in window && Notification.permission === "granted") {
      try {
        new Notification("Unknown person detected", {
          body: "An unrecognized face is visible on the live camera.",
        });
      } catch {
        // ignore notification failures
      }
    }

    if (!alarmAudio) {
      alarmAudio = new Audio("/alarm.wav");
      alarmAudio.preload = "auto";
    }

    try {
      alarmAudio.currentTime = 0;
      await alarmAudio.play();
      return;
    } catch {
      // fall through to synthesized beep if the sound file is unavailable
    }

    const AudioCtor = window.AudioContext || window.webkitAudioContext;
    if (!AudioCtor) {
      return;
    }

    try {
      const ctx = new AudioCtor();
      const gain = ctx.createGain();
      gain.gain.value = 0.001;
      gain.connect(ctx.destination);

      const oscillator = ctx.createOscillator();
      oscillator.type = "sine";
      oscillator.frequency.value = 880;
      oscillator.connect(gain);
      oscillator.start();

      const current = ctx.currentTime;
      gain.gain.cancelScheduledValues(current);
      gain.gain.setValueAtTime(0.001, current);
      gain.gain.exponentialRampToValueAtTime(0.15, current + 0.05);
      gain.gain.exponentialRampToValueAtTime(0.001, current + 0.65);

      window.setTimeout(() => {
        try {
          oscillator.stop();
        } catch {
          // ignore stop race
        }
      }, 700);
    } catch {
      // ignore audio setup failures
    }
  }

  function renderAttendance() {
    if (!attendanceListEl) {
      return;
    }

    if (!latestAttendance.length) {
      attendanceListEl.innerHTML =
        '<div class="small">No attendance records yet.</div>';
      return;
    }

    attendanceListEl.innerHTML = latestAttendance
      .map(
        (row) => `
          <div class="attendance-row">
            <div class="row">
              <div>
                <div><strong>${row.label}</strong></div>
                <div style="font-size: 16px">Appearances: ${row.appearances}</div>
              </div>
              <div class="pill">${Math.round((row.max_confidence || 0) * 100)}%</div>
            </div>
            <div style="font-size: 16px" class="small">Check in role: ${formatRole(row.first_camera_role)}</div>
            <div style="font-size: 16px" class="small">Check out role: ${formatRole(row.last_camera_role)}</div>
            <div style="font-size: 16px" class="small">First appearance: ${formatDateTime(row.first_appearance)}</div>
            <div style="font-size: 16px" class="small">Last appearance: ${formatDateTime(row.last_appearance)}</div>
            <div style="font-size: 16px" class="small">Raw first: ${row.first_appearance}</div>
            <div class="small">Raw last: ${row.last_appearance}</div>
          </div>
        `,
      )
      .join("");
  }

  async function fetchStatus() {
    const response = await fetch(`${API_BASE}/status`, { cache: "no-store" });
    latestStatus = await response.json();
    const faces = latestStatus?.lastFaces || [];
    const known = faces.find((face) => face?.match?.label);
    recognitionTextEl.textContent = known
      ? `Known: ${known.match.label}`
      : "Unknown";
    recognitionDotEl.className = `match-dot ${known ? "known" : ""}`;
    knownCountEl.textContent = `${latestStatus?.registeredFaces || 0} registered face${(latestStatus?.registeredFaces || 0) === 1 ? "" : "s"}`;
    renderState();
    renderFacesList();
    drawServerDetections();
  }

  async function loadCameras() {
    if (!cameraListEl || !cameraSelectEl) {
      return;
    }
    const response = await fetch(`${API_BASE}/cameras`, { cache: "no-store" });
    const payload = await response.json();
    cameras = payload.cameras || [];
    renderCameras();
  }

  async function loadSyncStatus() {
    const response = await fetch(`${API_BASE}/sync/status`, {
      cache: "no-store",
    });
    syncState = await response.json();
    renderSync();
  }

  async function loadAttendance() {
    if (!attendanceListEl) {
      return;
    }
    const response = await fetch(`${API_BASE}/attendance`, {
      cache: "no-store",
    });
    const payload = await response.json();
    latestAttendance = payload.attendance || [];
    renderAttendance();
  }

  async function postJson(url, body, method = "POST") {
    const response = await fetch(url, {
      method,
      headers: body ? { "Content-Type": "application/json" } : undefined,
      body: body ? JSON.stringify(body) : undefined,
    });

    if (!response.ok) {
      const payload = await response.json().catch(() => ({}));
      throw new Error(
        payload.error ||
          payload.message ||
          `Request failed: ${response.status}`,
      );
    }

    return response.json().catch(() => ({}));
  }

  if (isLivePage && startBtn) {
    startBtn.addEventListener("click", async () => {
      await postJson(`${API_BASE}/start`, {
        cameraId: activeCameraId(),
        cameraRole: activeCameraRole(),
      });
      await Promise.all([fetchStatus(), loadSyncStatus()]);
    });
  }

  if (isLivePage && stopBtn) {
    stopBtn.addEventListener("click", async () => {
      await postJson(`${API_BASE}/stop`);
      await fetchStatus();
    });
  }

  if (isLivePage && registerBtn) {
    registerBtn.addEventListener("click", async () => {
      const label = personNameEl.value.trim();
      if (!label) {
        alert("Enter a name first.");
        return;
      }

      try {
        registerBtn.disabled = true;
        await postJson(`${API_BASE}/faces/register`, { label });
        personNameEl.value = "";
        await fetchStatus();
      } catch (error) {
        alert(error.message || "Registration failed");
      } finally {
        registerBtn.disabled = false;
      }
    });
  }

  if (isLivePage && clearBtn) {
    clearBtn.addEventListener("click", async () => {
      await postJson(`${API_BASE}/faces/clear`);
      await fetchStatus();
    });
  }

  if (refreshCamerasBtn) {
    refreshCamerasBtn.addEventListener("click", loadCameras);
  }

  if (syncBtn) {
    syncBtn.addEventListener("click", loadSyncStatus);
  }

  if (syncNowBtn) {
    syncNowBtn.addEventListener("click", async () => {
      await postJson(`${API_BASE}/sync/run`);
      await loadSyncStatus();
    });
  }

  if (checkUpdateBtn) {
    checkUpdateBtn.addEventListener("click", async () => {
      await postJson(`${API_BASE}/update/check`);
      await fetchStatus();
    });
  }

  if (isAdminPage && downloadCsvBtn) {
    downloadCsvBtn.addEventListener("click", () => {
      window.location.href = `${API_BASE}/attendance.csv`;
    });
  }

  if (isAdminPage && refreshAttendanceBtn) {
    refreshAttendanceBtn.addEventListener("click", loadAttendance);
  }

  if (isAdminPage && cameraFormEl) {
    cameraFormEl.addEventListener("submit", async (event) => {
      event.preventDefault();
      const formData = new FormData(cameraFormEl);
      const payload = {
        id: formData.get("id") || undefined,
        name: String(formData.get("name") || "").trim(),
        cameraRole:
          String(formData.get("cameraRole") || "general").trim() || "general",
        rtspUrl: String(formData.get("rtspUrl") || "").trim(),
        rtspUsername: String(formData.get("rtspUsername") || "").trim() || null,
        rtspPassword: String(formData.get("rtspPassword") || "").trim() || null,
        enabled: formData.get("enabled") === "on",
      };

      const cameraId = String(payload.id || "").trim();
      if (!payload.name || !payload.rtspUrl) {
        alert("Camera name and RTSP URL are required.");
        return;
      }

      if (cameraId) {
        await postJson(
          `${API_BASE}/cameras/${encodeURIComponent(cameraId)}`,
          payload,
          "PUT",
        );
      } else {
        await postJson(`${API_BASE}/cameras`, payload);
      }
      cameraFormEl.reset();
      await loadCameras();
    });
  }

  if (isLivePage && stream) {
    stream.addEventListener("load", drawServerDetections);
  }
  if (isLivePage) {
    window.addEventListener("resize", drawServerDetections);
  }

  setInterval(async () => {
    const tasks = [loadSyncStatus()];
    if (isLivePage) {
      tasks.unshift(fetchStatus(), loadCameras());
    }
    if (isAdminPage) {
      tasks.push(loadAttendance());
    }
    await Promise.allSettled(tasks);
  }, 2000);

  const bootTasks = [loadSyncStatus()];
  if (isLivePage) {
    bootTasks.push(fetchStatus(), loadCameras());
  }
  if (isAdminPage) {
    bootTasks.push(loadAttendance(), loadCameras());
  }
  void Promise.allSettled(bootTasks);
})();
