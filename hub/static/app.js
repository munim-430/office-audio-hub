/**
 * Keystone Office Audio Hub — Web Dashboard Controller
 * Real-time Web Audio API streaming player, VU meters, and 90-min chunk browser.
 */

// Global State
let audioContext = null;
let liveGainNode = null;
let isListening = false;
let currentLiveDevice = null;
let dashboardSocket = null;
let pairingCountdownTimer = null;
let audioQueue = [];
let isPlayingQueue = false;

// Audio Configuration
const SAMPLE_RATE = 48000;
let nextPlayTime = 0;

// Initialize on Load
document.addEventListener("DOMContentLoaded", async () => {
  setupEventListeners();
  await checkAuthStatus();
  initWebSocket();
  loadChunks();
  setInterval(refreshTelemetry, 2000);
});

function setupEventListeners() {
  document.getElementById("btnPairDevice").addEventListener("click", openPairingModal);
  document.getElementById("btnClosePairingModal").addEventListener("click", closePairingModal);
  document.getElementById("btnRegenerateCode").addEventListener("click", regeneratePairingCode);
  document.getElementById("btnCopyCode").addEventListener("click", copyPairingCode);
  document.getElementById("btnStopLive").addEventListener("click", stopLiveListening);
  document.getElementById("btnRefreshChunks").addEventListener("click", loadChunks);
  document.getElementById("chunkFilterDevice").addEventListener("change", loadChunks);
  document.getElementById("chunkFilterDate").addEventListener("change", loadChunks);
  document.getElementById("btnLogout").addEventListener("click", handleLogout);
  document.getElementById("authForm").addEventListener("submit", handleAuthSubmit);

  const volSlider = document.getElementById("liveVolumeSlider");
  volSlider.addEventListener("input", (e) => {
    if (liveGainNode) {
      liveGainNode.gain.value = parseFloat(e.target.value);
    }
  });
}

// --- Authentication ---

async function checkAuthStatus() {
  try {
    const res = await fetch("/api/auth/status");
    const data = await res.json();
    if (!data.is_authenticated) {
      showAuthModal(!data.has_password);
    }
  } catch (e) {
    console.error("Auth check failed:", e);
  }
}

function showAuthModal(isFirstRun) {
  const modal = document.getElementById("authModal");
  const title = document.getElementById("authModalTitle");
  const subtitle = document.getElementById("authModalSubtitle");
  modal.classList.remove("hidden");
  if (isFirstRun) {
    title.innerText = "Setup Manager Password";
    subtitle.innerText = "Create an admin password to secure the console.";
  } else {
    title.innerText = "Manager Authentication";
    subtitle.innerText = "Enter your password to unlock the console.";
  }
}

async function handleAuthSubmit(e) {
  e.preventDefault();
  const password = document.getElementById("adminPasswordInput").value.trim();
  const errorMsg = document.getElementById("authErrorMsg");
  errorMsg.classList.add("hidden");

  try {
    const statusRes = await fetch("/api/auth/status");
    const statusData = await statusRes.json();
    const endpoint = !statusData.has_password ? "/api/auth/setup" : "/api/auth/login";

    const res = await fetch(endpoint, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ password })
    });

    if (res.ok) {
      document.getElementById("authModal").classList.add("hidden");
      document.getElementById("adminPasswordInput").value = "";
      refreshTelemetry();
      loadChunks();
    } else {
      const err = await res.json();
      errorMsg.innerText = err.detail || "Authentication failed.";
      errorMsg.classList.remove("hidden");
    }
  } catch (err) {
    errorMsg.innerText = "Network error. Try again.";
    errorMsg.classList.remove("hidden");
  }
}

async function handleLogout() {
  await fetch("/api/auth/logout", { method: "POST" });
  window.location.reload();
}

// --- WebSocket Connection ---

function initWebSocket() {
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  const wsUrl = `${protocol}//${window.location.host}/ws/dashboard`;

  dashboardSocket = new WebSocket(wsUrl);

  dashboardSocket.onopen = () => {
    document.getElementById("liveConnectionBadge").innerHTML = `
      <span class="w-2 h-2 rounded-full bg-emerald-400 animate-pulse"></span>
      <span>Hub Online</span>
    `;
    refreshTelemetry();
  };

  dashboardSocket.onclose = () => {
    document.getElementById("liveConnectionBadge").innerHTML = `
      <span class="w-2 h-2 rounded-full bg-red-500"></span>
      <span>Disconnected</span>
    `;
    setTimeout(initWebSocket, 3000);
  };

  dashboardSocket.onmessage = (event) => {
    try {
      const data = JSON.parse(event.data);
      if (data.type === "telemetry") {
        renderDeviceGrid(data.devices);
      } else if (data.type === "audio" && isListening && data.device_id === currentLiveDevice) {
        handleIncomingLiveAudio(data);
      }
    } catch (e) {
      console.error("WS Parse error:", e);
    }
  };
}

