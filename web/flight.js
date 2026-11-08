// The Flight tab: the x500 in 3D from PX4's MAVLink telemetry, its altitude, and take-off / land.
"use strict";

(() => {
  const $ = (id) => document.getElementById(id);
  const dark = matchMedia("(prefers-color-scheme: dark)").matches;
  let flying = false;          // a firmware with a MAVLink link is running
  let last = null;             // the latest telemetry
  const altitudes = [];        // [time_boot_s, altitude]

  // --- 3D: PX4's local frame is NED (x north, y east, z down); three.js is y up.
  const scene = new THREE.Scene();
  scene.background = new THREE.Color(dark ? 0x11151a : 0xeef2f6);
  const camera = new THREE.PerspectiveCamera(50, 1, 0.05, 200);
  const renderer = new THREE.WebGLRenderer({ antialias: true });
  $("view3d").appendChild(renderer.domElement);
  scene.add(new THREE.HemisphereLight(0xffffff, 0x445566, 1.0));
  const sun = new THREE.DirectionalLight(0xffffff, 0.6);
  sun.position.set(5, 10, 3);
  scene.add(sun);
  const grid = new THREE.GridHelper(40, 40, dark ? 0x4c5866 : 0x9aa6b2, dark ? 0x2d353f : 0xd0d7de);
  scene.add(grid);
  const north = new THREE.ArrowHelper(new THREE.Vector3(0, 0, -1), new THREE.Vector3(0, 0.01, 0), 2, 0xd1242f);
  scene.add(north);

  // an x500-like quad: 0.5 m motor-to-motor diagonal arms, four rotors
  const drone = new THREE.Group();
  const body = new THREE.Mesh(new THREE.BoxGeometry(0.16, 0.06, 0.16),
    new THREE.MeshStandardMaterial({ color: 0x1f6feb }));
  drone.add(body);
  const armMaterial = new THREE.MeshStandardMaterial({ color: 0x30363d });
  const rotorMaterial = new THREE.MeshStandardMaterial({ color: 0xfb8500, transparent: true, opacity: 0.8 });
  for (const angle of [45, 135, 225, 315]) {
    const a = (angle * Math.PI) / 180;
    const arm = new THREE.Mesh(new THREE.BoxGeometry(0.36, 0.02, 0.025), armMaterial);
    arm.position.set(Math.cos(a) * 0.18, 0, Math.sin(a) * 0.18);
    arm.rotation.y = -a;
    drone.add(arm);
    const rotor = new THREE.Mesh(new THREE.CylinderGeometry(0.12, 0.12, 0.01, 24), rotorMaterial);
    rotor.position.set(Math.cos(a) * 0.36, 0.04, Math.sin(a) * 0.36);
    drone.add(rotor);
  }
  const nose = new THREE.Mesh(new THREE.ConeGeometry(0.03, 0.08, 12), new THREE.MeshStandardMaterial({ color: 0xd1242f }));
  nose.rotation.x = -Math.PI / 2;
  nose.position.set(0, 0, -0.12);
  drone.add(nose);
  drone.position.y = 0.1;
  scene.add(drone);
  const shadow = new THREE.Mesh(new THREE.CircleGeometry(0.35, 24),
    new THREE.MeshBasicMaterial({ color: 0x000000, transparent: true, opacity: 0.15 }));
  shadow.rotation.x = -Math.PI / 2;
  shadow.position.y = 0.002;
  scene.add(shadow);

  function resize() {
    const box = $("view3d").getBoundingClientRect();
    if (box.width === 0) return;
    renderer.setSize(box.width, box.height);
    camera.aspect = box.width / box.height;
    camera.updateProjectionMatrix();
  }
  addEventListener("resize", resize);
  window.onFlightTab = resize;

  function render() {
    if (last && last.x !== undefined) {
      // NED -> three: x east, y up, z south
      drone.position.set(last.y, Math.max(0.1, -last.z + 0.1), -last.x);
      drone.rotation.set(0, 0, 0);
      const yaw = THREE.MathUtils.degToRad(last.yaw || 0);
      const pitch = THREE.MathUtils.degToRad(last.pitch || 0);
      const roll = THREE.MathUtils.degToRad(last.roll || 0);
      drone.rotation.order = "YXZ";
      drone.rotation.set(pitch, -yaw, -roll);
      shadow.position.set(drone.position.x, 0.002, drone.position.z);
    }
    camera.position.set(drone.position.x + 2.2, drone.position.y + 1.4, drone.position.z + 3.0);
    camera.lookAt(drone.position);
    renderer.render(scene, camera);
    requestAnimationFrame(render);
  }
  requestAnimationFrame(render);

  // --- telemetry, chart, buttons
  function row(name, value) { return `<tr><td>${name}</td><td>${value}</td></tr>`; }
  function fmt(v, digits = 2, unit = "") { return v === undefined ? "-" : `${v.toFixed(digits)}${unit}`; }

  function drawChart() {
    const c = $("altchart");
    const g = c.getContext("2d");
    g.clearRect(0, 0, c.width, c.height);
    if (altitudes.length < 2) return;
    const t1 = altitudes[altitudes.length - 1][0];
    const t0 = Math.max(altitudes[0][0], t1 - 60);
    const top = Math.max(3, ...altitudes.map((a) => a[1]));
    const x = (t) => ((t - t0) / Math.max(1, t1 - t0)) * (c.width - 4) + 2;
    const y = (h) => c.height - 4 - (h / top) * (c.height - 14);
    g.strokeStyle = dark ? "#2d353f" : "#d8dde3";
    g.setLineDash([3, 3]);
    g.beginPath(); g.moveTo(0, y(2.5)); g.lineTo(c.width, y(2.5)); g.stroke();
    g.setLineDash([]);
    g.strokeStyle = "#1f6feb";
    g.lineWidth = 2;
    g.beginPath();
    altitudes.filter((a) => a[0] >= t0).forEach(([t, h], i) => (i ? g.lineTo(x(t), y(h)) : g.moveTo(x(t), y(h))));
    g.stroke();
    g.fillStyle = dark ? "#9aa6b2" : "#5f6b78";
    g.font = "10px system-ui";
    g.fillText(`altitude (m), last 60 s of PX4 time; dashed 2.5 m`, 4, 10);
  }

  function log(text) {
    const box = $("flightlog");
    box.textContent += text + "\n";
    box.scrollTop = box.scrollHeight;
  }

  window.onFlight = (m) => {
    if (m.type === "flight_status") { log(m.text); return; }
    last = m;
    $("telemetry").innerHTML = row("link", m.connected ? "MAVLink (TCP 5760)" : "connecting")
      + row("armed", m.armed ? "yes" : "no") + row("mode", m.mode || "-")
      + row("altitude", fmt(m.alt, 2, " m")) + row("north / east", `${fmt(m.x, 2)} / ${fmt(m.y, 2)} m`)
      + row("roll / pitch", `${fmt(m.roll, 1)} / ${fmt(m.pitch, 1)}°`) + row("yaw", fmt(m.yaw, 1, "°"));
    $("takeoff").disabled = !(flying && m.connected && m.ready && !m.armed);
    $("land").disabled = !(flying && m.armed);
    if (m.alt !== undefined && m.time_boot_ms !== undefined) {
      const t = m.time_boot_ms / 1000;
      if (!altitudes.length || t > altitudes[altitudes.length - 1][0]) altitudes.push([t, m.alt]);
      while (altitudes.length > 2000) altitudes.shift();
      drawChart();
    }
  };

  window.onRunState = (m) => {
    flying = m.state === "running" && Boolean(m.flight);
    if (m.state === "running") {
      altitudes.length = 0;
      $("flightlog").textContent = "";
      if (m.flight) log("PX4 is booting; the take-off button opens when PX4 reports its home position.");
    }
    if (!flying) { $("takeoff").disabled = true; $("land").disabled = true; }
  };

  const post = (path, body) => fetch(path, { method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body || {}) });
  $("takeoff").addEventListener("click", () => { $("takeoff").disabled = true; post("/api/flight/takeoff", { altitude: 2.5 }); });
  $("land").addEventListener("click", () => post("/api/flight/land"));
})();
