'use strict';
/* =====================================================================
   Tarmoq trafigini tasniflash va anomaliyalarni klasterlash
   Koʻp sahifali ilova — sof Vanilla JavaScript (ML va grafik kutubxonalarisiz)
   ===================================================================== */

/* ---------------------------------------------------------------------
   1. Boshlangʻich baza va sozlamalar
   --------------------------------------------------------------------- */
const INITIAL_DATASET = [
  { id: 1,  packetSize: 20,   connections: 5,  label: 'Xavfsiz'  },
  { id: 2,  packetSize: 60,   connections: 9,  label: 'Xavfsiz'  },
  { id: 3,  packetSize: 100,  connections: 13, label: 'Xavfsiz'  },
  { id: 4,  packetSize: 140,  connections: 17, label: 'Xavfsiz'  },
  { id: 5,  packetSize: 180,  connections: 13, label: 'Xavfsiz'  },
  { id: 6,  packetSize: 220,  connections: 21, label: 'Xavfsiz'  },
  { id: 7,  packetSize: 270,  connections: 25, label: 'Xavfsiz'  },
  { id: 8,  packetSize: 320,  connections: 29, label: 'Xavfsiz'  },
  { id: 9,  packetSize: 380,  connections: 33, label: 'Xavfsiz'  },
  { id: 10, packetSize: 420,  connections: 45, label: 'Shubhali' },
  { id: 11, packetSize: 460,  connections: 37, label: 'Xavfsiz'  },
  { id: 12, packetSize: 520,  connections: 49, label: 'Shubhali' },
  { id: 13, packetSize: 580,  connections: 53, label: 'Shubhali' },
  { id: 14, packetSize: 620,  connections: 57, label: 'Shubhali' },
  { id: 15, packetSize: 680,  connections: 61, label: 'Shubhali' },
  { id: 16, packetSize: 740,  connections: 65, label: 'Shubhali' },
  { id: 17, packetSize: 820,  connections: 69, label: 'Shubhali' },
  { id: 18, packetSize: 880,  connections: 73, label: 'Shubhali' },
  { id: 19, packetSize: 940,  connections: 77, label: 'Shubhali' },
  { id: 20, packetSize: 1020, connections: 85, label: 'Shubhali' },
];

const K_NN = 3;
const MAX_DEPTH = 2;
const Q_CLUSTERS = 3;
const MAX_ITER = 100;
const MIN_ROWS = 3;
const DEFAULT_INIT_IDS = [1, 10, 20];
const DEFAULT_NEW_POINT = { packetSize: 420, connections: 40 };
const CLASSES = ['Xavfsiz', 'Shubhali'];
const FEATURES = [
  { key: 'packetSize',  z: 'Z₁', name: 'Paket hajmi',     unit: 'MB' },
  { key: 'connections', z: 'Z₂', name: 'Ulanishlar soni', unit: 'soʻrov/s' },
];
const EPS = 1e-12;

/* ---------------------------------------------------------------------
   2. Normalizatsiya va masofa
   --------------------------------------------------------------------- */
function computeBounds(dataset) {
  return FEATURES.map(f => {
    const v = dataset.map(r => r[f.key]);
    return { min: Math.min(...v), max: Math.max(...v) };
  });
}

/** Min-Max: z = (x − min) / (max − min); barcha qiymatlar teng boʻlsa 0. */
function normalize(x, b) {
  return b.max === b.min ? 0 : (x - b.min) / (b.max - b.min);
}

function denormalize(z, b) {
  return b.min + z * (b.max - b.min);
}

function sqDist(a, b) {
  let s = 0;
  for (let i = 0; i < a.length; i++) s += (a[i] - b[i]) ** 2;
  return s;
}

function euclid(a, b) {
  return Math.sqrt(sqDist(a, b));
}

/** Sinf yorligʻi z vektoriga kirmaydi — faqat ikkita sonli parametr. */
function buildRows(dataset, bounds) {
  return dataset.map(r => ({ ...r, z: FEATURES.map((f, j) => normalize(r[f.key], bounds[j])) }));
}

/* ---------------------------------------------------------------------
   3. KNN
   --------------------------------------------------------------------- */
function knnClassify(rows, z, k) {
  const computed = rows.map(r => {
    const d1 = z[0] - r.z[0];
    const d2 = z[1] - r.z[1];
    const sq = d1 * d1 + d2 * d2;
    return { id: r.id, label: r.label, z: r.z, d1, d2, sq, d: Math.sqrt(sq) };
  });
  const sorted = computed.slice().sort((a, b) => (a.d - b.d) || (a.id - b.id));
  const kk = Math.min(k, sorted.length);
  const neighbors = sorted.slice(0, kk);
  const votes = {};
  CLASSES.forEach(c => { votes[c] = 0; });
  neighbors.forEach(n => { votes[n.label]++; });
  const max = Math.max(...CLASSES.map(c => votes[c]));
  const tied = CLASSES.filter(c => votes[c] === max);
  const prediction = tied.length === 1 ? tied[0] : neighbors.find(n => tied.includes(n.label)).label;
  return { computed, sorted, neighbors, votes, prediction, tie: tied.length > 1, k: kk };
}

/* ---------------------------------------------------------------------
   4. Decision Tree (Gini)
   --------------------------------------------------------------------- */
function classCounts(rows) {
  const c = {};
  CLASSES.forEach(n => { c[n] = 0; });
  rows.forEach(r => { c[r.label]++; });
  return c;
}

function giniOf(rows) {
  if (!rows.length) return 0;
  const c = classCounts(rows);
  return 1 - CLASSES.reduce((s, n) => s + (c[n] / rows.length) ** 2, 0);
}

function majorityClass(rows, fallback) {
  const c = classCounts(rows);
  const max = Math.max(...CLASSES.map(n => c[n]));
  const top = CLASSES.filter(n => c[n] === max);
  if (top.length > 1 && fallback) return fallback;
  return top[0];
}

function findBestSplit(rows) {
  const n = rows.length;
  const candidates = [];
  let best = null;
  FEATURES.forEach((f, j) => {
    const vals = [...new Set(rows.map(r => r.z[j]))].sort((a, b) => a - b);
    for (let i = 0; i < vals.length - 1; i++) {
      const threshold = (vals[i] + vals[i + 1]) / 2;
      const L = rows.filter(r => r.z[j] <= threshold);
      const R = rows.filter(r => r.z[j] > threshold);
      const gL = giniOf(L);
      const gR = giniOf(R);
      const gw = (L.length / n) * gL + (R.length / n) * gR;
      const cand = {
        feature: j, threshold, lo: vals[i], hi: vals[i + 1],
        nL: L.length, nR: R.length, countsL: classCounts(L), countsR: classCounts(R), gL, gR, gw,
      };
      candidates.push(cand);
      if (!best || gw < best.gw - EPS) best = cand;
    }
  });
  return { best, candidates };
}

function trainTree(rows) {
  let counter = 0;
  const build = (subset, depth, parentPred) => {
    const node = {
      uid: counter++, depth, n: subset.length, ids: subset.map(r => r.id),
      counts: classCounts(subset), gini: giniOf(subset),
      prediction: majorityClass(subset, parentPred), leaf: true,
    };
    if (node.gini === 0) { node.reason = 'toza tugun (Gini = 0)'; return node; }
    if (depth >= MAX_DEPTH) { node.reason = 'maksimal chuqurlik'; return node; }
    const { best, candidates } = findBestSplit(subset);
    if (!best) { node.reason = 'nomzod yoʻq'; return node; }
    Object.assign(node, { leaf: false, feature: best.feature, threshold: best.threshold, split: best, candidates });
    node.left = build(subset.filter(r => r.z[best.feature] <= best.threshold), depth + 1, node.prediction);
    node.right = build(subset.filter(r => r.z[best.feature] > best.threshold), depth + 1, node.prediction);
    return node;
  };
  return build(rows, 0, null);
}

function treePath(root, z) {
  const path = [];
  const steps = [];
  let node = root;
  while (node) {
    path.push(node.uid);
    if (node.leaf) break;
    const goLeft = z[node.feature] <= node.threshold;
    steps.push({ node, goLeft });
    node = goLeft ? node.left : node.right;
  }
  return { path, steps, leaf: node };
}

function treeNodes(node, out = []) {
  if (!node) return out;
  out.push(node);
  treeNodes(node.left, out);
  treeNodes(node.right, out);
  return out;
}

/** Barglar hududlari (Z fazosidagi toʻrtburchaklar) va ajratish chiziqlari. */
function treeRegions(root, rect) {
  const regions = [];
  const lines = [];
  const walk = (node, r) => {
    if (node.leaf) { regions.push({ ...r, node }); return; }
    const t = node.threshold;
    if (node.feature === 0) {
      lines.push({ x0: t, y0: r.y0, x1: t, y1: r.y1, node });
      walk(node.left, { ...r, x1: Math.min(r.x1, t) });
      walk(node.right, { ...r, x0: Math.max(r.x0, t) });
    } else {
      lines.push({ x0: r.x0, y0: t, x1: r.x1, y1: t, node });
      walk(node.left, { ...r, y1: Math.min(r.y1, t) });
      walk(node.right, { ...r, y0: Math.max(r.y0, t) });
    }
  };
  walk(root, rect);
  return { regions, lines };
}

/* ---------------------------------------------------------------------
   5. K-means (har bir qadam batafsil log bilan)
   --------------------------------------------------------------------- */
function createKMeans(rows, initIds) {
  const centers = initIds.map(id => rows.find(r => r.id === id).z.slice());
  return {
    initIds: initIds.slice(),
    initialCenters: centers.map(c => c.slice()),
    centers,
    assign: null,
    iter: 0,
    done: false,
    converged: false,
    log: [],
    trajectory: centers.map(c => [c.slice()]),
  };
}

function argminIndex(arr) {
  let best = 0;
  for (let i = 1; i < arr.length; i++) if (arr[i] < arr[best] - EPS) best = i;
  return best;
}

function kmeansStep(st, rows) {
  if (st.done) return st;
  const oldCenters = st.centers.map(c => c.slice());
  const dists = rows.map(r => oldCenters.map(c => euclid(r.z, c)));
  const assign = dists.map(argminIndex);
  const changed = st.assign ? assign.reduce((s, a, i) => s + (a !== st.assign[i] ? 1 : 0), 0) : rows.length;

  if (st.assign && changed === 0) {
    st.done = true;
    st.converged = true;
    st.log.push({ type: 'check', iter: st.iter + 1, oldCenters, dists, assign });
    return st;
  }

  const clusters = oldCenters.map((c, k) => {
    const idx = [];
    assign.forEach((a, i) => { if (a === k) idx.push(i); });
    const sum = [0, 0];
    idx.forEach(i => { sum[0] += rows[i].z[0]; sum[1] += rows[i].z[1]; });
    const n = idx.length;
    const center = n ? [sum[0] / n, sum[1] / n] : c.slice();
    return { idx, ids: idx.map(i => rows[i].id), n, sum, center, empty: n === 0 };
  });
  const newCenters = clusters.map(c => c.center);
  const sq = rows.map((r, i) => sqDist(r.z, newCenters[assign[i]]));
  const Jparts = clusters.map(c => c.idx.reduce((s, i) => s + sq[i], 0));
  const J = Jparts.reduce((a, b) => a + b, 0);

  st.iter++;
  st.assign = assign;
  st.centers = newCenters.map(c => c.slice());
  st.log.push({ type: 'step', iter: st.iter, oldCenters, dists, assign, changed, clusters, newCenters, sq, Jparts, J });
  newCenters.forEach((c, k) => st.trajectory[k].push(c.slice()));
  if (st.iter >= MAX_ITER) st.done = true;
  return st;
}

/* Node.js muhitida sinash uchun */
if (typeof module !== 'undefined' && module.exports) {
  module.exports = {
    INITIAL_DATASET, computeBounds, buildRows, normalize, knnClassify, trainTree, treePath,
    treeRegions, createKMeans, kmeansStep, findBestSplit, giniOf,
  };
}

/* =====================================================================
   6. Umumiy holat (state) va saqlash
   ===================================================================== */
const STORAGE_KEY = 'netguard-ml-state-v1';
const PAGES = ['dashboard', 'dataset', 'knn', 'tree', 'kmeans'];
const PAGE_META = {
  dashboard: { group: 'Umumiy', title: 'Dashboard' },
  dataset: { group: 'Umumiy', title: 'Maʼlumotlar bazasi' },
  knn: { group: 'Algoritmlar', title: 'KNN tasniflash' },
  tree: { group: 'Algoritmlar', title: 'Decision Tree' },
  kmeans: { group: 'Algoritmlar', title: 'K-means klasterlash' },
};
const CLUSTER_COLORS = ['#3b82f6', '#10b981', '#f59e0b'];
const CLASS_COLORS = { Xavfsiz: '#10b981', Shubhali: '#f43f5e' };
const NONE_COLOR = '#94a3b8';
const NEW_COLOR = '#e11d48';
const PRIMARY = '#2563eb';

