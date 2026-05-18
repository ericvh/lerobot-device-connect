/** LeRobot web teleop client */

const KEY_MAP = {
  w: "forward",
  s: "backward",
  a: "left",
  d: "right",
  q: "rotate_left",
  e: "rotate_right",
};

const NUDGE_STEP = 2.0;
let activeDirections = new Set();
let pressedKeys = new Set();

async function api(path, options = {}) {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new Error(data.detail || data.reason || res.statusText);
  }
  if (data.status === "error") {
    throw new Error(data.reason || "request failed");
  }
  return data;
}

function setStatus(text, ok = true) {
  const el = document.getElementById("status-line");
  el.textContent = text;
  el.style.color = ok ? "var(--success)" : "var(--danger)";
}

async function refreshStatus() {
  try {
    const conn = await api("/api/connection");
    const status = await api("/api/status");
    const features = await api("/api/features");
    setStatus(
      `${conn.mode} · ${features.robot_kind} (${features.robot_id}) · robot connected: ${
        status.connected ? "yes" : "no"
      }`,
      status.connected !== false,
    );
  } catch (err) {
    setStatus(`Error: ${err.message}`, false);
  }
}

async function setupCameras() {
  let cameras = [];
  try {
    const result = await api("/api/cameras");
    cameras = result.cameras || [];
  } catch {
    return;
  }

  for (const name of ["front", "wrist"]) {
    const panel = document.getElementById(`panel-${name}`);
    const img = document.getElementById(`cam-${name}`);
    const placeholder = panel.querySelector(".cam-placeholder");
    if (!cameras.includes(name)) {
      img.hidden = true;
      placeholder.hidden = false;
      continue;
    }
    placeholder.hidden = true;
    img.hidden = false;
    img.src = `/api/cameras/${name}/stream.mjpg?t=${Date.now()}`;
    img.onerror = () => {
      img.hidden = true;
      placeholder.textContent = `${name} stream unavailable`;
      placeholder.hidden = false;
    };
  }
}

async function driveActive() {
  const keys = [...activeDirections];
  if (keys.length === 0) {
    await api("/api/base/stop", { method: "POST" });
    return;
  }
  if (keys.length === 1 && keys[0] === "stop") {
    await api("/api/base/stop", { method: "POST" });
    return;
  }
  if (keys.length === 1) {
    await api("/api/base/drive", {
      method: "POST",
      body: JSON.stringify({ direction: keys[0] }),
    });
    return;
  }
  await api("/api/base/drive-keys", {
    method: "POST",
    body: JSON.stringify({ keys }),
  });
}

function setDirection(dir, on) {
  if (on) {
    if (dir === "stop") {
      activeDirections.clear();
      activeDirections.add("stop");
    } else {
      activeDirections.delete("stop");
      activeDirections.add(dir);
    }
  } else {
    activeDirections.delete(dir);
  }
  driveActive().catch((err) => setStatus(`Drive error: ${err.message}`, false));
}

function setupBaseControls() {
  document.querySelectorAll("button[data-speed]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const level = Number(btn.dataset.speed);
      document.querySelectorAll("button[data-speed]").forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      try {
        await api(`/api/base/speed/${level}`, { method: "POST" });
      } catch (err) {
        setStatus(`Speed error: ${err.message}`, false);
      }
    });
  });
  document.querySelector("button[data-speed='1']")?.classList.add("active");

  document.querySelectorAll("button.drive").forEach((btn) => {
    const dir = btn.dataset.dir;
    const press = () => {
      btn.classList.add("pressed");
      setDirection(dir, true);
    };
    const release = () => {
      btn.classList.remove("pressed");
      setDirection(dir, false);
    };
    btn.addEventListener("mousedown", (e) => {
      e.preventDefault();
      press();
    });
    btn.addEventListener("mouseup", release);
    btn.addEventListener("mouseleave", release);
    btn.addEventListener("touchstart", (e) => {
      e.preventDefault();
      press();
    });
    btn.addEventListener("touchend", release);
    btn.addEventListener("touchcancel", release);
  });

  window.addEventListener("keydown", (e) => {
    if (e.repeat || e.target.matches("input")) return;
    const dir = KEY_MAP[e.key.toLowerCase()];
    if (!dir || pressedKeys.has(e.key)) return;
    pressedKeys.add(e.key);
    setDirection(dir, true);
  });

  window.addEventListener("keyup", (e) => {
    const dir = KEY_MAP[e.key.toLowerCase()];
    if (!dir) return;
    pressedKeys.delete(e.key);
    setDirection(dir, false);
  });

  window.addEventListener("blur", () => {
    pressedKeys.clear();
    activeDirections.clear();
    api("/api/base/stop", { method: "POST" }).catch(() => {});
  });
}

function sliderRange(joint) {
  return joint === "arm_gripper" ? { min: 0, max: 100, step: 1 } : { min: -100, max: 100, step: 0.5 };
}

async function setupArmControls() {
  const container = document.getElementById("arm-sliders");
  let config;
  let positions;
  try {
    config = await api("/api/arm/config");
    const pos = await api("/api/arm/positions");
    positions = pos.positions || {};
  } catch (err) {
    container.innerHTML = `<p class="hint">${err.message}</p>`;
    return;
  }

  for (const joint of config.joints) {
    const short = joint.replace(/^arm_/, "");
    const range = sliderRange(joint);
    const value = positions[joint] ?? 0;

    const row = document.createElement("div");
    row.className = "arm-row";
    row.innerHTML = `
      <label for="slider-${short}">${short}</label>
      <span class="value" id="val-${short}">${value.toFixed(1)}</span>
      <button type="button" class="nudge" data-joint="${short}" data-delta="-1">−</button>
      <button type="button" class="nudge" data-joint="${short}" data-delta="1">+</button>
      <input type="range" id="slider-${short}" min="${range.min}" max="${range.max}" step="${range.step}" value="${value}" />
    `;
    container.appendChild(row);

    const slider = row.querySelector("input");
    const valEl = row.querySelector(".value");
    let debounce;

    const applyPosition = async (pos) => {
      try {
        await api("/api/arm/joint", {
          method: "POST",
          body: JSON.stringify({ joint: short, position: pos }),
        });
        valEl.textContent = pos.toFixed(1);
      } catch (err) {
        setStatus(`Arm error: ${err.message}`, false);
      }
    };

    slider.addEventListener("input", () => {
      valEl.textContent = Number(slider.value).toFixed(1);
      clearTimeout(debounce);
      debounce = setTimeout(() => applyPosition(Number(slider.value)), 120);
    });

    row.querySelectorAll(".nudge").forEach((btn) => {
      btn.addEventListener("click", async () => {
        const delta = NUDGE_STEP * Number(btn.dataset.delta);
        try {
          const result = await api("/api/arm/joint", {
            method: "POST",
            body: JSON.stringify({ joint: short, delta }),
          });
          const p = result.positions?.[`arm_${short}`] ?? result.positions?.[joint];
          if (p !== undefined) {
            slider.value = p;
            valEl.textContent = p.toFixed(1);
          }
        } catch (err) {
          setStatus(`Arm error: ${err.message}`, false);
        }
      });
    });
  }
}

async function init() {
  setupBaseControls();
  await refreshStatus();
  await setupCameras();
  await setupArmControls();
  setInterval(refreshStatus, 5000);
}

init().catch((err) => setStatus(`Init failed: ${err.message}`, false));