function refreshTelemetry() {
  if (dashboardSocket && dashboardSocket.readyState === WebSocket.OPEN) {
    dashboardSocket.send(JSON.stringify({ action: "get_telemetry" }));
  }
}

// --- Device Rendering ---

function renderDeviceGrid(devices) {
  const grid = document.getElementById("deviceGrid");
  const countEl = document.getElementById("workstationsCount");
  const filterSelect = document.getElementById("chunkFilterDevice");
  
  countEl.innerText = `${devices.length} paired`;

  // Update filter dropdown
  const currentFilter = filterSelect.value;
  let optionsHtml = '<option value="">All Workstations</option>';
  devices.forEach(d => {
    optionsHtml += `<option value="${d.device_id}" ${d.device_id === currentFilter ? "selected" : ""}>${d.name} (${d.device_id})</option>`;
  });
  filterSelect.innerHTML = optionsHtml;

  if (devices.length === 0) {
    grid.innerHTML = `
      <div class="col-span-full p-8 rounded-xl border border-slate-800 bg-slate-900/40 text-center text-slate-500 text-sm">
        No employee laptops paired yet. Click <strong>➕ Pair Employee Laptop</strong> to get started.
      </div>
    `;
    return;
  }

  grid.innerHTML = devices.map(d => {
    const isLive = isListening && currentLiveDevice === d.device_id;
    const micPercent = Math.min(100, Math.round(d.mic_level * 150)); // Scale for visibility
    const lastSeenText = d.is_online ? "Active Now" : formatLastSeen(d.last_seen);

    return `
      <div class="p-5 rounded-xl border ${d.is_online ? 'border-slate-800 bg-slate-900/60' : 'border-slate-800/60 bg-slate-950/40 opacity-75'} card-hover space-y-4">
        <div class="flex items-center justify-between">
          <div class="flex items-center space-x-2.5">
            <span class="w-2.5 h-2.5 rounded-full ${d.is_online ? 'bg-emerald-400 animate-pulse' : 'bg-slate-600'}"></span>
            <div>
              <h3 class="font-semibold text-white text-sm tracking-tight">${d.name}</h3>
              <p class="text-xs text-slate-400 font-mono">${d.device_id}</p>
            </div>
          </div>
          <span class="text-xs px-2 py-0.5 rounded ${d.is_online ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20' : 'bg-slate-800 text-slate-400'}">
            ${d.is_online ? 'Connected' : 'Offline'}
          </span>
        </div>

        <!-- VU Microphone Meter -->
        <div class="space-y-1">
          <div class="flex justify-between text-xs text-slate-400">
            <span>Mic Activity</span>
            <span>${d.is_online ? micPercent + '%' : 'Idle'}</span>
          </div>
          <div class="w-full bg-slate-800 rounded-full h-1.5 overflow-hidden">
            <div class="vu-bar h-full ${micPercent > 60 ? 'bg-amber-400' : 'bg-emerald-400'}" style="width: ${d.is_online ? micPercent : 0}%"></div>
          </div>
        </div>

        <div class="pt-2 border-t border-slate-800/80 flex items-center justify-between text-xs">
          <span class="text-slate-400">${lastSeenText}</span>
          ${d.is_online ? `
            <button onclick="toggleLiveListen('${d.device_id}', '${d.name}')" class="px-3 py-1.5 rounded-lg ${isLive ? 'bg-red-600 hover:bg-red-500' : 'bg-emerald-600 hover:bg-emerald-500'} font-medium text-white transition flex items-center space-x-1">
              <span>${isLive ? '⏹️ Stop' : '🎧 Listen Live'}</span>
            </button>
          ` : `
            <span class="text-slate-400 italic">Offline</span>
          `}
        </div>
      </div>
    `;
  }).join("");
}