const clone = x => JSON.parse(JSON.stringify(x));

/**
 * Yagona umumiy holat. localStorage da uchta kalit saqlanadi:
 *   dataset      — bazadagi yozuvlar
 *   newPoint     — yangi nuqta (forma qiymatlari, matn koʻrinishida)
 *   kmeansState  — boshlangʻich markaz ID lari va bajarilgan qadamlar soni
 * Qolgan hamma narsa (min/max, Z, daraxt, KNN, K-means jurnali) shulardan qayta hisoblanadi.
 */
const S = {
  dataset: clone(INITIAL_DATASET),
  newPoint: { packetSize: String(DEFAULT_NEW_POINT.packetSize), connections: String(DEFAULT_NEW_POINT.connections) },
  kmeansState: { initIds: DEFAULT_INIT_IDS.slice(), steps: 0 },
  page: 'dashboard',
  lastAddedId: null,
  knnZoom: true,
  savedAt: null,
  // hisoblangan qiymatlar
  bounds: null, rows: [], tree: null, point: null, knn: null, path: null, km: null,
};

function defaultState() {
  return {
    dataset: clone(INITIAL_DATASET),
    newPoint: { packetSize: String(DEFAULT_NEW_POINT.packetSize), connections: String(DEFAULT_NEW_POINT.connections) },
    kmeansState: { initIds: DEFAULT_INIT_IDS.slice(), steps: 0 },
  };
}

function applyStored(d) {
  const okRow = r => r && Number.isFinite(r.id) && Number.isFinite(r.packetSize) && Number.isFinite(r.connections) && CLASSES.includes(r.label);
  if (Array.isArray(d.dataset) && d.dataset.length >= MIN_ROWS && d.dataset.every(okRow)) S.dataset = d.dataset;
  const np = d.newPoint;
  if (np && typeof np.packetSize === 'string' && typeof np.connections === 'string') S.newPoint = { packetSize: np.packetSize, connections: np.connections };
  const ks = d.kmeansState;
  if (ks && Array.isArray(ks.initIds) && ks.initIds.length === 3 && Number.isInteger(ks.steps) && ks.steps >= 0) {
    S.kmeansState = { initIds: ks.initIds.map(Number), steps: Math.min(ks.steps, MAX_ITER + 1) };
  }
  if (d.savedAt) S.savedAt = d.savedAt;
}

function loadState() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw) applyStored(JSON.parse(raw));
  } catch (e) { /* localStorage mavjud boʻlmasa — xotiradagi holat bilan ishlaymiz */ }
}

function saveState() {
  S.savedAt = Date.now();
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify({
      dataset: S.dataset, newPoint: S.newPoint, kmeansState: S.kmeansState, savedAt: S.savedAt,
    }));
    updateSaveIndicator(true);
  } catch (e) {
    const t = document.getElementById('sb-save-text');
    if (t) t.textContent = 'Faqat shu sessiyada';
  }
}

function updateSaveIndicator(pulse) {
  const box = document.getElementById('sb-save');
  if (!box) return;
  const time = S.savedAt ? new Date(S.savedAt).toLocaleTimeString('uz-UZ', { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false }) : null;
  document.getElementById('sb-save-text').textContent = time ? `Saqlangan · ${time}` : 'Boshlangʻich holat';
  if (pulse) {
    box.classList.add('pulse');
    setTimeout(() => box.classList.remove('pulse'), 500);
  }
}

/** Baza oʻzgarganda: chegaralar, Z, daraxt, KNN va K-means qayta hisoblanadi. */
function recomputeData(resetKm) {
  S.bounds = computeBounds(S.dataset);
  S.rows = buildRows(S.dataset, S.bounds);
  S.tree = trainTree(S.rows);
  if (resetKm) S.kmeansState.steps = 0;
  ensureInitIds();
  rebuildKMeans();
  recomputePoint();
}

function recomputePoint() {
  const p = Number(String(S.newPoint.packetSize).trim().replace(',', '.'));
  const c = Number(String(S.newPoint.connections).trim().replace(',', '.'));
  const okP = S.newPoint.packetSize.trim() !== '' && Number.isFinite(p) && p >= 0;
  const okC = S.newPoint.connections.trim() !== '' && Number.isFinite(c) && c >= 0;
  if (!okP || !okC) {
    S.point = { valid: false, okP, okC };
    S.knn = null;
    S.path = null;
    return;
  }
  const z = [normalize(p, S.bounds[0]), normalize(c, S.bounds[1])];
  S.point = { valid: true, packetSize: p, connections: c, z, okP, okC };
  S.knn = knnClassify(S.rows, z, K_NN);
  S.path = treePath(S.tree, z);
}

function distinctVectors(ids) {
  const rows = ids.map(id => S.rows.find(r => r.id === id));
  if (rows.some(r => !r)) return false;
  return new Set(ids).size === 3 && new Set(rows.map(r => r.z.join('|'))).size === 3;
}

/** Tanlangan boshlangʻich ID lar bazada boʻlmasa — avtomatik uchta turli vektor tanlanadi. */
function ensureInitIds() {
  if (distinctVectors(S.kmeansState.initIds)) return;
  const ids = S.rows.map(r => r.id);
  const pick = [ids[0], ids[Math.floor((ids.length - 1) / 2)], ids[ids.length - 1]];
  if (distinctVectors(pick)) { S.kmeansState.initIds = pick; return; }
  const chosen = [];
  const seen = new Set();
  for (const r of S.rows) {
    const key = r.z.join('|');
    if (!seen.has(key)) { seen.add(key); chosen.push(r.id); }
    if (chosen.length === 3) break;
  }
  S.kmeansState.initIds = chosen.length === 3 ? chosen : ids.slice(0, 3);
}

function rebuildKMeans() {
  S.km = createKMeans(S.rows, S.kmeansState.initIds);
  for (let i = 0; i < S.kmeansState.steps && !S.km.done; i++) kmeansStep(S.km, S.rows);
}

/* =====================================================================
   7. Yordamchilar
   ===================================================================== */
const $ = id => document.getElementById(id);
const f4 = x => (Number.isFinite(x) ? x.toFixed(4) : '—');
const fmtNum = (x, maxDec = 2) => {
  if (!Number.isFinite(x)) return '—';
  const r = Math.round(x * 10 ** maxDec) / 10 ** maxDec;
  const [i, d] = String(r).split('.');
  return i.replace(/\B(?=(\d{3})+(?!\d))/g, ' ') + (d ? '.' + d : '');
};
const pill = (c, big) => `<span class="pill pill-${c}${big ? ' big' : ''}">${c}</span>`;
const clTag = k => (k === null || k === undefined ? '<span class="cl cl-none">—</span>' : `<span class="cl cl-${k}">C${k + 1}</span>`);
const frac = (a, b) => `<span class="frac"><span>${a}</span><span>${b}</span></span>`;
const origOf = (j, z) => `${fmtNum(denormalize(z, S.bounds[j]), 1)} ${FEATURES[j].unit}`;
const vec = z => `(${f4(z[0])}, ${f4(z[1])})`;
const sub = n => String(n).replace(/\d/g, d => '₀₁₂₃₄₅₆₇₈₉'[d]);

let toastTimer = null;
function showToast(msg, actionLabel, action) {
  const t = $('toast');
  t.innerHTML = `<span>${msg}</span>${actionLabel ? `<button type="button">${actionLabel}</button>` : ''}`;
  t.hidden = false;
  if (actionLabel) t.querySelector('button').onclick = () => { t.hidden = true; action(); };
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { t.hidden = true; }, 5000);
}

function flashKpi(el) {
  if (!el) return;
  el.classList.add('flash');
  setTimeout(() => el.classList.remove('flash'), 550);
}

/* =====================================================================
   8. Yangi nuqta formasi (bir nechta sahifada, bitta umumiy holat)
   ===================================================================== */
function buildPointForms() {
  document.querySelectorAll('.point-form').forEach(box => {
    box.innerHTML = `
      <form class="pf" novalidate>
        <label class="field"><span class="field-label">Paket hajmi</span>
          <span class="input-wrap"><input type="number" step="any" min="0" data-k="packetSize"><span class="unit">MB</span></span></label>
        <label class="field"><span class="field-label">Ulanishlar soni (sekundiga)</span>
          <span class="input-wrap"><input type="number" step="any" min="0" data-k="connections"><span class="unit">soʻrov/s</span></span></label>
        <div class="btn-row">
          <button type="submit" class="btn btn-primary"><svg class="ic sm"><use href="#i-check"/></svg>Baholash</button>
          <button type="button" class="btn btn-secondary" data-act="random"><svg class="ic sm"><use href="#i-dice"/></svg>Tasodifiy</button>
        </div>
        <p class="form-error" hidden></p>
        <div class="pf-norm">
          <div class="kpi"><span class="kpi-label">Z₁ · paket hajmi</span><span class="kpi-value" data-z="0">—</span></div>
          <div class="kpi"><span class="kpi-label">Z₂ · ulanishlar</span><span class="kpi-value" data-z="1">—</span></div>
        </div>
      </form>`;
  });

  document.addEventListener('input', e => {
    const inp = e.target.closest('.pf input[data-k]');
    if (!inp) return;
    S.newPoint[inp.dataset.k] = inp.value;
    onPointChange();
  });
  document.addEventListener('submit', e => {
    if (!e.target.classList.contains('pf')) return;
    e.preventDefault();
    onPointChange();
  });
  document.addEventListener('click', e => {
    const b = e.target.closest('.pf [data-act="random"]');
    if (!b) return;
    const bd = S.bounds;
    S.newPoint.packetSize = String(Math.round(bd[0].min + Math.random() * (bd[0].max - bd[0].min)));
    S.newPoint.connections = String(Math.round(bd[1].min + Math.random() * (bd[1].max - bd[1].min)));
    onPointChange(true);
  });
}

function onPointChange(forceSync) {
  recomputePoint();
  saveState();
  syncPointForms(forceSync);
  renderCurrent({ skipForms: true });
}

function syncPointForms(force) {
  document.querySelectorAll('.pf').forEach(form => {
    form.querySelectorAll('input[data-k]').forEach(inp => {
      if (force || document.activeElement !== inp) inp.value = S.newPoint[inp.dataset.k];
      const ok = inp.dataset.k === 'packetSize' ? S.point.okP : S.point.okC;
      inp.classList.toggle('invalid', !ok);
    });
    const err = form.querySelector('.form-error');
    if (S.point.valid) {
      err.hidden = true;
    } else {
      const msgs = [];
      if (!S.point.okP) msgs.push('Paket hajmi manfiy boʻlmagan son boʻlishi kerak.');
      if (!S.point.okC) msgs.push('Ulanishlar soni manfiy boʻlmagan son boʻlishi kerak.');
      err.innerHTML = msgs.join('<br>');
      err.hidden = false;
    }
    form.querySelectorAll('[data-z]').forEach(el => {
      el.textContent = S.point.valid ? f4(S.point.z[Number(el.dataset.z)]) : '—';
    });
  });
}

/* =====================================================================
   9. Navigatsiya
   ===================================================================== */
function setPage(page) {
  if (!PAGES.includes(page)) page = 'dashboard';
  S.page = page;
  document.querySelectorAll('.view').forEach(v => { v.hidden = v.dataset.page !== page; });
  document.querySelectorAll('.nav-item').forEach(t => t.classList.toggle('active', t.dataset.page === page));
  const activeNav = document.querySelector(`.nav-item[data-page="${page}"]`);
  if (activeNav && window.innerWidth <= 900) activeNav.scrollIntoView({ inline: 'center', block: 'nearest' });
  $('crumb-group').textContent = PAGE_META[page].group;
  $('crumb-page').textContent = PAGE_META[page].title;
  document.title = `${PAGE_META[page].title} · NetGuard ML Analytics`;
  renderCurrent();
  window.scrollTo({ top: 0 });
}

function routeFromHash() {
  setPage((location.hash || '').replace('#', '') || 'dashboard');
}

let chartDrawers = [];

function renderCurrent(opts = {}) {
  if (!opts.skipForms) syncPointForms();
  chartDrawers = [];
  const map = { dashboard: renderDashboard, dataset: renderDataset, knn: renderKnn, tree: renderTree, kmeans: renderKMeans };
  map[S.page]();
  chartDrawers.forEach(fn => fn());
  renderChrome();
}

