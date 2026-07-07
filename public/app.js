(function () {
  const API_BASE = window.location.origin;
  const stream = document.getElementById("stream");
  const canvas = document.getElementById("overlay");
  const ctx = canvas.getContext("2d");
  const stateEl = document.getElementById("state");
  const detectionsEl = document.getElementById("detections");
  const framesEl = document.getElementById("frames");
  const registeredCountEl = document.getElementById("registeredCount");
  const lastFaceEl = document.getElementById("lastFace");
  const facesEl = document.getElementById("faces");
  const rawEl = document.getElementById("raw");
  const startBtn = document.getElementById("startBtn");
  const stopBtn = document.getElementById("stopBtn");
  const registerBtn = document.getElementById("registerBtn");
  const clearBtn = document.getElementById("clearBtn");
  const personNameEl = document.getElementById("personName");
  const recognitionTextEl = document.getElementById("recognitionText");
  const recognitionDotEl = document.querySelector(".match-dot");
  const knownCountEl = document.getElementById("knownCount");

  let latestStatus = null;

  stream.crossOrigin = "anonymous";
  stream.src = `${API_BASE}/stream.mjpg`;

  function resizeCanvas() {
    const rect = stream.getBoundingClientRect();
    const dpr = window.devicePixelRatio || 1;
    canvas.width = rect.width * dpr;
    canvas.height = rect.height * dpr;
    canvas.style.width = `${rect.width}px`;
    canvas.style.height = `${rect.height}px`;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    return { width: rect.width, height: rect.height };
  }

  function renderState() {
    const state = latestStatus?.state || "idle";
    stateEl.textContent = state;
    stateEl.className = `pill ${state}`;
    detectionsEl.textContent = latestStatus?.detectionCount || 0;
    framesEl.textContent = `${latestStatus?.frames?.received || 0} / ${latestStatus?.frames?.accepted || 0}`;
    registeredCountEl.textContent = latestStatus?.registeredFaces || 0;
    const faces = latestStatus?.lastFaces || [];
    const known = faces.find((face) => face?.match?.label);
    lastFaceEl.textContent = known ? "Known" : faces.length ? "Unknown" : "-";
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
            <div>${JSON.stringify(face.box)}</div>
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

  async function fetchStatus() {
    const response = await fetch(`${API_BASE}/status`, { cache: "no-store" });
    latestStatus = await response.json();
    const faces = latestStatus?.lastFaces || [];
    const known = faces.find((face) => face?.match?.label);
    recognitionTextEl.textContent = known ? `Known: ${known.match.label}` : "Unknown";
    recognitionDotEl.className = `match-dot ${known ? "known" : ""}`;
    knownCountEl.textContent = `${latestStatus?.registeredFaces || 0} registered face${(latestStatus?.registeredFaces || 0) === 1 ? "" : "s"}`;
    renderState();
    renderFacesList();
    drawServerDetections();
  }

  async function postJson(url, body) {
    const response = await fetch(url, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: body ? JSON.stringify(body) : undefined,
    });

    if (!response.ok) {
      const payload = await response.json().catch(() => ({}));
      throw new Error(payload.error || payload.message || `Request failed: ${response.status}`);
    }

    return response.json().catch(() => ({}));
  }

  startBtn.addEventListener("click", async () => {
    await postJson(`${API_BASE}/start`);
    await fetchStatus();
  });

  stopBtn.addEventListener("click", async () => {
    await postJson(`${API_BASE}/stop`);
    await fetchStatus();
  });

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

  clearBtn.addEventListener("click", async () => {
    await postJson(`${API_BASE}/faces/clear`);
    await fetchStatus();
  });

  stream.addEventListener("load", drawServerDetections);
  window.addEventListener("resize", drawServerDetections);
  setInterval(fetchStatus, 1000);
  void fetchStatus();
})();
