const labels = { time: "최단시간", energy: "최소에너지", balanced: "균형 에코", distance: "최단거리" };
const routeColors = { time: "#1565c0", energy: "#108a5b", balanced: "#7158e2", distance: "#d96517" };
const directionKeys = { time: "fastest", energy: "eco", balanced: "balanced", distance: "shortest" };
let map;
let routeLayer;
let markerLayer;
let routeLayers = {};

function setPoint(prefix, point) {
  document.querySelector(`#${prefix}-lat`).value = point.lat;
  document.querySelector(`#${prefix}-lon`).value = point.lon;
}

function pointFromInputs(prefix) {
  return { lat: Number(document.querySelector(`#${prefix}-lat`).value), lon: Number(document.querySelector(`#${prefix}-lon`).value) };
}

function formatTm(tm) {
  return `${tm.slice(0, 4)}.${tm.slice(4, 6)}.${tm.slice(6, 8)} ${tm.slice(8, 10)}:00`;
}

function initMap() {
  map = L.map("map", { zoomControl: false }).setView([37.55, 126.99], 11);
  L.control.zoom({ position: "bottomright" }).addTo(map);
  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", { maxZoom: 19, attribution: "© OpenStreetMap contributors" }).addTo(map);
  routeLayer = L.geoJSON(null).addTo(map);
  markerLayer = L.layerGroup().addTo(map);
}

function routeCard(route) {
  const type = route.route_type;
  return `<button class="route-card ${type}" type="button" data-route="${type}"><h3>${labels[type] ?? type}</h3><div class="big">${route.time_min.toFixed(1)}분</div><p>${route.distance_km.toFixed(2)}km · ${route.energy_wh.toLocaleString(undefined, {maximumFractionDigits:0})}Wh<br>${route.n_links}개 링크</p></button>`;
}

function showDirections(type, directions) {
  document.querySelector("#guide-title").textContent = `${labels[type] ?? type} 경로 구간 안내`;
  document.querySelector("#directions").innerHTML = directions.map((step) => `<li><strong>${step.road_name}</strong><br>${step.distance_km.toFixed(2)}km · 약 ${step.time_min.toFixed(1)}분</li>`).join("");
  Object.entries(routeLayers).forEach(([key, layer]) => layer.setStyle({ opacity: key === type ? 1 : .22, weight: key === type ? 8 : 4 }));
  document.querySelectorAll("[data-route]").forEach((card) => card.classList.toggle("active", card.dataset.route === type));
}

function renderRoutes(payload, origin, destination) {
  routeLayer.clearLayers(); markerLayer.clearLayers(); routeLayers = {};
  const features = payload.geojson.features;
  const typeOrder = { distance: 1, time: 2, energy: 3, balanced: 4 };
  features.sort((a, b) => typeOrder[a.properties.route_type] - typeOrder[b.properties.route_type]);
  routeLayer.addData(features);
  routeLayer.eachLayer((layer) => {
    const type = layer.feature.properties.route_type;
    routeLayers[type] = layer;
    layer.setStyle({ color: routeColors[type], weight: type === "balanced" ? 7 : 5, opacity: type === "distance" ? .65 : .88 });
    layer.bindPopup(`<strong>${labels[type]}</strong><br>${layer.feature.properties.time_min}분 · ${layer.feature.properties.energy_wh.toLocaleString()}Wh`);
  });
  markerLayer.addLayer(L.marker([origin.lat, origin.lon]).bindPopup("출발"));
  markerLayer.addLayer(L.marker([destination.lat, destination.lon]).bindPopup("도착"));
  const bounds = routeLayer.getBounds();
  if (bounds.isValid()) map.fitBounds(bounds.pad(.12));

  const cards = payload.routes.map(routeCard).join("");
  const saved = payload.eco_vs_fastest;
  document.querySelector("#summary").innerHTML = `${cards}<article class="route-card eco"><h3>최소에너지 효과</h3><div class="big">${saved.energy_saved_pct.toFixed(1)}% 절감</div><p>${saved.energy_saved_wh.toFixed(0)}Wh 절감<br>대신 ${saved.time_penalty_min.toFixed(1)}분 추가</p></article>`;
  document.querySelectorAll("[data-route]").forEach((card) => card.addEventListener("click", () => showDirections(card.dataset.route, payload.directions[directionKeys[card.dataset.route]])));
  showDirections("time", payload.directions.fastest);
}

function renderHotspots(data) {
  document.querySelector("#hotspot-reference").textContent = data.reference;
  document.querySelector("#hotspots").innerHTML = data.items.map((item, index) => `<article class="hotspot"><span class="rank">#${index + 1} 차량당 추가소비 후보</span><h3>${item.ROAD_NAME || "도로명 미상"}</h3><strong>+${item.operational_excess_wh.toLocaleString()} Wh</strong><p>${item.speed_kmh}km/h · 경사 ${item.slope_pct_raw}% · ${item.tier}<br>${item.diagnosis} · ${item.prediction_confidence} 신뢰도</p></article>`).join("");
}

async function calculate() {
  const button = document.querySelector("#route-button");
  const error = document.querySelector("#error");
  const origin = pointFromInputs("origin"); const destination = pointFromInputs("destination");
  if (![origin.lat, origin.lon, destination.lat, destination.lon].every(Number.isFinite)) { error.textContent = "출발지와 도착지 좌표를 확인해주세요."; return; }
  button.disabled = true; button.textContent = "경로 계산 중…"; error.textContent = "";
  const tm = document.querySelector("#timestamp").value;
  const dataset = document.querySelector("#dataset").value;
  const max_time_increase_pct = Number(document.querySelector("#time-limit").value);
  try {
    const response = await fetch("/api/routes", { method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify({tm, dataset, origin, destination, max_time_increase_pct}) });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.detail || "경로를 계산하지 못했습니다.");
    renderRoutes(payload, origin, destination);
    const hotspotResponse = await fetch(`/api/hotspots?tm=${tm}&dataset=${dataset}`);
    if (hotspotResponse.ok) renderHotspots(await hotspotResponse.json());
  } catch (err) { error.textContent = err.message; }
  finally { button.disabled = false; button.textContent = "경로 비교하기"; }
}

async function initialize() {
  initMap();
  const meta = await (await fetch("/api/meta")).json();
  const origin = document.querySelector("#origin-place"); const destination = document.querySelector("#destination-place");
  Object.entries(meta.places).forEach(([name, point]) => {
    const optionA = new Option(name, name); const optionB = new Option(name, name);
    origin.add(optionA); destination.add(optionB);
  });
  origin.value = "강남역"; destination.value = "서울시청";
  setPoint("origin", meta.places[origin.value]); setPoint("destination", meta.places[destination.value]);
  origin.addEventListener("change", () => setPoint("origin", meta.places[origin.value]));
  destination.addEventListener("change", () => setPoint("destination", meta.places[destination.value]));
  const timestamp = document.querySelector("#timestamp");
  meta.timestamps.forEach((tm) => timestamp.add(new Option(formatTm(tm), tm)));
  timestamp.value = meta.default_tm;
  const slider = document.querySelector("#time-limit");
  slider.addEventListener("input", () => document.querySelector("#time-limit-value").textContent = `${slider.value}%`);
  document.querySelector("#route-button").addEventListener("click", calculate);
  calculate();
}

initialize().catch((error) => { document.querySelector("#error").textContent = `초기화 실패: ${error.message}`; });