/** Yon panel nishonlari va yuqori qatordagi holat chiplari — har bir oʻzgarishda yangilanadi. */
function renderChrome() {
  const km = S.km;
  $('nav-badge-dataset').textContent = S.dataset.length;
  $('nav-badge-kmeans').textContent = km.converged ? '✓' : km.iter;
  $('nav-badge-kmeans').title = km.converged ? 'K-means yakunlangan' : `K-means: ${km.iter}-iteratsiya`;
  const knnDot = $('nav-dot-knn');
  const treeDot = $('nav-dot-tree');
  knnDot.className = 'nav-dot' + (S.knn ? ' ' + S.knn.prediction : '');
  treeDot.className = 'nav-dot' + (S.path ? ' ' + S.path.leaf.prediction : '');
  knnDot.title = S.knn ? `KNN bashorati: ${S.knn.prediction}` : '';
  treeDot.title = S.path ? `Daraxt bashorati: ${S.path.leaf.prediction}` : '';

  const p = S.point;
  const predChip = (href, name, cls) => `<a class="ts-chip" href="${href}"><span class="ts-dot" style="background:${cls ? CLASS_COLORS[cls] : NONE_COLOR}"></span>${name}: <b>${cls || '—'}</b></a>`;
  $('top-status').innerHTML = `
    <a class="ts-chip" href="#knn"><span class="ts-star">★</span><span class="mono">${p.valid ? `${fmtNum(p.packetSize)} MB · ${fmtNum(p.connections)} soʻrov/s` : 'notoʻgʻri qiymat'}</span></a>
    ${predChip('#knn', 'KNN', S.knn && S.knn.prediction)}
    ${predChip('#tree', 'Daraxt', S.path && S.path.leaf.prediction)}
    <a class="ts-chip" href="#kmeans"><span class="ts-dot" style="background:${km.converged ? CLUSTER_COLORS[1] : PRIMARY}"></span>K-means: <b>${km.converged ? 'yakunlandi' : km.iter + '-iter.'}</b></a>`;
}

/* =====================================================================
   10. Canvas grafigi (barcha sahifalar uchun umumiy)
   ===================================================================== */
const FONT = "Inter, -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif";
const MONO = "'JetBrains Mono', ui-monospace, Menlo, Consolas, monospace";
const hitPoints = {};

/**
 * opts: color ('cluster' | 'class'), labels ('cluster' | 'id'), centers, knn ('none' | 'lines' | 'labeled'),
 *       rays, trajectory, regions, newPoint
 */
function drawScatter(canvasId, opts) {
  const canvas = $(canvasId);
  const W = Math.max(320, canvas.clientWidth);
  const H = Math.max(300, canvas.clientHeight);
  const dpr = window.devicePixelRatio || 1;
  canvas.width = Math.round(W * dpr);
  canvas.height = Math.round(H * dpr);
  const ctx = canvas.getContext('2d');
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, W, H);

  const M = { l: 112, r: 16, t: 12, b: 70 };
  const pw = W - M.l - M.r;
  const ph = H - M.t - M.b;
  const np = opts.newPoint && S.point.valid ? S.point : null;

  let xMin = 0, xMax = 1, yMin = 0, yMax = 1;
  if (opts.zoom && np && S.knn) {
    // Yaqinlashtirilgan koʻrinish: yangi nuqta va uning qoʻshnilari atrofi
    const zs = [np.z, ...S.knn.neighbors.map(n => n.z)];
    const x0 = Math.min(...zs.map(z => z[0])), x1 = Math.max(...zs.map(z => z[0]));
    const y0 = Math.min(...zs.map(z => z[1])), y1 = Math.max(...zs.map(z => z[1]));
    const span = Math.max(x1 - x0, y1 - y0, 0.1) * 0.8;
    const cx = (x0 + x1) / 2, cy = (y0 + y1) / 2;
    xMin = cx - span * 1.25; xMax = cx + span * 1.25;
    yMin = cy - span; yMax = cy + span;
  } else {
    if (np) {
      xMin = Math.min(xMin, np.z[0]); xMax = Math.max(xMax, np.z[0]);
      yMin = Math.min(yMin, np.z[1]); yMax = Math.max(yMax, np.z[1]);
    }
    const padX = (xMax - xMin) * 0.05;
    const padY = (yMax - yMin) * 0.06;
    xMin -= padX; xMax += padX; yMin -= padY; yMax += padY;
  }
  const sx = x => M.l + ((x - xMin) / (xMax - xMin)) * pw;
  const sy = y => M.t + ph - ((y - yMin) / (yMax - yMin)) * ph;
  const niceStep = s => (s > 4 ? 1 : s > 2 ? 0.5 : s > 1.3 ? 0.2 : s > 0.6 ? 0.1 : s > 0.3 ? 0.05 : s > 0.12 ? 0.02 : 0.01);
  const ticks = (a, b, st) => {
    const out = [];
    for (let i = Math.ceil(a / st - 1e-9); i * st <= b + 1e-9; i++) out.push(Math.round(i * st * 10000) / 10000);
    return out;
  };

  ctx.fillStyle = '#f8fafc';
  ctx.fillRect(sx(0), sy(1), sx(1) - sx(0), sy(0) - sy(1));

  // Qaror hududlari (daraxt sahifasi)
  if (opts.regions && S.tree) {
    const { regions, lines } = treeRegions(S.tree, { x0: xMin, x1: xMax, y0: yMin, y1: yMax });
    regions.forEach(r => {
      ctx.fillStyle = hexA(CLASS_COLORS[r.node.prediction], S.path && S.path.leaf.uid === r.node.uid ? 0.16 : 0.07);
      ctx.fillRect(sx(r.x0), sy(r.y1), sx(r.x1) - sx(r.x0), sy(r.y0) - sy(r.y1));
    });
    opts._lines = lines;
  }

  // Punktir toʻr
  ctx.setLineDash([3, 4]);
  ctx.strokeStyle = '#e2e8f0';
  ctx.lineWidth = 1;
  const stX = niceStep(xMax - xMin);
  const stY = niceStep(yMax - yMin);
  const tx = ticks(xMin, xMax, stX);
  const ty = ticks(yMin, yMax, stY);
  const decX = stX < 0.1 ? 2 : 1;
  const decY = stY < 0.1 ? 2 : 1;
  tx.forEach(v => { const x = Math.round(sx(v)) + .5; ctx.beginPath(); ctx.moveTo(x, M.t); ctx.lineTo(x, M.t + ph); ctx.stroke(); });
  ty.forEach(v => { const y = Math.round(sy(v)) + .5; ctx.beginPath(); ctx.moveTo(M.l, y); ctx.lineTo(M.l + pw, y); ctx.stroke(); });
  ctx.setLineDash([]);
  ctx.strokeStyle = '#cbd5e1';
  ctx.beginPath();
  ctx.moveTo(M.l + .5, M.t); ctx.lineTo(M.l + .5, M.t + ph + .5); ctx.lineTo(M.l + pw, M.t + ph + .5);
  ctx.stroke();

  // Oʻq belgilari: yuqorida Z, pastda asl qiymat
  ctx.textAlign = 'center';
  ctx.textBaseline = 'top';
  tx.forEach(v => {
    ctx.font = `500 11px ${MONO}`; ctx.fillStyle = '#64748b';
    ctx.fillText(v.toFixed(decX), sx(v), M.t + ph + 8);
    ctx.font = `10px ${MONO}`; ctx.fillStyle = '#94a3b8';
    ctx.fillText(fmtNum(denormalize(v, S.bounds[0]), decX === 2 ? 1 : 0), sx(v), M.t + ph + 23);
  });
  ctx.textAlign = 'right';
  ctx.textBaseline = 'middle';
  ty.forEach(v => {
    ctx.font = `500 11px ${MONO}`; ctx.fillStyle = '#64748b';
    ctx.fillText(v.toFixed(decY), M.l - 44, sy(v));
    ctx.font = `10px ${MONO}`; ctx.fillStyle = '#94a3b8';
    ctx.fillText(fmtNum(denormalize(v, S.bounds[1]), 1), M.l - 8, sy(v));
  });
  ctx.textAlign = 'center';
  ctx.textBaseline = 'alphabetic';
  ctx.font = `500 12px ${FONT}`; ctx.fillStyle = '#0f172a';
  ctx.fillText('Z₁ — paket hajmi (normalizatsiyalangan, 0–1)', M.l + pw / 2, H - 20);
  ctx.font = `11px ${FONT}`; ctx.fillStyle = '#94a3b8';
  ctx.fillText('kulrang: asl qiymat, MB', M.l + pw / 2, H - 5);
  ctx.save();
  ctx.translate(14, M.t + ph / 2);
  ctx.rotate(-Math.PI / 2);
  ctx.font = `500 12px ${FONT}`; ctx.fillStyle = '#0f172a';
  ctx.fillText('Z₂ — ulanishlar soni (normalizatsiyalangan, 0–1)', 0, 0);
  ctx.font = `11px ${FONT}`; ctx.fillStyle = '#94a3b8';
  ctx.fillText('kulrang: asl qiymat, soʻrov/s', 0, 15);
  ctx.restore();

  ctx.save();
  ctx.beginPath();
  ctx.rect(M.l + 1, M.t, pw, ph);
  ctx.clip();

  const km = S.km;
  const rows = S.rows;
  const placed = [];
  const inside = rc => rc.x >= M.l + 2 && rc.x + rc.w <= M.l + pw - 2 && rc.y >= M.t + 2 && rc.y + rc.h <= M.t + ph - 2;
  const free = rc => inside(rc) && !placed.some(q => overlap(q, rc));

  // Daraxt ajratish chiziqlari
  if (opts._lines) {
    opts._lines.forEach(l => {
      const onPath = S.path && S.path.path.includes(l.node.uid);
      ctx.strokeStyle = onPath ? PRIMARY : '#64748b';
      ctx.lineWidth = onPath ? 2.2 : 1.4;
      ctx.setLineDash([6, 4]);
      ctx.beginPath(); ctx.moveTo(sx(l.x0), sy(l.y0)); ctx.lineTo(sx(l.x1), sy(l.y1)); ctx.stroke();
      ctx.setLineDash([]);
      const t = `T${l.node.uid}: ${FEATURES[l.node.feature].z} = ${f4(l.node.threshold)}`;
      ctx.font = `600 11px ${MONO}`;
      const w = ctx.measureText(t).width;
      let lx, ly;
      if (l.node.feature === 1) { lx = Math.max(sx(l.x0), M.l) + 8; ly = sy(l.y0) - 12; } else { lx = sx(l.x0) + 6; ly = Math.max(sy(l.y1), M.t) + 14; }
      ctx.fillStyle = 'rgba(255,255,255,.92)';
      ctx.fillRect(lx - 4, ly - 9, w + 8, 18);
      ctx.fillStyle = onPath ? PRIMARY : '#475569';
      ctx.textAlign = 'left';
      ctx.textBaseline = 'middle';
      ctx.fillText(t, lx, ly);
      placed.push({ x: lx - 4, y: ly - 9, w: w + 8, h: 18 });
    });
  }

  // Klaster nurlari
  if (opts.rays && km.assign) {
    rows.forEach((r, i) => {
      const c = km.centers[km.assign[i]];
      ctx.strokeStyle = hexA(CLUSTER_COLORS[km.assign[i]], 0.4);
      ctx.lineWidth = 1.3;
      ctx.beginPath(); ctx.moveTo(sx(r.z[0]), sy(r.z[1])); ctx.lineTo(sx(c[0]), sy(c[1])); ctx.stroke();
    });
  }

  // Markazlar harakati
  if (opts.trajectory) {
    km.trajectory.forEach((tr, k) => {
      if (tr.length < 2) return;
      ctx.strokeStyle = hexA(CLUSTER_COLORS[k], 0.75);
      ctx.lineWidth = 1.6;
      ctx.setLineDash([4, 4]);
      ctx.beginPath();
      tr.forEach((p, i) => (i ? ctx.lineTo(sx(p[0]), sy(p[1])) : ctx.moveTo(sx(p[0]), sy(p[1]))));
      ctx.stroke();
      ctx.setLineDash([]);
      tr.slice(0, -1).forEach(p => {
        ctx.fillStyle = '#fff';
        ctx.strokeStyle = CLUSTER_COLORS[k];
        ctx.lineWidth = 1.5;
        ctx.beginPath(); ctx.arc(sx(p[0]), sy(p[1]), 3, 0, Math.PI * 2); ctx.fill(); ctx.stroke();
      });
    });
  }

  // KNN chiziqlari
  const nIds = new Set(S.knn && np ? S.knn.neighbors.map(n => n.id) : []);
  if (np && S.knn && opts.knn !== 'none') {
    S.knn.neighbors.forEach(n => {
      ctx.strokeStyle = hexA(NEW_COLOR, 0.6);
      ctx.lineWidth = opts.knn === 'labeled' ? 1.8 : 1.3;
      ctx.setLineDash([5, 4]);
      ctx.beginPath(); ctx.moveTo(sx(np.z[0]), sy(np.z[1])); ctx.lineTo(sx(n.z[0]), sy(n.z[1])); ctx.stroke();
      ctx.setLineDash([]);
    });
  }

  // Nuqtalar
  const pts = [];
  rows.forEach((r, i) => {
    const x = sx(r.z[0]);
    const y = sy(r.z[1]);
    const k = km.assign ? km.assign[i] : null;
    const col = opts.color === 'class' ? CLASS_COLORS[r.label] : (k === null ? NONE_COLOR : CLUSTER_COLORS[k]);
    placed.push({ x: x - 7, y: y - 7, w: 14, h: 14 });
    if (nIds.has(r.id) && opts.knn !== 'none') {
      ctx.strokeStyle = hexA(NEW_COLOR, 0.7);
      ctx.lineWidth = 1.6;
      ctx.beginPath(); ctx.arc(x, y, 10.5, 0, Math.PI * 2); ctx.stroke();
    }
    ctx.beginPath();
    ctx.arc(x, y, 5.5, 0, Math.PI * 2);
    if (r.label === 'Shubhali') {
      ctx.fillStyle = col; ctx.fill();
      ctx.strokeStyle = '#fff'; ctx.lineWidth = 1.5; ctx.stroke();
    } else {
      ctx.fillStyle = '#fff'; ctx.fill();
      ctx.strokeStyle = col; ctx.lineWidth = 2.2; ctx.stroke();
    }
    pts.push({ x, y, row: r, k });
  });

  if (opts.centers) km.centers.forEach(c => placed.push({ x: sx(c[0]) - 10, y: sy(c[1]) - 10, w: 20, h: 20 }));
  if (np) placed.push({ x: sx(np.z[0]) - 13, y: sy(np.z[1]) - 13, w: 26, h: 26 });

  // KNN masofa yorliqlari
  if (np && S.knn && opts.knn === 'labeled') {
    ctx.font = `600 11px ${MONO}`;
    ctx.textAlign = 'left';
    ctx.textBaseline = 'middle';
    S.knn.neighbors.forEach((n, i) => {
      const ax = sx(np.z[0]), ay = sy(np.z[1]);
      const bxp = sx(n.z[0]), byp = sy(n.z[1]);
      const len = Math.hypot(bxp - ax, byp - ay);
      const ux = len > 1 ? (bxp - ax) / len : 0;
      const uy = len > 1 ? (byp - ay) / len : -1;
      const t = `d${sub(i + 1)} = ${f4(n.d)}`;
      const w = ctx.measureText(t).width;
      const bw = w + 10;
      const cands = [];
      [34, 52, 72].forEach(r => {
        cands.push([bxp + ux * r, byp + uy * r]);
        cands.push([bxp + ux * r - uy * 16, byp + uy * r + ux * 16]);
        cands.push([bxp + ux * r + uy * 16, byp + uy * r - ux * 16]);
      });
      if (len > bw + 30) cands.push([(ax + bxp) / 2, (ay + byp) / 2 - 12]);
      let bx = cands[0][0] - bw / 2;
      let by = cands[0][1] - 9;
      for (const c of cands) {
        const rc = { x: c[0] - bw / 2, y: c[1] - 9, w: bw, h: 18 };
        if (free(rc)) { bx = rc.x; by = rc.y; break; }
      }
      placed.push({ x: bx, y: by, w: w + 10, h: 18 });
      ctx.strokeStyle = hexA(NEW_COLOR, 0.35);
      ctx.lineWidth = 1;
      ctx.beginPath(); ctx.moveTo(bxp, byp); ctx.lineTo(bx + bw / 2, by + 9); ctx.stroke();
      roundRect(ctx, bx, by, bw, 18, 5);
      ctx.fillStyle = '#fff'; ctx.fill();
      ctx.strokeStyle = hexA(NEW_COLOR, 0.5); ctx.lineWidth = 1; ctx.stroke();
      ctx.fillStyle = '#be123c';
      ctx.fillText(t, bx + 5, by + 9.5);
    });
  }

  // Yorliqlar
  ctx.font = `500 10.5px ${MONO}`;
  ctx.textAlign = 'left';
  ctx.textBaseline = 'middle';
  pts.forEach(p => {
    if (p.x < M.l || p.x > M.l + pw || p.y < M.t || p.y > M.t + ph) return; // grafikdan tashqaridagi nuqta
    const label = `#${p.row.id}` + (opts.labels === 'cluster' && p.k !== null ? `(C${p.k + 1})` : '');
    const w = ctx.measureText(label).width;
    const h = 13;
    const offs = [[9, -10], [9, 9], [-w - 9, -10], [-w - 9, 9], [-w / 2, -18], [-w / 2, 18]];
    let ch = offs[0];
    for (const o of offs) {
      const rc = { x: p.x + o[0], y: p.y + o[1] - h / 2, w, h };
      if (free(rc)) { ch = o; break; }
    }
    const rc = { x: p.x + ch[0], y: p.y + ch[1] - h / 2, w, h };
    placed.push(rc);
    ctx.fillStyle = 'rgba(255,255,255,.85)';
    ctx.fillRect(rc.x - 2, rc.y, w + 4, h);
    const col = opts.color === 'class' ? CLASS_COLORS[p.row.label] : (p.k === null ? '#64748b' : CLUSTER_COLORS[p.k]);
    ctx.fillStyle = darken(col, 0.72);
    ctx.fillText(label, rc.x, p.y + ch[1]);
  });

  // Markazlar ✖ μ
  if (opts.centers) {
    km.centers.forEach((c, k) => {
      const x = sx(c[0]);
      const y = sy(c[1]);
      ctx.lineCap = 'round';
      ctx.strokeStyle = '#fff'; ctx.lineWidth = 7; drawX(ctx, x, y, 8);
      ctx.strokeStyle = CLUSTER_COLORS[k]; ctx.lineWidth = 3.2; drawX(ctx, x, y, 8);
      ctx.font = `600 12px ${FONT}`;
      ctx.textAlign = 'left';
      ctx.lineWidth = 4; ctx.strokeStyle = '#fff';
      ctx.strokeText(`μ${k + 1}`, x + 11, y + 12);
      ctx.fillStyle = darken(CLUSTER_COLORS[k], 0.72);
      ctx.fillText(`μ${k + 1}`, x + 11, y + 12);
    });
  }

  // Yangi nuqta ★
  if (np) {
    const x = sx(np.z[0]);
    const y = sy(np.z[1]);
    ctx.fillStyle = hexA(NEW_COLOR, 0.12);
    ctx.beginPath(); ctx.arc(x, y, 17, 0, Math.PI * 2); ctx.fill();
    drawStar(ctx, x, y, 11, 4.8);
    ctx.font = `600 12px ${FONT}`;
    const t = '★ Yangi';
    const tw = ctx.measureText(t).width;
    let lx = x + 18;
    let ly = y - 14;
    for (const [ox, oy] of [[18, -14], [18, 16], [-18 - tw, -14], [-18 - tw, 16], [-tw / 2, -26], [-tw / 2, 30]]) {
      const rc = { x: x + ox, y: y + oy - 8, w: tw, h: 16 };
      if (free(rc)) { lx = x + ox; ly = y + oy; break; }
    }
    ctx.textAlign = 'left';
    ctx.lineWidth = 4; ctx.strokeStyle = '#fff';
    ctx.strokeText(t, lx, ly);
    ctx.fillStyle = NEW_COLOR;
    ctx.fillText(t, lx, ly);
  }
  ctx.restore();
  hitPoints[canvasId] = pts;
}

