// The Flight tab: the x500 in 3D beside PX4's console.
//
// Where the pose comes from:
// - the sensor device's flight trace (firmware with flight_trace): the aircraft's truth about every 10 ms of
//   virtual time, with each rotor's speed ("pose" messages);
// - otherwise PX4's own MAVLink telemetry (its estimate, a few times a second on TELEM1).
// Either way the samples are kept on their virtual time and drawn a little behind the newest one, interpolated
// between the two around the play head, so the motion is smooth whatever the rate and the batching of the data.
"use strict";

(() => {
  const $ = (id) => document.getElementById(id);
  const dark = matchMedia("(prefers-color-scheme: dark)").matches;

  // ---------------------------------------------------------------- frames
  // Hakoniwa's world (ROS: x north, y west, z up; body x forward, y left, z up) to three.js (x right, y up, z back),
  // the conversion of hakoniwa-threejs-drone's frame.js.
  const rosToThree = (x, y, z) => new THREE.Vector3(-y, z, -x);
  function rosRpyToQuaternion(roll, pitch, yaw) {
    const q = new THREE.Quaternion().setFromEuler(new THREE.Euler(roll, pitch, yaw, "ZYX"));
    return new THREE.Quaternion(-q.y, q.z, -q.x, q.w);
  }

  // ---------------------------------------------------------------- samples and the play head
  const DELAY = 0.15;          // s of virtual time the view stays behind the newest sample
  const samples = [];          // {t (virtual s), p: Vector3, q: Quaternion, rpm: [], duty: []}
  let traceSeen = false;       // the run gives the flight trace: MAVLink poses are not used
  let playT = null;            // the virtual time drawn
  let rate = 1;                // virtual s per wall s, estimated from the arrivals
  let lastArrival = null;      // {wall, t}

  function addSample(s) {
    if (samples.length && s.t <= samples[samples.length - 1].t) return;
    samples.push(s);
    while (samples.length > 4000) samples.shift();
    const wall = performance.now() / 1000;
    if (lastArrival && wall - lastArrival.wall > 0.2) {
      const observed = (s.t - lastArrival.t) / (wall - lastArrival.wall);
      if (observed > 0 && observed < 50) rate += (observed - rate) * 0.3;
      lastArrival = { wall, t: s.t };
    } else if (!lastArrival) {
      lastArrival = { wall, t: s.t };
    }
  }

  function advancePlayHead(dt) {
    if (!samples.length) return null;
    const newest = samples[samples.length - 1].t;
    const target = newest - DELAY * Math.max(1, rate);
    if (playT === null || Math.abs(target - playT) > 2 * Math.max(1, rate)) playT = target;
    // move at the estimated rate, and close the gap to the target gently: no jumps when a batch arrives
    playT += dt * rate + (target - playT) * Math.min(1, dt * 1.5);
    playT = Math.min(playT, newest);
    return playT;
  }

  function sampleAt(t) {
    const n = samples.length;
    if (!n) return null;
    if (t <= samples[0].t) return samples[0];
    if (t >= samples[n - 1].t) return samples[n - 1];
    let lo = 0, hi = n - 1;
    while (hi - lo > 1) { const mid = (lo + hi) >> 1; if (samples[mid].t <= t) lo = mid; else hi = mid; }
    const a = samples[lo], b = samples[hi];
    const k = (t - a.t) / (b.t - a.t);
    return {
      t,
      p: a.p.clone().lerp(b.p, k),
      q: a.q.clone().slerp(b.q, k),
      rpm: a.rpm.map((v, i) => v + ((b.rpm[i] ?? v) - v) * k),
      duty: a.duty.map((v, i) => v + ((b.duty[i] ?? v) - v) * k),
    };
  }

  // ---------------------------------------------------------------- scene
  const scene = new THREE.Scene();
  const SKY_TOP = dark ? "#0d1724" : "#5f8fc9", SKY_HORIZON = dark ? "#2a3646" : "#cfdbe6";
  scene.background = (() => {
    const c = document.createElement("canvas"); c.width = 2; c.height = 256;
    const g = c.getContext("2d"); const grad = g.createLinearGradient(0, 0, 0, 256);
    grad.addColorStop(0, SKY_TOP); grad.addColorStop(1, SKY_HORIZON);
    g.fillStyle = grad; g.fillRect(0, 0, 2, 256);
    return new THREE.CanvasTexture(c);
  })();
  scene.fog = new THREE.Fog(SKY_HORIZON, 30, 150);

  const camera = new THREE.PerspectiveCamera(45, 1, 0.05, 500);
  const renderer = new THREE.WebGLRenderer({ antialias: true });
  renderer.setPixelRatio(Math.min(2, devicePixelRatio));
  renderer.outputEncoding = THREE.sRGBEncoding;
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 0.85;
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = THREE.PCFSoftShadowMap;
  $("view3d").appendChild(renderer.domElement);

  scene.add(new THREE.HemisphereLight(0xdfeeff, 0x6a6255, 0.55));
  const sun = new THREE.DirectionalLight(0xfff4e0, 1.0);
  sun.castShadow = true;
  sun.shadow.mapSize.set(2048, 2048);
  Object.assign(sun.shadow.camera, { left: -4, right: 4, top: 4, bottom: -4, near: 0.5, far: 40 });
  sun.shadow.bias = -0.0005;
  scene.add(sun, sun.target);

  // the ground: concrete with a 1 m grid, so that speed and height read at a glance
  const ground = (() => {
    const c = document.createElement("canvas"); c.width = c.height = 256;
    const g = c.getContext("2d");
    g.fillStyle = dark ? "#3a3f45" : "#7d8580"; g.fillRect(0, 0, 256, 256);
    for (let i = 0; i < 1400; i++) {   // a little grain
      const v = Math.random() * 24 - 12; const base = dark ? 58 : 125;
      g.fillStyle = `rgb(${base + v},${base + v},${base + v - 3})`;
      g.fillRect(Math.random() * 256, Math.random() * 256, 2, 2);
    }
    g.strokeStyle = dark ? "rgba(255,255,255,0.10)" : "rgba(30,34,32,0.35)"; g.lineWidth = 3;
    g.strokeRect(0, 0, 256, 256);
    const tex = new THREE.CanvasTexture(c);
    tex.wrapS = tex.wrapT = THREE.RepeatWrapping;
    tex.repeat.set(300, 300);
    tex.anisotropy = renderer.capabilities.getMaxAnisotropy();
    tex.encoding = THREE.sRGBEncoding;
    const mesh = new THREE.Mesh(new THREE.PlaneGeometry(300, 300),
      new THREE.MeshStandardMaterial({ map: tex, roughness: 0.95 }));
    mesh.rotation.x = -Math.PI / 2;
    mesh.receiveShadow = true;
    return mesh;
  })();
  scene.add(ground);

  // a landing pad at the take-off point
  const pad = (() => {
    const c = document.createElement("canvas"); c.width = c.height = 512;
    const g = c.getContext("2d");
    g.fillStyle = "#2b2f36"; g.beginPath(); g.arc(256, 256, 250, 0, Math.PI * 2); g.fill();
    g.strokeStyle = "#f2c94c"; g.lineWidth = 16; g.beginPath(); g.arc(256, 256, 215, 0, Math.PI * 2); g.stroke();
    g.fillStyle = "#f5f5f5"; g.font = "bold 260px system-ui, sans-serif"; g.textAlign = "center"; g.textBaseline = "middle";
    g.fillText("H", 256, 270);
    const tex = new THREE.CanvasTexture(c); tex.encoding = THREE.sRGBEncoding;
    tex.anisotropy = renderer.capabilities.getMaxAnisotropy();
    const mesh = new THREE.Mesh(new THREE.CircleGeometry(0.9, 64),
      new THREE.MeshStandardMaterial({ map: tex, roughness: 0.8, transparent: true }));
    mesh.rotation.x = -Math.PI / 2;
    mesh.position.y = 0.003;
    mesh.receiveShadow = true;
    return mesh;
  })();
  scene.add(pad);

  // ---------------------------------------------------------------- the x500
  // Rotor positions and spin directions of hakoniwa-threejs-drone's config/drone_types-x500.json (ROS, m), in the
  // order of the aircraft's rotors and of PX4's motors 1 to 4.
  const ROTORS = [
    { pos: [0.1768, -0.1768, 0.02], ccw: true },
    { pos: [-0.1768, 0.1768, 0.02], ccw: true },
    { pos: [0.1768, 0.1768, 0.02], ccw: false },
    { pos: [-0.1768, -0.1768, 0.02], ccw: false },
  ];
  const drone = new THREE.Group();
  scene.add(drone);
  const rotors = ROTORS.map((r) => {
    const hub = new THREE.Group();
    hub.position.copy(rosToThree(...r.pos));
    drone.add(hub);
    // a faint disc that shows the spin, fading out as the rotor slows
    const disc = new THREE.Mesh(new THREE.CircleGeometry(0.127, 48),
      new THREE.MeshBasicMaterial({ color: dark ? 0xc9d6e3 : 0x2b3440, transparent: true, opacity: 0, depthWrite: false,
        side: THREE.DoubleSide }));
    disc.rotation.x = -Math.PI / 2;
    disc.position.y = 0.012;
    hub.add(disc);
    const blades = new THREE.Group();
    hub.add(blades);
    return { hub, blades, disc, ccw: r.ccw, angle: Math.random() * Math.PI * 2 };
  });

  function makeShadowy(object) {
    object.traverse((o) => { if (o.isMesh) { o.castShadow = true; o.receiveShadow = false; } });
  }

  function fallbackModel() {
    const mat = new THREE.MeshStandardMaterial({ color: 0x2c3138, roughness: 0.6 });
    const body = new THREE.Mesh(new THREE.BoxGeometry(0.14, 0.05, 0.14), mat);
    drone.add(body);
    ROTORS.forEach((r) => {
      const p = rosToThree(...r.pos);
      const arm = new THREE.Mesh(new THREE.BoxGeometry(0.02, 0.015, p.length() * 2), mat);
      arm.lookAt(p); arm.position.copy(p).multiplyScalar(0.5);
      drone.add(arm);
    });
    rotors.forEach((r) => r.blades.add(new THREE.Mesh(new THREE.BoxGeometry(0.25, 0.004, 0.02),
      new THREE.MeshStandardMaterial({ color: 0x111111 }))));
    makeShadowy(drone);
  }

  if (THREE.GLTFLoader) {
    const loader = new THREE.GLTFLoader();
    const load = (url) => new Promise((resolve, reject) => loader.load(url, (g) => resolve(g.scene), undefined, reject));
    Promise.all([load("/web/assets/x500/x500-frame.glb"), load("/web/assets/x500/base-drone-prop.glb")])
      .then(([frame, prop]) => {
        drone.add(frame);
        rotors.forEach((r) => {
          const p = prop.clone(true);
          p.scale.setScalar(0.858);
          r.blades.add(p);
        });
        makeShadowy(drone);
        window.studioModelsLoaded = "x500";
      })
      .catch((e) => {
        console.warn("x500 models not loaded, using a simple model", e);
        fallbackModel();
        window.studioModelsLoaded = "fallback";
      });
  } else {
    fallbackModel();
    window.studioModelsLoaded = "fallback";
  }

  // ---------------------------------------------------------------- camera: a chase view that follows smoothly
  const view = { azimuth: 0.6, elevation: 0.16, distance: 3.0 };   // rad from south, rad above, m
  const camTarget = new THREE.Vector3(0, 0.3, 0);
  let camInit = false;
  (() => {   // drag to turn around the vehicle, wheel to zoom
    const el = renderer.domElement;
    let drag = null;
    el.addEventListener("pointerdown", (e) => { drag = { x: e.clientX, y: e.clientY }; el.setPointerCapture(e.pointerId); });
    el.addEventListener("pointermove", (e) => {
      if (!drag) return;
      view.azimuth -= (e.clientX - drag.x) * 0.005;
      view.elevation = Math.min(1.4, Math.max(0.02, view.elevation + (e.clientY - drag.y) * 0.004));
      drag = { x: e.clientX, y: e.clientY };
    });
    el.addEventListener("pointerup", () => { drag = null; });
    el.addEventListener("wheel", (e) => {
      e.preventDefault();
      view.distance = Math.min(30, Math.max(1, view.distance * Math.exp(e.deltaY * 0.001)));
    }, { passive: false });
  })();

  function updateCamera(dt) {
    const k = 1 - Math.exp(-dt * 4);
    camTarget.lerp(drone.position, camInit ? k : 1);
    const offset = new THREE.Vector3(
      Math.sin(view.azimuth) * Math.cos(view.elevation),
      Math.sin(view.elevation),
      Math.cos(view.azimuth) * Math.cos(view.elevation)).multiplyScalar(view.distance);
    const wanted = camTarget.clone().add(offset);
    wanted.y = Math.max(0.15, wanted.y);
    if (camInit) camera.position.lerp(wanted, k); else camera.position.copy(wanted);
    camera.lookAt(camTarget);
    camInit = true;
    // the sun's shadow box follows the vehicle
    sun.position.copy(camTarget).add(new THREE.Vector3(4, 10, 3));
    sun.target.position.copy(camTarget);
  }

  function resize() {
    const box = $("view3d").getBoundingClientRect();
    if (box.width === 0) return;
    renderer.setSize(box.width, box.height);
    camera.aspect = box.width / box.height;
    camera.updateProjectionMatrix();
    fitFlightTerminal();
  }
  addEventListener("resize", resize);

  // ---------------------------------------------------------------- the HUD
  const SPIN_SCALE = 0.25;     // drawn spin per real spin: 5500 rpm turns a visible 5.7 rev/s
  let armedSpin = 0;           // with MAVLink only, no rotor speeds: spin while armed
  function updateHud(s) {
    if (!s) return;
    const alt = s.p.y;
    $("hud-time").textContent = `${s.t.toFixed(2)} s`;
    $("hud-alt").textContent = `${alt.toFixed(2)} m`;
    const rpm = s.rpm.length ? s.rpm : null;
    rotors.forEach((_, i) => {
      const bar = $(`hud-m${i + 1}`);
      if (!bar) return;
      const value = rpm ? rpm[i] || 0 : null;
      bar.querySelector("i").style.width = value === null ? "0" : `${Math.min(100, (value / 7000) * 100)}%`;
      bar.querySelector("b").textContent = value === null ? "-" : `${Math.round(value)}`;
      bar.classList.toggle("stopped", value !== null && value < 300 && s.rpm.some((v) => v > 2000));
    });
  }

  let banner = null;
  // a message's kind: alarm (red) for failures, warn (orange) for an injected fault, good (green) for steps done
  function kindOf(text) {
    if (/fail|failure|emergency|denied|abort/i.test(text)) return "alarm";
    if (/^fault:|stop motor/i.test(text)) return "warn";
    if (/^armed$|armed by|takeoff detected|landing detected|accepted|^route: |reached|restored/i.test(text)) return "good";
    return "";
  }
  function showBanner(text, kind) {
    const el = $("hud-banner");
    el.textContent = text;
    el.className = `${kind} show`;
    clearTimeout(banner);
    banner = setTimeout(() => { el.className = kind; }, kind === "alarm" ? 6000 : 3500);
  }

  // ---------------------------------------------------------------- the frame loop
  // for checks from the browser's console: the play head and the data's arrival
  window.studioFlight = { samples, get playT() { return playT; }, get rate() { return rate; } };

  // one picture: the vehicle at virtual time t (null: as it was), rotors and camera advanced by dt seconds
  function drawFrame(t, dt) {
    const s = t === null ? null : sampleAt(t);
    if (s) {
      drone.position.copy(s.p);
      drone.quaternion.copy(s.q);
      updateHud(s);
    }
    rotors.forEach((r, i) => {
      const rpm = s && s.rpm.length ? s.rpm[i] || 0 : armedSpin;
      const omega = (rpm / 60) * Math.PI * 2 * SPIN_SCALE;
      r.angle += (r.ccw ? 1 : -1) * omega * dt;
      r.blades.rotation.y = r.angle;
      r.disc.material.opacity = Math.min(0.22, (rpm / 5500) * 0.22);
    });
    updateCamera(dt);
    renderer.render(scene, camera);
  }

  const REPLAY = Boolean(window.STUDIO_REPLAY);   // web/replay.html: pictures on request, no live loop
  let lastFrame = performance.now();
  function frame(now) {
    const dt = Math.min(0.1, (now - lastFrame) / 1000);
    lastFrame = now;
    drawFrame(advancePlayHead(dt), dt);
    requestAnimationFrame(frame);
  }
  if (!REPLAY) requestAnimationFrame(frame);

  // ---------------------------------------------------------------- PX4's console beside the view
  const TERM_FONT = (window.STUDIO_REPLAY && window.STUDIO_REPLAY.fontSize) || 13;
  const fterm = new Terminal({ convertEol: true, fontSize: TERM_FONT, scrollback: 3000,
    theme: { background: "#0f1318", foreground: "#d6dde5" } });
  fterm.open($("flightterm"));
  function fitFlightTerminal() {
    const box = $("flightterm").getBoundingClientRect();
    if (box.width === 0) return;
    fterm.resize(Math.max(30, Math.floor(box.width / (TERM_FONT * 0.6))),
      Math.max(8, Math.floor(box.height / (TERM_FONT * 1.31))));
  }
  window.onConsole = (data) => fterm.write(data);
  window.onFlightTab = resize;

  // ---------------------------------------------------------------- the replay of a recorded run
  // replay.load(record) takes /api/record/<board>; replay.renderAt(t, dt) draws virtual time t: the console as
  // far as t, PX4's last status text for a few seconds after it came, rotors and camera advanced by dt.
  if (REPLAY) {
    let events = [];
    let written = 0;
    const writeAsync = (data) => new Promise((resolve) => fterm.write(data, resolve));
    window.replay = {
      view,
      load(record) {
        samples.length = 0;
        for (const [tUsec, x, y, z, roll, pitch, yaw, rpm, duty] of record.trace) {
          samples.push({ t: tUsec / 1e6, p: rosToThree(x, y, z), q: rosRpyToQuaternion(roll, pitch, yaw), rpm, duty });
        }
        events = record.timeline.slice().sort((a, b) => a.t - b.t);
        written = 0;
        fterm.reset();
        resize();
        camInit = false;
        return { first: samples[0]?.t, last: samples[samples.length - 1]?.t, events: events.length };
      },
      async renderAt(t, dt) {
        let text = "";
        while (written < events.length && events[written].t <= t) {
          if (events[written].type === "console") text += events[written].data;
          written += 1;
        }
        if (text) await writeAsync(text);
        const status = events.filter((e) => e.type === "flight_status" && e.text.startsWith("PX4: ") && e.t <= t
          && !/^PX4: (t\s*|\[logger\].*)$/.test(e.text)).pop();
        const el = $("hud-banner");
        if (status) {
          const message = status.text.slice(5).replace(/^Preflight Fail: /, "").trim();
          const alarm = /fail|failure|emergency|lost/i.test(message);
          const shown = t - status.t < (alarm ? 6 : 3);
          el.textContent = `PX4: ${message}`;
          el.className = (alarm ? "alarm" : "") + (shown ? " show" : "");
        } else {
          el.className = "";
        }
        drawFrame(t, dt);
        await new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)));
      },
    };
  }

  // ---------------------------------------------------------------- messages
  function log(text) {
    const box = $("flightlog");
    const line = document.createElement("span");
    line.className = kindOf(text);
    line.textContent = text + "\n";
    box.appendChild(line);
    box.scrollTop = box.scrollHeight;
  }

  window.onPose = (m) => {
    traceSeen = true;
    for (const [tUsec, x, y, z, roll, pitch, yaw, rpm, duty] of m.samples) {
      addSample({ t: tUsec / 1e6, p: rosToThree(x, y, z), q: rosRpyToQuaternion(roll, pitch, yaw), rpm, duty });
    }
  };

  let flying = false;
  window.onFlight = (m) => {
    if (m.type === "flight_status") {
      log(m.text);
      if (m.text.startsWith("PX4: ")) {
        const text = m.text.slice(5).replace(/^Preflight Fail: /, "");
        // ground-station link messages are noise here (the link is local)
        if (!/ground station lost|GCS connection regained/i.test(text)) showBanner(`PX4: ${text}`, kindOf(text));
      } else if (kindOf(m.text)) {
        showBanner(m.text.replace(/^take-off to ([\d.]+) m: accepted$/, "take-off to $1 m"), kindOf(m.text));
      }
      return;
    }
    $("hud-link").textContent = m.connected ? (m.armed ? `armed · ${m.mode || ""}` : `disarmed · ${m.mode || ""}`) : "connecting";
    $("takeoff").disabled = !(flying && m.connected && m.ready && !m.armed);
    $("land").disabled = !(flying && m.armed);
    armedSpin = m.armed ? 5000 : 0;
    // PX4's estimate, when there is no flight trace: NED / FRD to Hakoniwa's world
    if (!traceSeen && m.x !== undefined && m.time_boot_ms !== undefined) {
      const d2r = Math.PI / 180;
      addSample({ t: m.time_boot_ms / 1000, p: rosToThree(m.x, -m.y, Math.max(0, -m.z)),
        q: rosRpyToQuaternion((m.roll || 0) * d2r, -(m.pitch || 0) * d2r, -(m.yaw || 0) * d2r), rpm: [], duty: [] });
    }
  };

  window.onRunState = (m) => {
    flying = m.state === "running" && Boolean(m.flight);
    if (m.state === "running") {
      samples.length = 0; playT = null; rate = 1; lastArrival = null; traceSeen = false; camInit = false;
      drone.position.set(0, 0, 0); drone.quaternion.identity();
      fterm.reset();
      $("flightlog").replaceChildren();
      if (m.flight) log("PX4 is booting; the take-off button opens when PX4 reports its home position.");
    }
    if (!flying) { $("takeoff").disabled = true; $("land").disabled = true; }
  };

  const post = (path, body) => fetch(path, { method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body || {}) });
  $("takeoff").addEventListener("click", () => { $("takeoff").disabled = true; post("/api/flight/takeoff", { altitude: 2.5 }); });
  $("land").addEventListener("click", () => post("/api/flight/land"));

  // ---------------------------------------------------------------- the route (firmware with route)
  // Points are north/east metres from home (PX4's local frame); the map shows them north up, and the 3D
  // view draws them on the ground with the path between them.
  const MAP_M = 24;                     // the map's width in metres (home in the middle)
  const route = { points: [], index: -1, armed: false, faultAt: 0, faultMotor: 3 };
  window.studioRoute = route;   // for checks from the browser's console
  const routeGroup = new THREE.Group();
  scene.add(routeGroup);
  const neToThree = (north, east, up) => rosToThree(north, -east, up);   // ROS y is west
  function drawRoute3d() {
    routeGroup.clear();
    if (!route.points.length) return;
    // the path: flat bands 0.15 m wide on the ground (a line of one pixel is lost at a distance)
    const pts = [[0, 0], ...route.points].map(([n, e]) => neToThree(n, e, 0.03));
    const band = new THREE.MeshBasicMaterial({ color: 0x2f81f7, transparent: true, opacity: 0.85 });
    for (let i = 1; i < pts.length; i++) {
      const a = pts[i - 1], b = pts[i], len = a.distanceTo(b);
      if (len < 0.01) continue;
      const m = new THREE.Mesh(new THREE.BoxGeometry(0.15, 0.004, len), band);   // depth along local z
      m.position.set((a.x + b.x) / 2, 0.03, (a.z + b.z) / 2);
      m.lookAt(b.x, 0.03, b.z);
      routeGroup.add(m);
    }
    if (route.faultAt > 0 && route.faultAt <= route.points.length) {
      const [n, e] = route.points[route.faultAt - 1];
      const mark = new THREE.Mesh(new THREE.RingGeometry(0.5, 0.62, 40),
        new THREE.MeshBasicMaterial({ color: 0xf85149, side: THREE.DoubleSide }));
      mark.rotation.x = -Math.PI / 2;
      mark.position.copy(neToThree(n, e, 0.045));
      routeGroup.add(mark);
    }
    route.points.forEach(([n, e], i) => {
      const done = route.index > i;
      const ring = new THREE.Mesh(new THREE.RingGeometry(0.25, 0.4, 32),
        new THREE.MeshBasicMaterial({ color: done ? 0x3fb950 : (i === route.index ? 0xffc400 : 0x2f81f7),
          side: THREE.DoubleSide }));
      ring.rotation.x = -Math.PI / 2;
      ring.position.copy(neToThree(n, e, 0.04));
      routeGroup.add(ring);
    });
  }
  const map = $("routemap");
  const mapCtx = map.getContext("2d");
  let mapVehicle = null;                // [north, east] of the vehicle
  function mapXY(north, east) {
    const k = map.width / MAP_M;
    return [map.width / 2 + east * k, map.height / 2 - north * k];
  }
  function drawMap() {
    const c = mapCtx, w = map.width, k = w / MAP_M;
    c.clearRect(0, 0, w, w);
    for (let m = -MAP_M / 2; m <= MAP_M / 2; m++) {
      c.strokeStyle = m % 5 === 0 ? "rgba(255,255,255,0.28)" : "rgba(255,255,255,0.10)";
      c.beginPath(); c.moveTo(w / 2 + m * k, 0); c.lineTo(w / 2 + m * k, w); c.stroke();
      c.beginPath(); c.moveTo(0, w / 2 - m * k); c.lineTo(w, w / 2 - m * k); c.stroke();
    }
    c.fillStyle = "#aab6c3"; c.font = "11px system-ui"; c.fillText("N", w / 2 + 4, 12);
    if (route.points.length) {
      c.strokeStyle = "#2f81f7"; c.lineWidth = 2; c.beginPath();
      const [hx, hy] = mapXY(0, 0); c.moveTo(hx, hy);
      route.points.forEach(([n, e]) => { const [x, y] = mapXY(n, e); c.lineTo(x, y); });
      c.stroke(); c.lineWidth = 1;
      route.points.forEach(([n, e], i) => {
        const [x, y] = mapXY(n, e);
        c.fillStyle = route.index > i ? "#3fb950" : (i === route.index ? "#ffc400" : "#2f81f7");
        c.beginPath(); c.arc(x, y, 6, 0, Math.PI * 2); c.fill();
        c.fillStyle = "#fff"; c.fillText(String(i + 1), x + 8, y - 6);
        if (route.faultAt === i + 1) {
          c.strokeStyle = "#f85149"; c.lineWidth = 2;
          c.beginPath(); c.arc(x, y, 10, 0, Math.PI * 2); c.stroke(); c.lineWidth = 1;
          c.fillStyle = "#ff7b72"; c.fillText(`M${route.faultMotor} stops`, x + 8, y + 14);
        }
      });
    }
    const [hx, hy] = mapXY(0, 0);
    c.strokeStyle = "#ffc400"; c.strokeRect(hx - 5, hy - 5, 10, 10);   // home
    if (mapVehicle) {
      const [x, y] = mapXY(mapVehicle[0], mapVehicle[1]);
      c.fillStyle = "#ff7b72"; c.beginPath(); c.arc(x, y, 5, 0, Math.PI * 2); c.fill();
    }
  }
  function updateRouteButtons() {
    $("flyroute").disabled = !(flying && route.armed && route.points.length);
    const at = $("faultat");
    if (at.options.length !== route.points.length + 1) {
      const keep = Number(at.value);
      at.innerHTML = '<option value="0">none</option>' +
        route.points.map((_, i) => `<option value="${i + 1}">${i + 1}</option>`).join("");
      at.value = keep <= route.points.length ? String(keep) : "0";
    }
    route.faultAt = Number(at.value); route.faultMotor = Number($("faultmotor").value);
  }
  $("faultat").addEventListener("change", () => { updateRouteButtons(); drawMap(); drawRoute3d(); });
  $("faultmotor").addEventListener("change", () => { updateRouteButtons(); drawMap(); drawRoute3d(); });
  map.addEventListener("click", (e) => {
    const r = map.getBoundingClientRect(), k = map.width / MAP_M;
    const x = (e.clientX - r.left) * (map.width / r.width), y = (e.clientY - r.top) * (map.height / r.height);
    const north = Math.round(((map.height / 2 - y) / k) * 2) / 2, east = Math.round(((x - map.width / 2) / k) * 2) / 2;
    if (route.index >= 0 && route.index < route.points.length) return;   // flying a route: no edits
    if (route.index >= route.points.length) { route.points = []; route.index = -1; }
    route.points.push([north, east]);
    drawMap(); drawRoute3d(); updateRouteButtons();
  });
  $("clearroute").addEventListener("click", () => {
    route.points = []; route.index = -1; drawMap(); drawRoute3d(); updateRouteButtons();
  });
  // flying a route: pull the chase camera back and up, gently, so that the path on the ground shows
  function easeView(target, seconds) {
    const from = { ...view }, t0 = performance.now();
    const step = (now) => {
      const u = Math.min(1, (now - t0) / (seconds * 1000)), k = u * u * (3 - 2 * u);
      view.distance = from.distance + (target.distance - from.distance) * k;
      view.elevation = from.elevation + (target.elevation - from.elevation) * k;
      if (u < 1) requestAnimationFrame(step);
    };
    requestAnimationFrame(step);
  }
  $("flyroute").addEventListener("click", () => {
    route.index = 0; drawMap(); drawRoute3d();
    const fault = route.faultAt > 0 ? { motor: route.faultMotor, at: route.faultAt } : null;
    post("/api/flight/route", { points: route.points, altitude: 2.5, speed: 2.0, fault });
    easeView({ distance: Math.max(view.distance, 9), elevation: Math.max(view.elevation, 0.55) }, 2.0);
  });
  const onFlightBase = window.onFlight;
  window.onFlight = (m) => {
    onFlightBase(m);
    if (m.type !== "flight") return;
    route.armed = Boolean(m.armed);
    if (m.x !== undefined) mapVehicle = [m.x, m.y];
    if (m.route) { route.index = m.route.index; }
    updateRouteButtons(); drawMap(); drawRoute3d();
  };

  // ---------------------------------------------------------------- ESC faults (firmware with rotor_fault)
  const faultButtons = [...document.querySelectorAll("#faultbox button[data-motor]")];
  faultButtons.forEach((b) => b.addEventListener("click", () => post("/api/fault", { motor: Number(b.dataset.motor), stop: true })));
  $("restore").addEventListener("click", () => post("/api/fault", { scales: [1, 1, 1, 1] }));
  window.onFault = (m) => {
    faultButtons.forEach((b, i) => b.classList.toggle("on", (m.scales[i] ?? 1) <= 0));
  };

  const onRunStateBase = window.onRunState;
  window.onRunState = (m) => {
    onRunStateBase(m);
    if (m.state === "running") {
      $("routebox").hidden = !m.route;
      $("faultbox").hidden = !m.rotor_fault;
      route.points = []; route.index = -1; mapVehicle = null;
      faultButtons.forEach((b) => b.classList.remove("on"));
      drawMap(); drawRoute3d(); updateRouteButtons();
    }
  };
  drawMap();
})();
