(function () {
  const API_BASE = window.location.origin;
  const pageType = document.body?.dataset?.page || "live";
  const isLivePage = pageType === "live";
  const isAdminPage = pageType === "admin";

  const EDIT_ICON_HTML = `<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="lucide lucide-square-pen"><path d="M12 3H5a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.375 2.625a1 1 0 0 1 3 3l-9.013 9.014a2 2 0 0 1-.853.505l-2.873.84a.5.5 0 0 1-.62-.62l.84-2.873a2 2 0 0 1 .506-.852z"/></svg>`;
  const DELETE_ICON_HTML = `<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="lucide lucide-trash"><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6"/><path d="M3 6h18"/><path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>`;

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
  const recognitionTextEl = el("recognitionText");
  const recognitionDotEl = el("recognitionDot");
  const knownCountEl = el("knownCount");
  const attendanceListEl = el("attendanceList");
  const cameraSelectEl = el("cameraSelect");
  const cameraRoleEl = el("cameraRole");
  const cameraWallEl = el("cameraWall");
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
  const departmentFormEl = el("departmentForm");
  const departmentListEl = el("departmentList");
  const employeeFormEl = el("employeeForm");
  const employeeListEl = el("employeeList");
  const cameraDepartmentSelectEl = el("cameraDepartmentSelect");
  const employeeDepartmentSelectEl = el("employeeDepartmentSelect");
  const cleanupFacesBtn = el("cleanupFacesBtn");

  let latestStatus = null;
  let cameras = [];
  let syncState = null;
  let latestAttendance = [];
  let departments = [];
  let employees = [];
  let lastAlarmAt = 0;
  let alarmAudio = null;
  let streamLoadTimer = null;
  let pollInFlight = false;
  let statusTimer = null;
  let syncTimer = null;
  let adminTimer = null;
  let currentMainStreamUrl = "";
  let cameraWallSignature = "";
  let frameTimer = null;
  let liveSocket = null;
  let liveSocketReconnectTimer = null;
  const latestFrameUrls = new Map();

  function buildStreamUrl(params = {}) {
    const url = new URL("/frame.jpg", API_BASE);
    if (params.cameraId) {
      url.searchParams.set("cameraId", params.cameraId);
    }
    if (params.cameraRole) {
      url.searchParams.set("cameraRole", params.cameraRole);
    }
    url.searchParams.set("_", String(Date.now()));
    return url.toString();
  }

  function wsUrl(path) {
    const url = new URL(path, API_BASE);
    url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
    return url.toString();
  }

  function buildStreamKey(params = {}) {
    const key = new URL("/frame.jpg", API_BASE);
    if (params.cameraId) {
      key.searchParams.set("cameraId", params.cameraId);
    }
    if (params.cameraRole) {
      key.searchParams.set("cameraRole", params.cameraRole);
    }
    return key.toString();
  }

  function refreshMainStream() {
    if (!stream) {
      return;
    }
    if (streamLoadTimer) {
      window.clearTimeout(streamLoadTimer);
    }
    stream.onload = () => {
      if (stateEl && latestStatus?.state === "running") {
        stateEl.textContent = "running";
        stateEl.className = "pill running";
      }
    };
    stream.onerror = () => {
      if (stateEl) {
        stateEl.textContent = "error";
        stateEl.className = "pill error";
      }
    };
    stream.crossOrigin = "anonymous";
    const params = {
      cameraId: activeCameraId() || undefined,
      cameraRole: activeCameraId() ? undefined : activeCameraRole() || undefined,
    };
    const nextKey = buildStreamKey(params);
    if (nextKey === currentMainStreamUrl && stream.src) {
      return;
    }
    currentMainStreamUrl = nextKey;
    const activeId = activeCameraId();
    if (activeId && latestFrameUrls.has(activeId)) {
      stream.src = latestFrameUrls.get(activeId);
    } else if (!activeId) {
      const firstCamera = cameras.find((camera) => !activeCameraRole() || camera.camera_role === activeCameraRole());
      const cached = firstCamera ? latestFrameUrls.get(firstCamera.id) : null;
      if (cached) {
        stream.src = cached;
      }
    }
    streamLoadTimer = window.setTimeout(() => {
      if (!stream.naturalWidth || !stream.naturalHeight) {
        if (stateEl) {
          stateEl.textContent = "connecting";
          stateEl.className = "pill idle";
        }
      }
    }, 8000);
  }

  function refreshFrameImages() {
    if (!isLivePage) {
      return;
    }
    if (stream && currentMainStreamUrl) {
      const params = {
        cameraId: activeCameraId() || undefined,
        cameraRole: activeCameraId() ? undefined : activeCameraRole() || undefined,
      };
      stream.src = buildStreamUrl(params);
    }
    cameraWallEl?.querySelectorAll("[data-camera-stream]").forEach((node) => {
      if (!(node instanceof HTMLImageElement)) {
        return;
      }
      const cameraId = node.getAttribute("data-camera-stream");
      if (!cameraId) {
        return;
      }
      node.src = buildStreamUrl({ cameraId });
    });
  }

  function applyFrame(cameraId, jpegBase64) {
    const src = `data:image/jpeg;base64,${jpegBase64}`;
    latestFrameUrls.set(cameraId, src);
    const activeId = activeCameraId();
    const activeRole = activeCameraRole();
    const camera = cameras.find((item) => item.id === cameraId);
    const shouldShowMain =
      !activeId
        ? !activeRole || activeRole === camera?.camera_role
        : activeId === cameraId;
    if (stream && shouldShowMain) {
      stream.src = src;
    }
    const tile = cameraWallEl?.querySelector(`[data-camera-stream="${cameraId}"]`);
    if (tile instanceof HTMLImageElement) {
      tile.src = src;
    }
  }

  function connectLiveSocket() {
    if (!isLivePage || liveSocket?.readyState === WebSocket.OPEN || liveSocket?.readyState === WebSocket.CONNECTING) {
      return;
    }
    liveSocket = new WebSocket(wsUrl("/ws/live"));
    liveSocket.onopen = () => {
      if (stateEl && latestStatus?.state === "running") {
        stateEl.textContent = "running";
        stateEl.className = "pill running";
      }
    };
    liveSocket.onmessage = (event) => {
      try {
        const payload = JSON.parse(event.data);
        if (payload.status) {
          latestStatus = payload.status;
          renderState();
          renderFacesList();
          drawServerDetections();
          updateCameraWallStatus();
        }
        (payload.frames || []).forEach((frame) => {
          if (frame.cameraId && frame.jpegBase64) {
            applyFrame(frame.cameraId, frame.jpegBase64);
          }
        });
      } catch {
        // ignore malformed socket payloads
      }
    };
    liveSocket.onclose = () => {
      liveSocket = null;
      if (liveSocketReconnectTimer) {
        window.clearTimeout(liveSocketReconnectTimer);
      }
      liveSocketReconnectTimer = window.setTimeout(connectLiveSocket, 1500);
    };
    liveSocket.onerror = () => {
      try {
        liveSocket?.close();
      } catch {
        // ignore close races
      }
    };
  }

  if (stream) {
    refreshMainStream();
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
    if (!cameraSelectEl) {
      return;
    }
    if (cameraDepartmentSelectEl) {
      cameraDepartmentSelectEl.innerHTML = `<option value="">No department</option>${departments
        .map((department) => `<option value="${department.id}">${department.name}</option>`)
        .join("")}`;
    }
    if (employeeDepartmentSelectEl) {
      employeeDepartmentSelectEl.innerHTML = departments
        .map((department) => `<option value="${department.id}">${department.name}</option>`)
        .join("");
    }

    const options = cameras
      .map(
        (camera) =>
          `<option value="${camera.id}">${camera.name} ${camera.enabled ? "" : "(disabled)"}</option>`,
      )
      .join("");
    cameraSelectEl.innerHTML = `<option value="">Auto select</option>${options}`;

    if (!cameraListEl) {
      return;
    }

    cameraListEl.innerHTML = cameras.length
      ? cameras
          .map(
            (camera) => `
          <div class="camera-card">
                <div>
                  <div><strong>${camera.name}</strong></div>
                  <div class="small">Role: ${camera.camera_role || "general"}</div>
                  <div class="small">Department: ${departmentName(camera.department_id)}</div>
                  <div class="small">${camera.rtsp_url}</div>
                  <div class="small">${camera.enabled ? "Enabled" : "Disabled"}</div>
                </div>
                <div class="actions-inline">
                  <button data-camera-edit="${camera.id}" title="Edit Camera" class="btn-icon-action btn-edit">${EDIT_ICON_HTML}</button>
                  <button data-camera-delete="${camera.id}" title="Delete Camera" class="btn-icon-action btn-delete">${DELETE_ICON_HTML}</button>
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
        cameraFormEl.elements.namedItem("departmentId").value =
          camera.department_id || "";
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

  function renderCameraWall() {
    if (!cameraWallEl) {
      return;
    }

    const enabled = cameras.filter((camera) => camera.enabled);
    const nextSignature = enabled.map((camera) => `${camera.id}:${camera.name}:${camera.camera_role || "general"}`).join("|");
    if (!enabled.length) {
      cameraWallSignature = "";
      cameraWallEl.innerHTML = '<div class="small">No enabled cameras available.</div>';
      return;
    }
    if (nextSignature === cameraWallSignature) {
      updateCameraWallStatus();
      return;
    }
    cameraWallSignature = nextSignature;

    cameraWallEl.innerHTML = enabled
      .map(
        (camera) => `
          <div class="camera-feed">
            <div class="row">
              <div>
                <div><strong>${camera.name}</strong></div>
                <div class="small">Role: ${camera.camera_role || "general"}</div>
              </div>
              <div class="small">${camera.id}</div>
            </div>
            <div class="camera-stage">
              <img data-camera-stream="${camera.id}" alt="${camera.name} stream" loading="lazy" />
              <canvas data-camera-overlay="${camera.id}"></canvas>
            </div>
            <div class="small" data-camera-status="${camera.id}">Connecting</div>
          </div>
        `,
      )
      .join("");
    updateCameraWallStatus();
  }

  function updateCameraWallStatus() {
    if (!cameraWallEl) {
      return;
    }
    const cameraStatuses = Array.isArray(latestStatus?.cameras) ? latestStatus.cameras : [];

    cameraWallEl.querySelectorAll("[data-camera-overlay]").forEach((node) => {
      const cameraId = node.getAttribute("data-camera-overlay");
      const label = cameraWallEl.querySelector(`[data-camera-status="${cameraId}"]`);
      const cameraStatus = cameraStatuses.find((item) => item.id === cameraId);
      if (label) {
        label.textContent = cameraStatus?.stream?.running ? "Running" : "Connecting";
      }
      const tile = cameraWallEl.querySelector(`[data-camera-stream="${cameraId}"]`);
      if (!(node instanceof HTMLCanvasElement) || !(tile instanceof HTMLImageElement)) {
        return;
      }

      const rect = tile.getBoundingClientRect();
      const dpr = window.devicePixelRatio || 1;
      node.width = rect.width * dpr;
      node.height = rect.height * dpr;
      node.style.width = `${rect.width}px`;
      node.style.height = `${rect.height}px`;
      const overlayCtx = node.getContext("2d");
      if (!overlayCtx) {
        return;
      }
      overlayCtx.setTransform(dpr, 0, 0, dpr, 0, 0);
      overlayCtx.clearRect(0, 0, rect.width, rect.height);

      const faces = cameraStatus?.lastFaces || [];
      if (!faces.length || !tile.naturalWidth || !tile.naturalHeight) {
        return;
      }

      const scale = Math.min(rect.width / tile.naturalWidth, rect.height / tile.naturalHeight);
      const drawnW = tile.naturalWidth * scale;
      const drawnH = tile.naturalHeight * scale;
      const offsetX = (rect.width - drawnW) / 2;
      const offsetY = (rect.height - drawnH) / 2;

      overlayCtx.lineWidth = 3;
      overlayCtx.font = "bold 14px Inter, sans-serif";

      faces.forEach((face) => {
        const known = Boolean(face.match && face.match.label);
        const x = offsetX + face.box.x * scale;
        const y = offsetY + face.box.y * scale;
        const w = face.box.width * scale;
        const h = face.box.height * scale;

        overlayCtx.strokeStyle = known ? "#22c55e" : "#f87171";
        overlayCtx.strokeRect(x, y, w, h);
        const label = known ? `Known: ${face.match.label}` : "Unknown";
        const labelText = `${label} · ${Math.round((face.match?.confidence ?? face.confidence) * 100)}%`;
        const labelWidth = overlayCtx.measureText(labelText).width + 14;
        overlayCtx.fillStyle = known ? "#166534" : "#7f1d1d";
        overlayCtx.fillRect(x, Math.max(4, y - 22), labelWidth, 20);
        overlayCtx.fillStyle = "#fff";
        overlayCtx.fillText(labelText, x + 7, Math.max(18, y - 8));
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

  function formatPercent(value) {
    return `${Math.round((Number(value) || 0) * 100)}%`;
  }

  function snapshotUrl(path) {
    if (!path) {
      return "";
    }
    const normalized = String(path).replaceAll("\\", "/");
    const marker = "/snapshots/";
    const filename = normalized.includes(marker)
      ? normalized.slice(normalized.indexOf(marker) + marker.length)
      : normalized.replace(/^\.?\/?snapshots\//, "");
    return `${API_BASE}/snapshots/${encodeURIComponent(filename)}`;
  }

  function departmentName(id) {
    if (!id) {
      return "-";
    }
    return departments.find((department) => department.id === id)?.name || id;
  }

  function renderDepartments() {
    if (!departmentListEl) return;
    departmentListEl.innerHTML = departments.length
      ? departments.map((department) => `
          <div class="face">
            <div class="row">
              <div>
                <strong>${department.name}</strong>
                <div class="small">${department.description || ""}</div>
              </div>
              <div class="actions-inline">
                <button data-department-edit="${department.id}" title="Edit Department" class="btn-icon-action btn-edit">${EDIT_ICON_HTML}</button>
                <button data-department-delete="${department.id}" title="Delete Department" class="btn-icon-action btn-delete">${DELETE_ICON_HTML}</button>
              </div>
            </div>
          </div>
        `).join("")
      : '<div class="small">No departments yet.</div>';
    departmentListEl.querySelectorAll("[data-department-edit]").forEach((button) => {
      button.addEventListener("click", () => {
        const department = departments.find((item) => item.id === button.getAttribute("data-department-edit"));
        if (!department || !departmentFormEl) return;
        departmentFormEl.elements.namedItem("id").value = department.id;
        departmentFormEl.elements.namedItem("name").value = department.name;
        departmentFormEl.elements.namedItem("description").value = department.description || "";
      });
    });
    departmentListEl.querySelectorAll("[data-department-delete]").forEach((button) => {
      button.addEventListener("click", async () => {
        await postJson(`${API_BASE}/departments/${encodeURIComponent(button.getAttribute("data-department-delete"))}`, null, "DELETE");
        await loadDepartments();
      });
    });
  }

  function renderEmployees() {
    if (!employeeListEl) return;
    employeeListEl.innerHTML = employees.length
      ? employees.map((employee) => `
          <div class="face">
            <div class="row">
              <div>
                <strong>${employee.name}</strong>
                <div class="small">${employee.employee_code || ""} ${employee.role || ""}</div>
                <div class="small">Access: ${(employee.departments || []).map(departmentName).join(", ") || "-"}</div>
                <div class="small">Photos: ${employee.photoCount || 0} · ${employee.active ? "Active" : "Inactive"}</div>
              </div>
              <div class="actions-inline">
                <button data-employee-edit="${employee.id}" title="Edit Employee" class="btn-icon-action btn-edit">${EDIT_ICON_HTML}</button>
                <button data-employee-delete="${employee.id}" title="Delete Employee" class="btn-icon-action btn-delete">${DELETE_ICON_HTML}</button>
              </div>
            </div>
          </div>
        `).join("")
      : '<div class="small">No employees yet.</div>';
    employeeListEl.querySelectorAll("[data-employee-edit]").forEach((button) => {
      button.addEventListener("click", () => {
        const employee = employees.find((item) => item.id === button.getAttribute("data-employee-edit"));
        if (!employee || !employeeFormEl) return;
        employeeFormEl.elements.namedItem("id").value = employee.id;
        employeeFormEl.elements.namedItem("name").value = employee.name;
        employeeFormEl.elements.namedItem("employeeCode").value = employee.employee_code || "";
        employeeFormEl.elements.namedItem("role").value = employee.role || "";
        employeeFormEl.elements.namedItem("active").checked = Boolean(employee.active);
        Array.from(employeeDepartmentSelectEl?.options || []).forEach((option) => {
          option.selected = (employee.departments || []).includes(option.value);
        });
      });
    });
    employeeListEl.querySelectorAll("[data-employee-delete]").forEach((button) => {
      button.addEventListener("click", async () => {
        await postJson(`${API_BASE}/employees/${encodeURIComponent(button.getAttribute("data-employee-delete"))}`, null, "DELETE");
        await loadEmployees();
      });
    });
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
        (row) => {
          const firstSnapshot = snapshotUrl(row.first_snapshot_path);
          const lastSnapshot = snapshotUrl(row.last_snapshot_path);
          return `
          <div class="attendance-row">
            <div class="row">
              <div>
                <div><strong>${row.label}</strong></div>
                <div style="font-size: 16px">Appearances: ${row.appearances}</div>
              </div>
              <div class="pill">${formatPercent(row.max_confidence)}</div>
            </div>
            <div class="columns-2">
              <div>
                <div style="font-size: 16px" class="small">First appearance: ${formatDateTime(row.first_appearance)}</div>
                <div style="font-size: 16px" class="small">Check in role: ${formatRole(row.first_camera_role)}</div>
                <div style="font-size: 16px" class="small">Camera: ${row.first_camera_name || row.first_camera_id || "-"}</div>
                <div style="font-size: 16px" class="small">Department: ${row.first_department_name || row.first_department_id || "-"}</div>
                <div class="small">Snapshot: ${firstSnapshot ? `<a href="${firstSnapshot}" target="_blank" rel="noreferrer">Open</a>` : "-"}</div>
              </div>
              <div>
                <div style="font-size: 16px" class="small">Last appearance: ${formatDateTime(row.last_appearance)}</div>
                <div style="font-size: 16px" class="small">Check out role: ${formatRole(row.last_camera_role)}</div>
                <div style="font-size: 16px" class="small">Camera: ${row.last_camera_name || row.last_camera_id || "-"}</div>
                <div style="font-size: 16px" class="small">Department: ${row.last_department_name || row.last_department_id || "-"}</div>
                <div class="small">Snapshot: ${lastSnapshot ? `<a href="${lastSnapshot}" target="_blank" rel="noreferrer">Open</a>` : "-"}</div>
              </div>
            </div>
            <div style="font-size: 16px" class="small">Last confidence: ${formatPercent(row.last_confidence)} · Max confidence: ${formatPercent(row.max_confidence)}</div>
            <div class="small">Raw first: ${row.first_appearance}</div>
            <div class="small">Raw last: ${row.last_appearance}</div>
          </div>
        `;
        },
      )
      .join("");
  }

  async function fetchStatus() {
    latestStatus = await fetchJson(`${API_BASE}/status`);
    const faces = latestStatus?.lastFaces || [];
    const known = faces.find((face) => face?.match?.label);
    if (recognitionTextEl) {
      recognitionTextEl.textContent = known
        ? `Known: ${known.match.label}`
        : "Unknown";
    }
    if (recognitionDotEl) {
      recognitionDotEl.className = `match-dot ${known ? "known" : ""}`;
    }
    if (knownCountEl) {
      knownCountEl.textContent = `${latestStatus?.registeredFaces || 0} registered face${(latestStatus?.registeredFaces || 0) === 1 ? "" : "s"}`;
    }
    renderState();
    renderFacesList();
    drawServerDetections();
    updateCameraWallStatus();
  }

  async function loadCameras() {
    if (!cameraSelectEl) {
      return;
    }
    const payload = await fetchJson(`${API_BASE}/cameras`);
    cameras = payload.cameras || [];
    renderCameras();
    renderCameraWall();
    refreshMainStream();
  }

  async function loadDepartments() {
    if (!departmentListEl && !cameraDepartmentSelectEl && !employeeDepartmentSelectEl) {
      return;
    }
    const payload = await fetchJson(`${API_BASE}/departments`);
    departments = payload.departments || [];
    renderDepartments();
    renderCameras();
    renderEmployees();
  }

  async function loadEmployees() {
    if (!employeeListEl) {
      return;
    }
    const payload = await fetchJson(`${API_BASE}/employees`);
    employees = payload.employees || [];
    renderEmployees();
  }

  async function loadSyncStatus() {
    syncState = await fetchJson(`${API_BASE}/sync/status`);
    renderSync();
  }

  async function loadAttendance() {
    if (!attendanceListEl) {
      return;
    }
    const payload = await fetchJson(`${API_BASE}/attendance`);
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

  async function fetchJson(url, options = {}) {
    const response = await fetch(url, {
      cache: "no-store",
      ...options,
    });
    if (!response.ok) {
      throw new Error(`Request failed: ${response.status}`);
    }
    return await response.json();
  }

  async function fileToDataUrl(file) {
    return await new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(String(reader.result || ""));
      reader.onerror = () => reject(new Error(`Unable to read ${file.name}`));
      reader.readAsDataURL(file);
    });
  }

  async function autoStartIfNeeded() {
    if (!isLivePage) {
      return;
    }
    try {
      await postJson(`${API_BASE}/start`, {
        cameraId: activeCameraId(),
        cameraRole: activeCameraRole(),
      });
    } catch {
      // best-effort startup only
    }
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

  if (isLivePage && cameraSelectEl) {
    cameraSelectEl.addEventListener("change", refreshMainStream);
  }

  if (isLivePage && cameraRoleEl) {
    cameraRoleEl.addEventListener("change", refreshMainStream);
  }

  if (isLivePage && stopBtn) {
    stopBtn.addEventListener("click", async () => {
      await postJson(`${API_BASE}/stop`);
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
        departmentId: String(formData.get("departmentId") || "").trim() || null,
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

  if (isAdminPage && departmentFormEl) {
    departmentFormEl.addEventListener("submit", async (event) => {
      event.preventDefault();
      const formData = new FormData(departmentFormEl);
      const payload = {
        id: String(formData.get("id") || "").trim() || undefined,
        name: String(formData.get("name") || "").trim(),
        description: String(formData.get("description") || "").trim() || null,
      };

      if (!payload.name) {
        alert("Department name is required.");
        return;
      }

      if (payload.id) {
        await postJson(
          `${API_BASE}/departments/${encodeURIComponent(payload.id)}`,
          payload,
          "PUT",
        );
      } else {
        await postJson(`${API_BASE}/departments`, payload);
      }
      departmentFormEl.reset();
      await Promise.all([loadDepartments(), loadCameras()]);
    });
  }

  if (isAdminPage && employeeFormEl) {
    employeeFormEl.addEventListener("submit", async (event) => {
      event.preventDefault();
      const formData = new FormData(employeeFormEl);
      const selectedDepartments = Array.from(employeeDepartmentSelectEl?.selectedOptions || [])
        .map((option) => option.value)
        .filter(Boolean);
      const payload = {
        id: String(formData.get("id") || "").trim() || undefined,
        name: String(formData.get("name") || "").trim(),
        employeeCode: String(formData.get("employeeCode") || "").trim() || null,
        role: String(formData.get("role") || "").trim() || null,
        active: formData.get("active") === "on",
        departmentIds: selectedDepartments,
      };

      if (!payload.name) {
        alert("Employee name is required.");
        return;
      }

      let result;
      if (payload.id) {
        result = await postJson(
          `${API_BASE}/employees/${encodeURIComponent(payload.id)}`,
          payload,
          "PUT",
        );
      } else {
        result = await postJson(`${API_BASE}/employees`, payload);
      }

      const employeeId = result.employee?.id || payload.id;
      const files = Array.from(employeeFormEl.elements.namedItem("photos")?.files || []);
      if (employeeId && files.length) {
        const photos = await Promise.all(files.map(fileToDataUrl));
        await postJson(`${API_BASE}/employees/${encodeURIComponent(employeeId)}/photos`, {
          photos,
        });
      }

      employeeFormEl.reset();
      Array.from(employeeDepartmentSelectEl?.options || []).forEach((option) => {
        option.selected = false;
      });
      await loadEmployees();
    });
  }

  if (isAdminPage && cleanupFacesBtn) {
    cleanupFacesBtn.addEventListener("click", async () => {
      await postJson(`${API_BASE}/employees/cleanup-orphan-faces`);
      await loadEmployees();
      alert("Old non-employee face samples removed.");
    });
  }

  if (isLivePage && stream) {
    stream.addEventListener("load", drawServerDetections);
  }
  if (isLivePage) {
    window.addEventListener("resize", drawServerDetections);
    window.addEventListener("beforeunload", () => {
      if (stream) {
        stream.removeAttribute("src");
      }
      cameraWallEl?.querySelectorAll("[data-camera-stream]").forEach((node) => {
        if (node instanceof HTMLImageElement) {
          node.removeAttribute("src");
        }
      });
      try {
        liveSocket?.close();
      } catch {
        // ignore unload close failures
      }
    });
  }

  async function poll() {
    if (pollInFlight) {
      return;
    }
    pollInFlight = true;
    try {
      const tasks = [];
      if (isLivePage) {
        tasks.push(fetchStatus());
      }
      if (isAdminPage) {
        tasks.push(loadSyncStatus(), loadAttendance());
      }
      await Promise.allSettled(tasks);
    } finally {
      pollInFlight = false;
    }
  }

  const bootTasks = [loadSyncStatus()];
  if (isLivePage) {
    bootTasks.push(fetchStatus(), loadDepartments(), loadCameras(), autoStartIfNeeded());
  }
  if (isAdminPage) {
    bootTasks.push(loadAttendance(), loadDepartments(), loadEmployees(), loadCameras());
  }
  void Promise.allSettled(bootTasks).then(() => {
    if (isLivePage) {
      refreshMainStream();
      connectLiveSocket();
    }
    poll();
    if (isLivePage) {
      statusTimer = window.setInterval(fetchStatus, 15000);
    }
    if (isAdminPage) {
      syncTimer = window.setInterval(loadSyncStatus, 15000);
      adminTimer = window.setInterval(loadAttendance, 10000);
    }
  });
})();