function drawX(ctx, x, y, s) {
  ctx.beginPath();
  ctx.moveTo(x - s, y - s); ctx.lineTo(x + s, y + s);
  ctx.moveTo(x + s, y - s); ctx.lineTo(x - s, y + s);
  ctx.stroke();
}

function drawStar(ctx, x, y, R, r) {
  ctx.beginPath();
  for (let i = 0; i < 10; i++) {
    const rad = i % 2 ? r : R;
    const a = -Math.PI / 2 + (i * Math.PI) / 5;
    const px = x + rad * Math.cos(a);
    const py = y + rad * Math.sin(a);
    if (i) ctx.lineTo(px, py); else ctx.moveTo(px, py);
  }
  ctx.closePath();
  ctx.fillStyle = NEW_COLOR; ctx.fill();
  ctx.strokeStyle = '#fff'; ctx.lineWidth = 1.5; ctx.stroke();
}

function roundRect(ctx, x, y, w, h, r) {
  ctx.beginPath();
  ctx.moveTo(x + r, y);
  ctx.arcTo(x + w, y, x + w, y + h, r);
  ctx.arcTo(x + w, y + h, x, y + h, r);
  ctx.arcTo(x, y + h, x, y, r);
  ctx.arcTo(x, y, x + w, y, r);
  ctx.closePath();
}

const overlap = (a, b) => a.x < b.x + b.w && a.x + a.w > b.x && a.y < b.y + b.h && a.y + a.h > b.y;
function hexA(hex, a) {
  const n = parseInt(hex.slice(1), 16);
  return `rgba(${(n >> 16) & 255}, ${(n >> 8) & 255}, ${n & 255}, ${a})`;
}
function darken(hex, f) {
  const n = parseInt(hex.slice(1), 16);
  return `rgb(${[(n >> 16) & 255, (n >> 8) & 255, n & 255].map(v => Math.round(v * f)).join(',')})`;
}

/** J (klaster ichidagi kvadrat masofalar yigʻindisi) dinamikasi: kichik (sparkline) yoki toʻliq koʻrinish. */
function drawJChart(canvasId, mini) {
  const canvas = $(canvasId);
  if (!canvas) return;
  const W = Math.max(60, canvas.clientWidth);
  const H = Math.max(30, canvas.clientHeight);
  const dpr = window.devicePixelRatio || 1;
  canvas.width = Math.round(W * dpr);
  canvas.height = Math.round(H * dpr);
  const ctx = canvas.getContext('2d');
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, W, H);
  const vals = S.km.log.filter(l => l.type === 'step').map(l => l.J);

  const M = mini ? { l: 2, r: 4, t: 4, b: 4 } : { l: 52, r: 14, t: 12, b: 28 };
  const pw = W - M.l - M.r;
  const ph = H - M.t - M.b;
  if (!vals.length) {
    if (!mini) {
      ctx.fillStyle = '#94a3b8';
      ctx.font = `12px ${FONT}`;
      ctx.textAlign = 'center';
      ctx.fillText('Hali iteratsiya yoʻq — «Keyingi qadam» tugmasini bosing', W / 2, H / 2);
    } else {
      ctx.strokeStyle = '#e2e8f0';
      ctx.setLineDash([3, 3]);
      ctx.beginPath(); ctx.moveTo(M.l, H / 2); ctx.lineTo(W - M.r, H / 2); ctx.stroke();
    }
    return;
  }
  const maxV = Math.max(...vals);
  const minV = mini ? Math.min(...vals) : 0;
  const span = maxV - minV || 1;
  const n = vals.length;
  const sx = i => M.l + (n === 1 ? pw / 2 : (i / (n - 1)) * pw);
  const sy = v => M.t + ph - ((v - minV) / span) * ph * (mini ? 1 : 0.9);

  if (!mini) {
    ctx.font = `10.5px ${MONO}`;
    ctx.fillStyle = '#94a3b8';
    ctx.textAlign = 'right';
    ctx.textBaseline = 'middle';
    [0, 0.5, 1].forEach(f => {
      const v = minV + f * span / 0.9 * 0.9;
      const y = sy(v);
      ctx.strokeStyle = '#eef2f6';
      ctx.setLineDash([3, 4]);
      ctx.beginPath(); ctx.moveTo(M.l, y); ctx.lineTo(W - M.r, y); ctx.stroke();
      ctx.setLineDash([]);
      ctx.fillText(v.toFixed(3), M.l - 8, y);
    });
    ctx.textAlign = 'center';
    ctx.textBaseline = 'top';
    vals.forEach((v, i) => ctx.fillText(String(i + 1), sx(i), H - M.b + 8));
  }

  // maydon
  const grad = ctx.createLinearGradient(0, M.t, 0, M.t + ph);
  grad.addColorStop(0, 'rgba(37, 99, 235, .18)');
  grad.addColorStop(1, 'rgba(37, 99, 235, 0)');
  ctx.beginPath();
  ctx.moveTo(sx(0), M.t + ph);
  vals.forEach((v, i) => ctx.lineTo(sx(i), sy(v)));
  ctx.lineTo(sx(n - 1), M.t + ph);
  ctx.closePath();
  ctx.fillStyle = grad;
  ctx.fill();
  // chiziq
  ctx.beginPath();
  vals.forEach((v, i) => (i ? ctx.lineTo(sx(i), sy(v)) : ctx.moveTo(sx(i), sy(v))));
  ctx.strokeStyle = PRIMARY;
  ctx.lineWidth = mini ? 1.6 : 2;
  ctx.stroke();
  // nuqtalar
  vals.forEach((v, i) => {
    const last = i === n - 1;
    if (mini && !last) return;
    ctx.beginPath();
    ctx.arc(sx(i), sy(v), last ? 3.5 : 3, 0, Math.PI * 2);
    ctx.fillStyle = '#fff'; ctx.fill();
    ctx.strokeStyle = PRIMARY; ctx.lineWidth = 2; ctx.stroke();
    if (!mini) {
      ctx.font = `600 10.5px ${MONO}`;
      ctx.fillStyle = '#0f172a';
      ctx.textAlign = i === 0 && n > 1 ? 'left' : i === n - 1 && n > 1 ? 'right' : 'center';
      ctx.textBaseline = 'bottom';
      ctx.fillText(v.toFixed(4), sx(i) + (i === 0 && n > 1 ? -2 : 0), sy(v) - 7);
    }
  });
}