function formatLastSeen(ts) {
  if (!ts) return "Never";
  const diffSec = Math.floor(Date.now() / 1000 - ts);
  if (diffSec < 60) return `${diffSec}s ago`;
  if (diffSec < 3600) return `${Math.floor(diffSec / 60)}m ago`;
  return `${Math.floor(diffSec / 3600)}h ago`;
}

// --- Live Audio Player (Web Audio API) ---

function initAudioContext() {
  if (!audioContext) {
    const AudioCtx = window.AudioContext || window.webkitAudioContext;
    audioContext = new AudioCtx({ sampleRate: SAMPLE_RATE });
    liveGainNode = audioContext.createGain();
    liveGainNode.gain.value = parseFloat(document.getElementById("liveVolumeSlider").value);
    liveGainNode.connect(audioContext.destination);
  }
  if (audioContext.state === "suspended") {
    audioContext.resume();
  }
}

window.toggleLiveListen = function(deviceId, deviceName) {
  if (isListening && currentLiveDevice === deviceId) {
    stopLiveListening();
  } else {
    startLiveListening(deviceId, deviceName);
  }
};

function startLiveListening(deviceId, deviceName) {
  initAudioContext();
  isListening = true;
  currentLiveDevice = deviceId;
  nextPlayTime = audioContext.currentTime + 0.05; // 50ms initial jitter buffer

  document.getElementById("liveDeviceName").innerText = deviceName;
  document.getElementById("livePlayerBar").classList.remove("hidden");

  if (dashboardSocket && dashboardSocket.readyState === WebSocket.OPEN) {
    dashboardSocket.send(JSON.stringify({
      action: "subscribe_live",
      device_id: deviceId
    }));
  }
  refreshTelemetry();
}

function stopLiveListening() {
  isListening = false;
  currentLiveDevice = null;
  document.getElementById("livePlayerBar").classList.add("hidden");

  if (dashboardSocket && dashboardSocket.readyState === WebSocket.OPEN) {
    dashboardSocket.send(JSON.stringify({ action: "unsubscribe_live" }));
  }
  refreshTelemetry();
}

function handleIncomingLiveAudio(data) {
  if (!audioContext || !data.pcm_base64) return;

  // Convert hex to Int16Array
  const hex = data.pcm_base64;
  const byteCount = hex.length / 2;
  const buffer = new ArrayBuffer(byteCount);
  const uint8View = new Uint8Array(buffer);
  for (let i = 0; i < byteCount; i++) {
    uint8View[i] = parseInt(hex.substr(i * 2, 2), 16);
  }
  const int16Array = new Int16Array(buffer);

  // Convert Int16 PCM to Float32 [-1.0, 1.0]
  const float32 = new Float32Array(int16Array.length);
  for (let i = 0; i < int16Array.length; i++) {
    float32[i] = int16Array[i] / 32768.0;
  }

  // Create Web Audio Buffer
  const audioBuf = audioContext.createBuffer(1, float32.length, SAMPLE_RATE);
  audioBuf.getChannelData(0).set(float32);

  // Play frame seamlessly
  const source = audioContext.createBufferSource();
  source.buffer = audioBuf;
  source.connect(liveGainNode);

  const now = audioContext.currentTime;
  if (nextPlayTime < now) {
    nextPlayTime = now + 0.02; // Reset on underrun
  }
  source.start(nextPlayTime);
  nextPlayTime += audioBuf.duration;

  // Render visualizer
  drawVisualizerWave(float32);
}

function drawVisualizerWave(floatData) {
  const canvas = document.getElementById("liveVisualizer");
  const ctx = canvas.getContext("2d");
  const width = canvas.width;
  const height = canvas.height;

  ctx.fillStyle = "#0b0f19";
  ctx.fillRect(0, 0, width, height);

  ctx.lineWidth = 1.5;
  ctx.strokeStyle = "#10b981";
  ctx.beginPath();

  const sliceWidth = width / floatData.length;
  let x = 0;

  for (let i = 0; i < floatData.length; i += 4) {
    const v = floatData[i];
    const y = (v * height / 2) + (height / 2);
    if (i === 0) {
      ctx.moveTo(x, y);
    } else {
      ctx.lineTo(x, y);
    }
    x += sliceWidth * 4;
  }
  ctx.stroke();
}

// --- 90-Minute Chunk Archive ---