function setupTooltips() {
  const tip = $('tooltip');
  document.querySelectorAll('.chart-wrap canvas').forEach(canvas => {
    canvas.addEventListener('mousemove', e => {
      const pts = hitPoints[canvas.id] || [];
      const rect = canvas.getBoundingClientRect();
      const mx = e.clientX - rect.left;
      const my = e.clientY - rect.top;
      let best = null;
      let bd = 144;
      pts.forEach(p => { const d = (p.x - mx) ** 2 + (p.y - my) ** 2; if (d < bd) { bd = d; best = p; } });
      if (!best) { tip.hidden = true; canvas.style.cursor = 'default'; return; }
      canvas.style.cursor = 'pointer';
      const r = best.row;
      const extra = S.knn && S.point.valid ? S.knn.computed.find(c => c.id === r.id) : null;
      tip.innerHTML = `<b>Ulanish #${r.id}</b> · ${r.label}${best.k === null ? '' : ' · C' + (best.k + 1)}<br>
        ${fmtNum(r.packetSize)} MB · ${fmtNum(r.connections)} soʻrov/s<br>
        <span class="mono">z = ${vec(r.z)}${extra ? ` · d = ${f4(extra.d)}` : ''}</span>`;
      tip.hidden = false;
      tip.style.left = Math.min(e.clientX + 14, window.innerWidth - tip.offsetWidth - 8) + 'px';
      tip.style.top = Math.max(8, e.clientY - tip.offsetHeight - 12) + 'px';
    });
    canvas.addEventListener('mouseleave', () => { tip.hidden = true; });
  });
}

function legendHtml(kind) {
  const sw = (c, t) => `<span class="lg"><i class="sw" style="background:${c}"></i>${t}</span>`;
  const div = '<span class="lg-div"></span>';
  const star = '<span class="lg"><b class="lg-star">★</b>Yangi nuqta</span>';
  if (kind === 'cluster') {
    return CLUSTER_COLORS.map((c, k) => sw(c, `C${k + 1}`)).join('') + sw(NONE_COLOR, 'Klastersiz') + div +
      '<span class="lg"><i class="pt" style="background:#64748b"></i>Shubhali</span><span class="lg"><i class="pt hollow" style="border-color:#64748b"></i>Xavfsiz</span>' + div +
      '<span class="lg"><b class="lg-x">✖</b>Markaz μ</span>';
  }
  return `<span class="lg"><i class="pt" style="background:${CLASS_COLORS.Shubhali}"></i>Shubhali</span>
    <span class="lg"><i class="pt hollow" style="border-color:${CLASS_COLORS.Xavfsiz}"></i>Xavfsiz</span>${div}${star}`;
}

/* =====================================================================
   11. 1-sahifa: Umumiy dashboard
   ===================================================================== */
function renderDashboard() {
  const km = S.km;
  const last = km.log.filter(l => l.type === 'step').pop();
  const p = S.point;

  const counts = { Xavfsiz: 0, Shubhali: 0 };
  S.dataset.forEach(r => { counts[r.label]++; });
  const kmState = km.converged ? 'Yakunlandi' : km.done ? 'Toʻxtatildi' : km.iter === 0 ? 'Boshlanmagan' : 'Jarayonda';
  const waiting = '<span class="note" style="margin:0">Qiymatlarni kiriting</span>';

  $('dash-stats').innerHTML = `
    <a class="card stat" href="#dataset">
      <div class="stat-top"><span class="stat-label"><span class="stat-ic"><svg class="ic"><use href="#i-db"/></svg></span>Tarmoq ulanishlari</span><span class="chip-soft">baza</span></div>
      <div class="stat-main"><span class="stat-value">${S.dataset.length}<small>ta yozuv</small></span>
        <span class="class-bar" style="width:92px;margin:0"><i style="width:${(counts.Xavfsiz / S.dataset.length) * 100}%;background:${CLASS_COLORS.Xavfsiz}"></i><i style="width:${(counts.Shubhali / S.dataset.length) * 100}%;background:${CLASS_COLORS.Shubhali}"></i></span></div>
      <div class="stat-foot"><span>Xavfsiz <b>${counts.Xavfsiz}</b></span><span>Shubhali <b>${counts.Shubhali}</b></span><span>MB: <b>${fmtNum(S.bounds[0].min)}–${fmtNum(S.bounds[0].max)}</b></span></div>
    </a>
    <a class="card stat" href="#knn">
      <div class="stat-top"><span class="stat-label"><span class="stat-ic blue"><svg class="ic"><use href="#i-target"/></svg></span>KNN bashorati</span><span class="chip-soft">k = 3</span></div>
      <div class="stat-main">${p.valid ? `${pill(S.knn.prediction, true)}<span class="stat-value" style="font-size:20px">${S.knn.votes[S.knn.prediction]}/${S.knn.k}<small>ovoz</small></span>` : waiting}</div>
      <div class="stat-foot">${p.valid ? `<span>Qoʻshnilar: <b>${S.knn.neighbors.map(n => '#' + n.id).join(' ')}</b></span><span>d₁ = <b>${f4(S.knn.neighbors[0].d)}</b></span>` : '<span>—</span>'}</div>
    </a>
    <a class="card stat" href="#tree">
      <div class="stat-top"><span class="stat-label"><span class="stat-ic green"><svg class="ic"><use href="#i-tree"/></svg></span>Decision Tree</span><span class="chip-soft">chuqurlik ≤ 2</span></div>
      <div class="stat-main">${p.valid ? `${pill(S.path.leaf.prediction, true)}<span class="mono" style="font-size:13px;color:var(--muted)">barg T${S.path.leaf.uid}</span>` : waiting}</div>
      <div class="stat-foot">${p.valid ? `<span>Yoʻl: <b>${S.path.path.map(id => 'T' + id).join(' → ')}</b></span><span>Gini: <b>${f4(S.path.leaf.gini)}</b></span>` : '<span>—</span>'}</div>
    </a>
    <a class="card stat" href="#kmeans">
      <div class="stat-top"><span class="stat-label"><span class="stat-ic amber"><svg class="ic"><use href="#i-cluster"/></svg></span>K-means · J</span><span class="chip-soft">${kmState.toLowerCase()}</span></div>
      <div class="stat-main"><span class="stat-value">${last ? f4(last.J) : '—'}</span><canvas class="stat-spark" id="spark-j"></canvas></div>
      <div class="stat-foot"><span>Iteratsiya <b>${km.iter}</b></span>${km.assign ? [0, 1, 2].map(k => `<span>C${k + 1} <b>${km.assign.filter(x => x === k).length}</b></span>`).join('') : '<span>hali biriktirilmagan</span>'}</div>
    </a>`;
  chartDrawers.push(() => drawJChart('spark-j', true));

  $('dash-chart-chip').textContent = `${S.rows.length} ta nuqta · K-means: ${km.iter}-iteratsiya`;
  $('legend-dash').innerHTML = legendHtml('cluster') + '<span class="lg-div"></span><span class="lg"><b class="lg-star">★</b>Yangi nuqta</span><span class="lg"><i class="lg-dash" style="border-color:#e11d48"></i>KNN qoʻshnisi</span>';
  chartDrawers.push(() => drawScatter('chart-dash', { color: 'cluster', labels: 'cluster', centers: true, knn: 'lines', newPoint: true, trajectory: true }));

  const nIds = new Set(S.knn ? S.knn.neighbors.map(n => n.id) : []);
  $('dash-table-sub').textContent = `${S.rows.length} ta yozuv · Z qiymatlar joriy min/max chegaralari boʻyicha · KNN qoʻshnilari ajratilgan`;
  $('dash-table').innerHTML = `
    <thead><tr><th class="l">ID</th><th>Paket hajmi (MB)</th><th>Ulanishlar soni (soʻrov/s)</th><th class="l">Sinf</th><th>Z₁</th><th>Z₂</th><th class="c">Klaster</th></tr></thead>
    <tbody>${S.rows.map((r, i) => `
      <tr class="${nIds.has(r.id) ? 'hl' : ''}">
        <td class="id">#${r.id}${nIds.has(r.id) ? '<span class="tag">KNN</span>' : ''}</td>
        <td class="num">${fmtNum(r.packetSize)}</td>
        <td class="num">${fmtNum(r.connections)}</td>
        <td class="l">${pill(r.label)}</td>
        <td class="num">${f4(r.z[0])}</td>
        <td class="num">${f4(r.z[1])}</td>
        <td class="c">${clTag(km.assign ? km.assign[i] : null)}</td>
      </tr>`).join('')}</tbody>`;
}

/* =====================================================================
   12. 2-sahifa: Maʼlumotlar bazasi
   ===================================================================== */
let lastDeleted = null;

function renderDataset() {
  const b = S.bounds;
  const counts = { Xavfsiz: 0, Shubhali: 0 };
  S.dataset.forEach(r => { counts[r.label]++; });
  const n = S.dataset.length;
  const nextId = Math.max(...S.dataset.map(r => r.id)) + 1;

  const boundCard = j => `
    <div class="card stat-card">
      <h4>${FEATURES[j].z} — ${FEATURES[j].name.toLowerCase()} (${FEATURES[j].unit})</h4>
      <div class="minmax">
        <div><span>x<sub>${j + 1},min</sub></span><b>${fmtNum(b[j].min)}</b></div>
        <div><span>x<sub>${j + 1},max</sub></span><b>${fmtNum(b[j].max)}</b></div>
      </div>
      <p class="note">Oraliq: max − min = <span class="mono">${fmtNum(b[j].max - b[j].min)}</span>${b[j].max === b[j].min ? ' → barcha Z = 0' : ''}</p>
    </div>`;

  $('ds-stats').innerHTML = `
    <div class="card stat-card">
      <h4>Min-Max normalizatsiya formulasi</h4>
      <div class="formula-big">z<sub>ij</sub> = ${frac('x<sub>ij</sub> − x<sub>j,min</sub>', 'x<sub>j,max</sub> − x<sub>j,min</sub>')}</div>
      <p class="note">Agar x<sub>j,max</sub> = x<sub>j,min</sub> boʻlsa, z<sub>ij</sub> = 0. Sinf yorligʻi normalizatsiyaga va masofa hisobiga qoʻshilmaydi.</p>
    </div>
    ${boundCard(0)}
    ${boundCard(1)}
    <div class="card stat-card">
      <h4>Baza tarkibi</h4>
      <div class="big-num">${n} <span style="font-size:13px;color:var(--muted);font-family:var(--font);font-weight:500">ta yozuv</span></div>
      <div class="class-bar"><i style="width:${(counts.Xavfsiz / n) * 100}%;background:${CLASS_COLORS.Xavfsiz}"></i><i style="width:${(counts.Shubhali / n) * 100}%;background:${CLASS_COLORS.Shubhali}"></i></div>
      <div class="result-meta"><div>${pill('Xavfsiz')} <b>${counts.Xavfsiz}</b> &nbsp; ${pill('Shubhali')} <b>${counts.Shubhali}</b></div></div>
    </div>`;

  $('ds-next-id').textContent = `Keyingi ID: #${nextId}`;
  $('ds-table-sub').textContent = `${n} ta yozuv · oʻchirish ${n <= MIN_ROWS ? `oʻchirilgan (kamida ${MIN_ROWS} ta yozuv kerak)` : 'har bir qator oxirida'}`;
  const canDel = n > MIN_ROWS;
  $('ds-table').innerHTML = `
    <thead><tr><th class="l">ID</th><th>Paket hajmi (MB)</th><th>Ulanishlar soni (soʻrov/s)</th><th class="l">Sinf</th><th>Z₁</th><th>Z₂</th><th class="c">Amal</th></tr></thead>
    <tbody>${S.rows.map(r => `
      <tr class="${r.id === S.lastAddedId ? 'new-row' : ''}">
        <td class="id">#${r.id}${r.id > 20 ? '<span class="tag new">yangi</span>' : ''}</td>
        <td class="num">${fmtNum(r.packetSize)}</td>
        <td class="num">${fmtNum(r.connections)}</td>
        <td class="l">${pill(r.label)}</td>
        <td class="num">${f4(r.z[0])}</td>
        <td class="num">${f4(r.z[1])}</td>
        <td class="c"><button type="button" class="btn btn-danger-ghost" data-del="${r.id}" ${canDel ? '' : 'disabled'} title="${canDel ? 'Yozuvni oʻchirish' : `Kamida ${MIN_ROWS} ta yozuv qolishi kerak`}">✕ Oʻchirish</button></td>
      </tr>`).join('')}</tbody>`;
  S.lastAddedId = null;
}

function setupDataset() {
  let label = 'Xavfsiz';
  $('ds-label').addEventListener('click', e => {
    const b = e.target.closest('button[data-v]');
    if (!b) return;
    label = b.dataset.v;
    $('ds-label').querySelectorAll('button').forEach(x => x.classList.toggle('on', x === b));
  });

  $('ds-add').addEventListener('submit', e => {
    e.preventDefault();
    const pIn = $('ds-packet');
    const cIn = $('ds-conn');
    const p = Number(pIn.value.replace(',', '.'));
    const c = Number(cIn.value.replace(',', '.'));
    const okP = pIn.value.trim() !== '' && Number.isFinite(p) && p >= 0;
    const okC = cIn.value.trim() !== '' && Number.isFinite(c) && c >= 0;
    pIn.classList.toggle('invalid', !okP);
    cIn.classList.toggle('invalid', !okC);
    const err = $('ds-error');
    if (!okP || !okC) {
      err.textContent = 'Ikkala qiymat ham manfiy boʻlmagan son boʻlishi kerak.';
      err.hidden = false;
      return;
    }
    err.hidden = true;
    const id = Math.max(...S.dataset.map(r => r.id)) + 1;
    S.dataset.push({ id, packetSize: p, connections: c, label });
    S.lastAddedId = id;
    recomputeData(true);
    saveState();
    pIn.value = '';
    cIn.value = '';
    renderCurrent();
    showToast(`#${id} bazaga qoʻshildi — chegaralar, Z va 3 ta algoritm qayta hisoblandi.`);
  });

  $('ds-table').addEventListener('click', e => {
    const b = e.target.closest('button[data-del]');
    if (!b || b.disabled) return;
    const id = Number(b.dataset.del);
    const index = S.dataset.findIndex(r => r.id === id);
    if (index < 0 || S.dataset.length <= MIN_ROWS) return;
    lastDeleted = { row: S.dataset[index], index };
    S.dataset.splice(index, 1);
    recomputeData(true);
    saveState();
    renderCurrent();
    showToast(`#${id} oʻchirildi — barcha hisoblar yangilandi.`, 'Qaytarish', () => {
      if (!lastDeleted) return;
      S.dataset.splice(lastDeleted.index, 0, lastDeleted.row);
      S.lastAddedId = lastDeleted.row.id;
      lastDeleted = null;
      recomputeData(true);
      saveState();
      renderCurrent();
    });
  });

  $('ds-reset').addEventListener('click', () => {
    S.dataset = clone(INITIAL_DATASET);
    S.kmeansState.initIds = DEFAULT_INIT_IDS.slice();
    recomputeData(true);
    saveState();
    renderCurrent();
    showToast('Boshlangʻich 20 talik baza tiklandi.');
  });
}

/* =====================================================================
   13. 3-sahifa: KNN
   ===================================================================== */
function renderKnn() {
  const p = S.point;
  $('legend-knn').innerHTML = legendHtml('class') + '<span class="lg"><i class="lg-dash" style="border-color:#e11d48"></i>Masofa vektori</span>';
  chartDrawers.push(() => drawScatter('chart-knn', { color: 'class', labels: 'id', knn: 'labeled', newPoint: true, zoom: S.knnZoom }));
  document.querySelectorAll('#knn-zoom button').forEach(b => b.classList.toggle('on', (b.dataset.v === 'zoom') === S.knnZoom));

  if (!p.valid) {
    const msg = '<div class="empty-state">Yangi nuqta uchun toʻgʻri qiymatlarni kiriting.</div>';
    ['knn-norm', 'knn-vote'].forEach(id => { $(id).innerHTML = msg; });
    $('knn-sorted').innerHTML = '';
    $('knn-steps').innerHTML = '';
    return;
  }

  // Normalizatsiya — sonlar qoʻyilgan holda
  const b = S.bounds;
  const x = [p.packetSize, p.connections];
  const normLine = j => {
    if (b[j].max === b[j].min) return `<div class="formula-big">${FEATURES[j].z} = 0 <span class="note" style="margin:0 0 0 6px">(barcha qiymatlar teng)</span></div>`;
    return `<div class="formula-big">${FEATURES[j].z} = ${frac(`${fmtNum(x[j])} − ${fmtNum(b[j].min)}`, `${fmtNum(b[j].max)} − ${fmtNum(b[j].min)}`)} = ${frac(fmtNum(x[j] - b[j].min), fmtNum(b[j].max - b[j].min))} = <span class="hl-val">${f4(p.z[j])}</span></div>`;
  };
  const out = p.z.some(z => z < 0 || z > 1);
  $('knn-norm').innerHTML = `
    ${normLine(0)}
    <p class="note" style="margin:0 0 8px">x₁ = ${fmtNum(x[0])} MB, min = ${fmtNum(b[0].min)}, max = ${fmtNum(b[0].max)}</p>
    ${normLine(1)}
    <p class="note" style="margin:0">x₂ = ${fmtNum(x[1])} soʻrov/s, min = ${fmtNum(b[1].min)}, max = ${fmtNum(b[1].max)}</p>
    <div class="calc" style="margin-top:12px">z<sub>yangi</sub> = <b>${vec(p.z)}</b></div>
    ${out ? '<p class="note">Qiymat bazadagi oraliqdan tashqarida, shuning uchun Z ∉ [0, 1]. Bu xato emas: chegaralar faqat bazadan olinadi.</p>' : ''}`;

  const { sorted, neighbors, votes, prediction, computed, tie, k } = S.knn;
  const nIds = new Set(neighbors.map(n => n.id));
  const rankOf = {};
  sorted.forEach((r, i) => { rankOf[r.id] = i + 1; });

  // Saralangan roʻyxat
  $('knn-sorted').innerHTML = `
    <thead><tr><th class="l">Oʻrin</th><th class="l">ID</th><th class="l">Sinf</th><th>Masofa d</th></tr></thead>
    <tbody>${sorted.map((r, i) => `
      <tr class="${i < k ? 'nb' : ''}">
        <td class="l mono">${i + 1}${i < k ? '<span class="tag" style="background:#d1fae5;color:#047857">qoʻshni</span>' : ''}</td>
        <td class="id">#${r.id}</td>
        <td class="l">${pill(r.label)}</td>
        <td class="num"><b>${f4(r.d)}</b></td>
      </tr>`).join('')}</tbody>`;

  // Ovoz berish
  $('knn-vote').innerHTML = `
    <div class="nb-cards">${neighbors.map((n, i) => `
      <div class="nb-card ${i % 2 ? 'k2' : ''}">
        <span class="nb-rank">${i + 1}</span>
        <span><span class="mono" style="font-weight:600">#${n.id}</span> &nbsp;${pill(n.label)}</span>
        <span class="mono">d = ${f4(n.d)}</span>
      </div>`).join('')}</div>
    <div class="votes">${CLASSES.map(c => `
      <div class="vote-row"><span>${c}</span><span class="vote-track"><i class="${c}" style="width:${(votes[c] / k) * 100}%"></i></span><b>${votes[c]}/${k}</b></div>`).join('')}</div>
    <div class="calc">
      <div>N<sub>Xavfsiz</sub> = ${votes.Xavfsiz}, &nbsp; N<sub>Shubhali</sub> = ${votes.Shubhali}</div>
      <div>ŷ = arg max<sub>c</sub> N<sub>c</sub> = <b>${prediction}</b>${tie ? ' (durang — eng yaqin qoʻshni sinfi olindi)' : ''}</div>
    </div>
    <div class="verdict" style="margin:14px 0 0"><div class="verdict-label">Yakuniy bashorat<b>${votes[prediction]} / ${k} ovoz</b></div>${pill(prediction, true)}</div>`;

  // Ochiq hisob jadvali
  const z = p.z;
  $('knn-steps').innerHTML = `
    <thead><tr><th class="l">№</th><th class="l">ID</th><th class="l">Sinf</th><th>Z₁,ᵢ</th><th>Z₂,ᵢ</th><th class="l">Ochiq hisob</th><th>d</th><th class="c">Oʻrin</th></tr></thead>
    <tbody>${computed.map((r, i) => `
      <tr class="${nIds.has(r.id) ? 'nb' : ''}">
        <td class="l mono">${i + 1}</td>
        <td class="id">#${r.id}</td>
        <td class="l">${pill(r.label)}</td>
        <td class="num">${f4(r.z[0])}</td>
        <td class="num">${f4(r.z[1])}</td>
        <td class="formula">√((${f4(z[0])} − ${f4(r.z[0])})² + (${f4(z[1])} − ${f4(r.z[1])})²) = √(${f4(r.d1 ** 2)} + ${f4(r.d2 ** 2)}) = √${f4(r.sq)} = <b>${f4(r.d)}</b></td>
        <td class="num"><b>${f4(r.d)}</b></td>
        <td class="c mono">${rankOf[r.id]}</td>
      </tr>`).join('')}</tbody>`;
}

/* =====================================================================
   14. 4-sahifa: Decision Tree
   ===================================================================== */
function giniExpand(counts, n) {
  if (!n) return 'n = 0 → G = 0';
  const parts = CLASSES.map(c => `(${counts[c]}/${n})²`).join(' + ');
  const vals = CLASSES.map(c => f4((counts[c] / n) ** 2)).join(' + ');
  const g = 1 - CLASSES.reduce((s, c) => s + (counts[c] / n) ** 2, 0);
  return `1 − (${parts}) = 1 − (${vals}) = <span class="res">${f4(g)}</span>`;
}