async function loadChunks() {
  const device = document.getElementById("chunkFilterDevice").value;
  const date = document.getElementById("chunkFilterDate").value;
  const listEl = document.getElementById("chunkList");

  let url = "/api/chunks?";
  if (device) url += `device_id=${encodeURIComponent(device)}&`;
  if (date) url += `date=${encodeURIComponent(date)}&`;

  try {
    const res = await fetch(url);
    if (!res.ok) throw new Error("Failed to load chunks");
    const chunks = await res.json();

    if (chunks.length === 0) {
      listEl.innerHTML = `
        <div class="p-8 rounded-xl border border-slate-800 bg-slate-900/30 text-center text-slate-500 text-xs">
          No 90-minute recordings found for the selected criteria.
        </div>
      `;
      return;
    }

    listEl.innerHTML = chunks.map(c => {
      const durMinutes = (c.duration_seconds / 60).toFixed(1);
      const sizeMb = (c.file_size_bytes / (1024 * 1024)).toFixed(2);
      const startTime = new Date(c.start_time * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
      const endTime = new Date(c.end_time * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });

      return `
        <div class="p-4 rounded-xl border border-slate-800 bg-slate-900/40 flex flex-col md:flex-row items-center justify-between gap-4">
          <div class="flex items-center space-x-3 w-full md:w-auto">
            <div class="w-8 h-8 rounded-lg bg-slate-800 flex items-center justify-center text-slate-300 text-xs font-mono">
              🎵
            </div>
            <div>
              <div class="flex items-center space-x-2">
                <span class="font-semibold text-white text-sm">${c.device_id}</span>
                <span class="text-xs px-2 py-0.5 rounded bg-slate-800 text-slate-300 font-mono">${c.date_str}</span>
              </div>
              <p class="text-xs text-slate-400">${startTime} &rarr; ${endTime} &bull; ${durMinutes} min &bull; ${sizeMb} MB &bull; ${c.frame_count.toLocaleString()} frames</p>
            </div>
          </div>

          <div class="flex items-center space-x-3 w-full md:w-auto justify-end">
            <audio controls preload="none" src="/api/chunks/${c.chunk_id}/wav" class="h-8 max-w-[220px] rounded"></audio>
            <a href="/api/chunks/${c.chunk_id}/wav" download="${c.chunk_id}.wav" class="px-2.5 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-xs text-slate-200 transition">
              💾 Download WAV
            </a>
          </div>
        </div>
      `;
    }).join("");

  } catch (e) {
    listEl.innerHTML = `<div class="p-4 text-xs text-red-400 text-center">Failed to load audio archive.</div>`;
  }
}

// --- 6-Digit Pairing Modal ---

async function openPairingModal() {
  document.getElementById("pairingModal").classList.remove("hidden");
  await fetchPairingCode();
}

function closePairingModal() {
  document.getElementById("pairingModal").classList.add("hidden");
  if (pairingCountdownTimer) clearInterval(pairingCountdownTimer);
}

async function fetchPairingCode() {
  try {
    const res = await fetch("/api/pairing/code");
    if (res.ok) {
      const data = await res.json();
      renderPairingCode(data.pairing_code, data.expires_in_seconds);
    }
  } catch (e) {
    console.error("Failed to fetch pairing code:", e);
  }
}

async function regeneratePairingCode() {
  try {
    const res = await fetch("/api/pairing/code/regenerate", { method: "POST" });
    if (res.ok) {
      const data = await res.json();
      renderPairingCode(data.pairing_code, data.expires_in_seconds);
    }
  } catch (e) {
    console.error("Failed to regenerate code:", e);
  }
}

function renderPairingCode(code, expiresIn) {
  document.getElementById("pairingCodeDisplay").innerText = code;
  let remaining = expiresIn;

  if (pairingCountdownTimer) clearInterval(pairingCountdownTimer);
  pairingCountdownTimer = setInterval(() => {
    remaining--;
    if (remaining <= 0) {
      clearInterval(pairingCountdownTimer);
      document.getElementById("pairingExpiryText").innerText = "Code expired. Generate a new one.";
    } else {
      const mins = Math.floor(remaining / 60);
      const secs = remaining % 60;
      document.getElementById("pairingExpiryText").innerText = `Expires in ${mins}:${secs < 10 ? '0' : ''}${secs}`;
    }
  }, 1000);
}

function copyPairingCode() {
  const code = document.getElementById("pairingCodeDisplay").innerText;
  navigator.clipboard.writeText(code);
  const btn = document.getElementById("btnCopyCode");
  btn.innerText = "✓ Copied!";
  setTimeout(() => { btn.innerText = "📋 Copy Code"; }, 2000);
}