function buildTreeSvg() {
  const root = S.tree;
  const pathSet = new Set(S.path ? S.path.path : []);
  const NW = 216, NH = 100, GX = 28, GY = 64, PAD = 8;
  let leafIdx = 0;
  const pos = {};
  const place = node => {
    if (node.leaf) { pos[node.uid] = { x: PAD + leafIdx * (NW + GX) + NW / 2, y: PAD + node.depth * (NH + GY) }; leafIdx++; return; }
    place(node.left);
    place(node.right);
    pos[node.uid] = { x: (pos[node.left.uid].x + pos[node.right.uid].x) / 2, y: PAD + node.depth * (NH + GY) };
  };
  place(root);
  const nodes = treeNodes(root);
  const maxDepth = Math.max(...nodes.map(n => n.depth));
  const W = PAD * 2 + leafIdx * NW + (leafIdx - 1) * GX;
  const H = PAD * 2 + (maxDepth + 1) * NH + maxDepth * GY;

  let edges = '';
  let labels = '';
  nodes.filter(n => !n.leaf).forEach(n => {
    const p = pos[n.uid];
    [[n.left, 'Ha · ≤'], [n.right, 'Yoʻq · >']].forEach(([c, txt]) => {
      const q = pos[c.uid];
      const active = pathSet.has(n.uid) && pathSet.has(c.uid);
      const y0 = p.y + NH;
      const my = (y0 + q.y) / 2;
      edges += `<path class="tedge ${active ? 'active' : ''}" d="M${p.x},${y0} C${p.x},${my} ${q.x},${my} ${q.x},${q.y}"/>`;
      const lx = (p.x + q.x) / 2;
      const w = txt.length * 6.4 + 16;
      labels += `<g class="tedge-label ${active ? 'active' : ''}" transform="translate(${lx - w / 2},${my - 10})"><rect width="${w}" height="20" rx="10"/><text x="${w / 2}" y="14" text-anchor="middle">${txt}</text></g>`;
    });
  });

  const esc = s => s.replace(/</g, '&lt;').replace(/>/g, '&gt;');
  const nodeSvg = nodes.map(n => {
    const p = pos[n.uid];
    const active = pathSet.has(n.uid);
    const x = p.x - NW / 2;
    const lines = n.leaf
      ? `<text x="14" y="46" class="tnode-pred-${n.prediction}">→ ${n.prediction}</text>`
      : `<text x="14" y="46" class="tnode-cond">${esc(`${FEATURES[n.feature].z} ≤ ${f4(n.threshold)}`)}</text>`;
    return `<g class="tnode ${active ? 'active' : ''}" transform="translate(${x},${p.y})">
      <rect class="tnode-rect" width="${NW}" height="${NH}" rx="10"/>
      ${active ? `<rect width="4" height="${NH - 16}" y="8" rx="2" fill="${PRIMARY}"/>` : ''}
      <text x="14" y="21" class="tnode-title">T${n.uid} · ${n.leaf ? 'barg' : 'tugun'} · chuqurlik ${n.depth}</text>
      ${lines}
      <text x="14" y="68" class="tnode-line">Gini = ${f4(n.gini)} · n = ${n.n}</text>
      <text x="14" y="87" class="tnode-line">Xavfsiz: ${n.counts.Xavfsiz}, Shubhali: ${n.counts.Shubhali}</text>
    </g>`;
  }).join('');

  return `<svg viewBox="0 0 ${W} ${H}" width="${W}" style="width:100%;max-width:${W}px;min-width:${Math.min(W, 480)}px" role="img" aria-label="Qaror daraxti sxemasi">${edges}${nodeSvg}${labels}</svg>`;
}

function renderTree() {
  $('tree-svg').innerHTML = buildTreeSvg();
  $('legend-tree').innerHTML = legendHtml('class') +
    `<span class="lg-div"></span><span class="lg"><i class="sw" style="background:${hexA(CLASS_COLORS.Xavfsiz, .25)}"></i>Xavfsiz hududi</span>
     <span class="lg"><i class="sw" style="background:${hexA(CLASS_COLORS.Shubhali, .25)}"></i>Shubhali hududi</span>
     <span class="lg"><i class="lg-dash" style="border-color:#2563eb"></i>Ajratish chizigʻi</span>`;
  chartDrawers.push(() => drawScatter('chart-tree', { color: 'class', labels: 'id', knn: 'none', newPoint: true, regions: true }));

  if (S.point.valid) {
    $('tree-pred').innerHTML = pill(S.path.leaf.prediction, true);
    const z = S.point.z;
    const parts = S.path.steps.map(s => {
      const j = s.node.feature;
      return `<code>T${s.node.uid}: ${FEATURES[j].z} = ${f4(z[j])} ${s.goLeft ? '≤' : '&gt;'} ${f4(s.node.threshold)} → ${s.goLeft ? 'Ha' : 'Yoʻq'}</code>`;
    });
    parts.push(`<code>T${S.path.leaf.uid} barg → ${S.path.leaf.prediction}</code>`);
    $('tree-path').innerHTML = `<b style="color:var(--text)">Yangi nuqta yoʻli:</b> ${parts.join(' → ')}`;
  } else {
    $('tree-pred').innerHTML = '';
    $('tree-path').textContent = 'Yangi nuqta uchun toʻgʻri qiymatlarni kiriting.';
  }

  const internal = treeNodes(S.tree).filter(n => !n.leaf);
  const leaves = treeNodes(S.tree).filter(n => n.leaf);

  const nodeCard = (n, idx) => {
    const s = n.split;
    const j = s.feature;
    const fz = FEATURES[j].z;
    const rows = n.candidates.map((c, i) => `
      <tr class="${c === s ? 'best' : ''}">
        <td class="l mono">${i + 1}</td>
        <td class="l">${FEATURES[c.feature].z}</td>
        <td class="num">${f4(c.lo)}</td>
        <td class="num">${f4(c.hi)}</td>
        <td class="num"><b>${f4(c.threshold)}</b></td>
        <td class="num">${c.nL} (${c.countsL.Xavfsiz}/${c.countsL.Shubhali})</td>
        <td class="num">${f4(c.gL)}</td>
        <td class="num">${c.nR} (${c.countsR.Xavfsiz}/${c.countsR.Shubhali})</td>
        <td class="num">${f4(c.gR)}</td>
        <td class="num"><b>${f4(c.gw)}</b>${c === s ? '<span class="tag" style="background:#d1fae5;color:#047857">min</span>' : ''}</td>
      </tr>`).join('');
    return `
    <div class="card">
      <div class="card-head">
        <div><span class="eyebrow">${idx + 1}-hisob · chuqurlik ${n.depth}</span><h3>T${n.uid} tugun — ${n.n} ta yozuv</h3>
          <p class="card-sub">Tugundagi yozuvlar: <span class="mono">${n.ids.map(id => '#' + id).join(' ')}</span></p></div>
        <span class="chip-soft mono">tanlandi: ${fz} ≤ ${f4(s.threshold)}</span>
      </div>
      <div class="node-grid">
        <div>
          <div class="mini-head">a) Tugun Ginisi</div>
          <div class="calc">
            <div>Xavfsiz = ${n.counts.Xavfsiz}, Shubhali = ${n.counts.Shubhali}, n = ${n.n}</div>
            <div>G = ${giniExpand(n.counts, n.n)}</div>
          </div>
        </div>
        <div>
          <div class="mini-head">b) Eng yaxshi shart: ${fz} ≤ ${f4(s.threshold)}</div>
          <div class="calc">
            <div>chegara = (${f4(s.lo)} + ${f4(s.hi)}) / 2 = <b>${f4(s.threshold)}</b></div>
            <div>Chap (≤): n<sub>L</sub> = ${s.nL} → Xavfsiz ${s.countsL.Xavfsiz}, Shubhali ${s.countsL.Shubhali}</div>
            <div>G<sub>L</sub> = ${giniExpand(s.countsL, s.nL)}</div>
            <div>Oʻng (&gt;): n<sub>R</sub> = ${s.nR} → Xavfsiz ${s.countsR.Xavfsiz}, Shubhali ${s.countsR.Shubhali}</div>
            <div>G<sub>R</sub> = ${giniExpand(s.countsR, s.nR)}</div>
          </div>
        </div>
        <div>
          <div class="mini-head">c) Vaznli Gini</div>
          <div class="calc">
            <div>G<sub>ajratish</sub> = (n<sub>L</sub>/n)·G<sub>L</sub> + (n<sub>R</sub>/n)·G<sub>R</sub></div>
            <div>= (${s.nL}/${n.n})·${f4(s.gL)} + (${s.nR}/${n.n})·${f4(s.gR)}</div>
            <div>= ${f4((s.nL / n.n) * s.gL)} + ${f4((s.nR / n.n) * s.gR)} = <b>${f4(s.gw)}</b></div>
          </div>
          <p class="note">Bu ${n.candidates.length} ta nomzod ichida eng kichik vaznli Gini. Gini kamayishi: ${f4(n.gini)} → ${f4(s.gw)}.</p>
        </div>
      </div>
      <details class="details" style="margin-top:14px" ${idx === 0 ? 'open' : ''}>
        <summary>Barcha nomzod chegaralar (oʻrta nuqtalar) <span class="sum-right">${n.candidates.length} ta</span></summary>
        <div class="details-body">
          <p class="note" style="margin-top:0">Har bir parametrning tartiblangan turli qiymatlari v<sub>i</sub>, v<sub>i+1</sub> orasidagi oʻrta nuqta. Qavsda — Xavfsiz/Shubhali soni.</p>
          <div class="table-scroll"><table>
            <thead><tr><th class="l">№</th><th class="l">Par.</th><th>vᵢ</th><th>vᵢ₊₁</th><th>Chegara</th><th>n<sub>L</sub></th><th>G<sub>L</sub></th><th>n<sub>R</sub></th><th>G<sub>R</sub></th><th>G<sub>ajratish</sub></th></tr></thead>
            <tbody>${rows}</tbody>
          </table></div>
        </div>
      </details>
    </div>`;
  };

  const leafCard = `
    <div class="card">
      <div class="card-head"><div><h3>Barglar — koʻpchilik sinf</h3><p class="card-sub">Barg tugunida qaysi sinf koʻp boʻlsa, oʻsha bashorat qilinadi</p></div></div>
      <div class="table-scroll"><table>
        <thead><tr><th class="l">Barg</th><th class="c">Chuqurlik</th><th>n</th><th>Xavfsiz</th><th>Shubhali</th><th>Gini</th><th class="l">Toʻxtash sababi</th><th class="l">Bashorat</th></tr></thead>
        <tbody>${leaves.map(l => `
          <tr class="${S.path && S.path.leaf.uid === l.uid ? 'hl' : ''}">
            <td class="id">T${l.uid}</td><td class="c">${l.depth}</td><td class="num">${l.n}</td>
            <td class="num">${l.counts.Xavfsiz}</td><td class="num">${l.counts.Shubhali}</td><td class="num">${f4(l.gini)}</td>
            <td class="l">${l.reason}</td><td class="l">${pill(l.prediction)}</td>
          </tr>`).join('')}</tbody>
      </table></div>
    </div>`;

  $('tree-steps').innerHTML = `<div class="node-steps">${internal.length
    ? internal.map(nodeCard).join('')
    : '<div class="card"><div class="empty-state">Ildiz tugun allaqachon toza (Gini = 0) — ajratish kerak emas.</div></div>'}${leafCard}</div>`;
}

/* =====================================================================
   15. 5-sahifa: K-means
   ===================================================================== */
function renderKMeans() {
  const km = S.km;
  const rows = S.rows;
  const opts = rows.map(r => `<option value="${r.id}">#${r.id}</option>`).join('');
  [0, 1, 2].forEach(i => {
    const sel = $('km-init-' + i);
    sel.innerHTML = opts;
    sel.value = String(S.kmeansState.initIds[i]);
  });
  $('km-step').disabled = km.done;
  $('km-run').disabled = km.done;

  const steps = km.log.filter(l => l.type === 'step');
  const last = steps[steps.length - 1];
  const prev = steps[steps.length - 2];
  const state = km.converged ? 'Yakunlandi' : km.done ? 'Toʻxtatildi' : km.iter === 0 ? 'Tayyor' : 'Jarayonda';
  const stateFoot = km.converged ? 'oʻzgarish yoʻq' : km.done ? `limit: ${MAX_ITER}` : km.iter === 0 ? 'kutilmoqda' : `${last.changed === rows.length && km.iter === 1 ? 'birinchi biriktirish' : last.changed + ' ta oʻzgardi'}`;
  $('km-kpis').innerHTML = `
    <div class="kpi" id="kpi-iter"><span class="kpi-label">Iteratsiya</span><span class="kpi-value">${km.iter}</span><span class="kpi-foot">maks. ${MAX_ITER}</span></div>
    <div class="kpi" id="kpi-j"><span class="kpi-label">J xatolik</span><span class="kpi-value">${last ? f4(last.J) : '—'}</span><span class="kpi-foot">${last && prev ? '▼ ' + f4(prev.J - last.J) : 'Σ‖z − μ‖²'}</span></div>
    <div class="kpi ${km.done ? 'done' : ''}"><span class="kpi-label">Holat</span><span class="kpi-value text">${state}</span><span class="kpi-foot">${stateFoot}</span></div>`;

  const st = $('km-status');
  if (km.converged) {
    st.className = 'status done';
    st.innerHTML = `<span>✓</span><span>Biriktirishlar oʻzgarmadi — algoritm ${km.iter}-iteratsiyada yaqinlashdi.</span>`;
    st.hidden = false;
  } else if (km.done) {
    st.className = 'status info';
    st.textContent = `Maksimal iteratsiyalar soniga (${MAX_ITER}) yetildi.`;
    st.hidden = false;
  } else {
    st.hidden = true;
  }

  const label = km.iter === 0 ? 'boshlangʻich' : 'yangilangan';
  $('km-clusters').innerHTML = [0, 1, 2].map(k => {
    const members = km.assign ? rows.filter((r, i) => km.assign[i] === k) : [];
    const c = km.centers[k];
    return `<div class="cluster k${k}">
      <div class="cluster-top">${clTag(k)}<span class="cluster-n">${km.assign ? members.length + ' ta' : '—'}</span></div>
      <div class="cluster-center">μ${k + 1} = ${vec(c)} <span class="cluster-orig">${label}</span></div>
      <div class="cluster-orig">≈ ${origOf(0, c[0])}, ${origOf(1, c[1])}</div>
      <div class="ids">${!km.assign ? '<span class="empty">hali biriktirilmagan</span>' : members.length ? members.map(m => `<span class="id-chip">#${m.id}</span>`).join('') : '<span class="empty">boʻsh klaster</span>'}</div>
    </div>`;
  }).join('');

  $('km-chart-chip').textContent = km.converged ? `Yakunlandi · ${km.iter} iteratsiya` : `Iteratsiya ${km.iter}`;
  $('legend-km').innerHTML = legendHtml('cluster') + '<span class="lg-div"></span><span class="lg"><i class="lg-line" style="border-color:#94a3b8"></i>Klaster nuri</span><span class="lg"><i class="lg-dash" style="border-color:#64748b"></i>Markaz harakati</span>';
  chartDrawers.push(() => drawScatter('chart-km', { color: 'cluster', labels: 'cluster', centers: true, rays: true, trajectory: true, knn: 'none', newPoint: false }));
  chartDrawers.push(() => drawJChart('chart-j', false));

  renderKmLog();
}

function distTable(entry, prevAssign) {
  const rows = S.rows;
  return `<div class="table-scroll"><table>
    <thead><tr><th class="l">ID</th><th>Z₁</th><th>Z₂</th><th>d(z, μ₁)</th><th>d(z, μ₂)</th><th>d(z, μ₃)</th><th class="c">Klaster</th></tr></thead>
    <tbody>${rows.map((r, i) => {
      const a = entry.assign[i];
      const moved = prevAssign && prevAssign[i] !== a;
      return `<tr>
        <td class="id">#${r.id}</td>
        <td class="num">${f4(r.z[0])}</td><td class="num">${f4(r.z[1])}</td>
        ${entry.dists[i].map((d, k) => `<td class="num ${k === a ? 'minc' : ''}">${f4(d)}</td>`).join('')}
        <td class="c">${clTag(a)}${moved ? `<span class="tag new">C${prevAssign[i] + 1}→C${a + 1}</span>` : ''}</td>
      </tr>`;
    }).join('')}</tbody></table></div>`;
}

function renderKmLog() {
  const km = S.km;
  const rows = S.rows;
  const initHtml = `
    <details class="details" ${km.log.length ? '' : 'open'}>
      <summary>Boshlangʻich holat (0-iteratsiya) <span class="sum-right">μ = z(#${km.initIds.join('), z(#')})</span></summary>
      <div class="details-body"><div class="calc">${km.initialCenters.map((c, k) => `<div>μ${sub(k + 1)} = z(#${km.initIds[k]}) = <b>${vec(c)}</b></div>`).join('')}</div>
      ${km.log.length ? '' : '<p class="note">«Keyingi qadam» tugmasini bosing — birinchi iteratsiya shu yerda paydo boʻladi.</p>'}</div>
    </details>`;

  let prevAssign = null;
  const entries = km.log.map((e, idx) => {
    const isLast = idx === km.log.length - 1;
    const centersLine = e.oldCenters.map((c, k) => `μ${sub(k + 1)} = ${vec(c)}`).join(', &nbsp; ');
    let html;
    if (e.type === 'check') {
      html = `
      <details class="details" ${isLast ? 'open' : ''}>
        <summary>Iteratsiya ${e.iter} — tekshiruv <span class="log-badge ok">yaqinlashdi</span><span class="sum-right">0 ta oʻzgarish</span></summary>
        <div class="details-body">
          <div class="step-title"><span class="step-no">1</span>Biriktirish (joriy markazlar bilan)</div>
          <div class="calc" style="margin-bottom:10px">${centersLine}</div>
          ${distTable(e, prevAssign)}
          <div class="status done" style="margin-top:12px"><span>✓</span><span>Barcha ${rows.length} ta nuqta oldingi iteratsiyadagi klasterida qoldi → markazlar oʻzgarmaydi, jarayon yakunlandi.</span></div>
        </div>
      </details>`;
    } else {
      const centerCalc = e.clusters.map((c, k) => {
        if (c.empty) return `<div>μ${sub(k + 1)}: C${k + 1} boʻsh → markaz oʻzgarmaydi = <b>${vec(c.center)}</b></div>`;
        const s1 = c.idx.map(i => f4(rows[i].z[0])).join(' + ');
        const s2 = c.idx.map(i => f4(rows[i].z[1])).join(' + ');
        return `<div class="mini-head" style="margin-top:6px">C${k + 1} = {${c.ids.map(id => '#' + id).join(', ')}}, |C${k + 1}| = ${c.n}</div>
          <div>ΣZ₁ = ${s1} = ${f4(c.sum[0])}</div>
          <div>ΣZ₂ = ${s2} = ${f4(c.sum[1])}</div>
          <div>μ${sub(k + 1)} = (1/${c.n})·(${f4(c.sum[0])}, ${f4(c.sum[1])}) = <b>${vec(c.center)}</b></div>`;
      }).join('');
      const jCalc = e.clusters.map((c, k) => {
        if (c.empty) return `<div>J${sub(k + 1)} = 0 (boʻsh klaster)</div>`;
        const terms = c.idx.map(i => f4(e.sq[i])).join(' + ');
        return `<div>J${sub(k + 1)} = Σ‖z − μ${sub(k + 1)}‖² = ${terms} = <b>${f4(e.Jparts[k])}</b></div>`;
      }).join('');
      const sqRows = rows.map((r, i) => {
        const k = e.assign[i];
        const m = e.newCenters[k];
        return `<tr><td class="id">#${r.id}</td><td class="c">${clTag(k)}</td>
          <td class="formula">(${f4(r.z[0])} − ${f4(m[0])})² + (${f4(r.z[1])} − ${f4(m[1])})²</td>
          <td class="num"><b>${f4(e.sq[i])}</b></td></tr>`;
      }).join('');
      html = `
      <details class="details" ${isLast ? 'open' : ''}>
        <summary>Iteratsiya ${e.iter} <span class="log-badge">${e.iter === 1 ? 'birinchi biriktirish' : e.changed + ' ta oʻzgardi'}</span><span class="sum-right">J = ${f4(e.J)}</span></summary>
        <div class="details-body">
          <div class="step-title"><span class="step-no">1</span>Har bir nuqtani eng yaqin markazga biriktirish</div>
          <div class="calc" style="margin-bottom:10px">${centersLine}</div>
          ${distTable(e, prevAssign)}
          <div class="step-title"><span class="step-no">2</span><span>Markazlarni yangilash: μ<sub>r</sub> = (1/|C<sub>r</sub>|) Σ z<sub>i</sub></span></div>
          <div class="calc">${centerCalc}</div>
          <div class="step-title"><span class="step-no">3</span>Klaster ichidagi kvadrat masofalar yigʻindisi J</div>
          <div class="calc">${jCalc}<div>J = ${e.Jparts.map(f4).join(' + ')} = <b>${f4(e.J)}</b></div></div>
          <details class="details" style="margin-top:10px">
            <summary>Har bir nuqta uchun ‖z − μ‖² hisobi</summary>
            <div class="details-body"><div class="table-scroll"><table>
              <thead><tr><th class="l">ID</th><th class="c">Klaster</th><th class="l">Ochiq hisob (yangi markaz bilan)</th><th>‖z − μ‖²</th></tr></thead>
              <tbody>${sqRows}</tbody></table></div></div>
          </details>
        </div>
      </details>`;
    }
    prevAssign = e.assign;
    return html;
  });
  $('km-log').innerHTML = initHtml + entries.join('');
}

let kmStepAction = null;

function setupKMeans() {
  const step = () => {
    if (S.km.done) return;
    kmeansStep(S.km, S.rows);
    S.kmeansState.steps++;
    saveState();
    renderCurrent();
    flashKpi($('kpi-iter'));
    flashKpi($('kpi-j'));
  };
  $('km-step').addEventListener('click', step);
  kmStepAction = step;
  $('km-run').addEventListener('click', () => {
    while (!S.km.done) { kmeansStep(S.km, S.rows); S.kmeansState.steps++; }
    saveState();
    renderCurrent();
  });
  $('km-reset').addEventListener('click', () => {
    S.kmeansState.steps = 0;
    rebuildKMeans();
    saveState();
    renderCurrent();
  });
  [0, 1, 2].forEach(i => $('km-init-' + i).addEventListener('change', () => {
    const ids = [0, 1, 2].map(j => Number($('km-init-' + j).value));
    if (!distinctVectors(ids)) {
      showToast('Uchta turli ulanishni (turli vektorlarni) tanlang.');
      $('km-init-' + i).value = String(S.kmeansState.initIds[i]);
      return;
    }
    S.kmeansState.initIds = ids;
    S.kmeansState.steps = 0;
    rebuildKMeans();
    saveState();
    renderCurrent();
  }));
}

/* =====================================================================
   16. Ishga tushirish
   ===================================================================== */
function init() {
  loadState();
  recomputeData(false);
  buildPointForms();
  setupDataset();
  setupKMeans();
  setupTooltips();
  syncPointForms(true);
  $('knn-zoom').addEventListener('click', e => {
    const b = e.target.closest('button[data-v]');
    if (!b) return;
    S.knnZoom = b.dataset.v === 'zoom';
    renderCurrent();
  });

  window.addEventListener('hashchange', routeFromHash);

  // Boshqa brauzer oynasida holat oʻzgarsa — shu oynani ham sinxronlash
  window.addEventListener('storage', e => {
    if (e.key !== STORAGE_KEY || !e.newValue) return;
    try {
      applyStored(JSON.parse(e.newValue));
      recomputeData(false);
      syncPointForms(true);
      renderCurrent({ skipForms: true });
      updateSaveIndicator(true);
      showToast('Boshqa oynadagi oʻzgarishlar sinxronlandi.');
    } catch (err) { /* eʼtiborsiz */ }
  });

  // Klaviatura yorliqlari: 1–5 — boʻlimlar, N — K-means keyingi qadami
  document.addEventListener('keydown', e => {
    if (e.ctrlKey || e.metaKey || e.altKey) return;
    const tag = (e.target.tagName || '').toLowerCase();
    if (tag === 'input' || tag === 'select' || tag === 'textarea') return;
    const idx = ['1', '2', '3', '4', '5'].indexOf(e.key);
    if (idx >= 0) { location.hash = '#' + PAGES[idx]; return; }
    if ((e.key === 'n' || e.key === 'N') && kmStepAction) {
      if (S.km.done) { showToast('K-means allaqachon yakunlangan.'); return; }
      kmStepAction();
      if (S.page !== 'kmeans') showToast(`K-means: ${S.km.iter}-iteratsiya bajarildi.`);
    }
  });

  // Barcha holatni tozalash (bekor qilish imkoniyati bilan)
  $('reset-all').addEventListener('click', () => {
    const snapshot = { dataset: clone(S.dataset), newPoint: clone(S.newPoint), kmeansState: clone(S.kmeansState) };
    const d = defaultState();
    S.dataset = d.dataset;
    S.newPoint = d.newPoint;
    S.kmeansState = d.kmeansState;
    try { localStorage.removeItem(STORAGE_KEY); } catch (err) { /* eʼtiborsiz */ }
    recomputeData(false);
    saveState();
    syncPointForms(true);
    renderCurrent({ skipForms: true });
    showToast('Barcha holat boshlangʻich koʻrinishga qaytarildi.', 'Bekor qilish', () => {
      S.dataset = snapshot.dataset;
      S.newPoint = snapshot.newPoint;
      S.kmeansState = snapshot.kmeansState;
      recomputeData(false);
      saveState();
      syncPointForms(true);
      renderCurrent({ skipForms: true });
    });
  });
  updateSaveIndicator(false);

  let t = null;
  const redraw = () => { clearTimeout(t); t = setTimeout(() => chartDrawers.forEach(fn => fn()), 60); };
  if ('ResizeObserver' in window) new ResizeObserver(redraw).observe(document.querySelector('.page'));
  else window.addEventListener('resize', redraw);
  if (document.fonts && document.fonts.ready) document.fonts.ready.then(redraw);

  routeFromHash();
}

if (typeof document !== 'undefined') document.addEventListener('DOMContentLoaded', init);
