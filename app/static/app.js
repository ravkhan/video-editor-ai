"use strict";

// ------------------------------------------------------------------ helpers

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") node.className = v;
    else if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
    else if (v !== false && v != null) node.setAttribute(k, v === true ? "" : v);
  }
  node.append(...children.filter((c) => c != null));
  return node;
}

function fmtTime(sec) {
  sec = Math.max(0, sec || 0);
  const ms = Math.round(sec * 1000);
  const h = Math.floor(ms / 3600000);
  const m = Math.floor((ms % 3600000) / 60000);
  const s = Math.floor((ms % 60000) / 1000);
  const rest = String(ms % 1000).padStart(3, "0");
  const mm = h ? String(m).padStart(2, "0") : String(m);
  return `${h ? h + ":" : ""}${mm}:${String(s).padStart(2, "0")}.${rest}`;
}

function parseTime(text) {
  text = String(text).trim().replace(",", ".");
  if (!/^(\d+:){0,2}\d+(\.\d+)?$/.test(text)) return NaN;
  return text.split(":").reduce((acc, part) => acc * 60 + parseFloat(part), 0);
}

function fmtDuration(sec) {
  return fmtTime(sec).replace(/\.\d+$/, "");
}

function fmtSize(bytes) {
  if (bytes > 1e9) return (bytes / 1e9).toFixed(1) + " ГБ";
  return (bytes / 1e6).toFixed(1) + " МБ";
}

let toastTimer;
function toast(message, isError = false) {
  const node = $("#toast");
  node.textContent = message;
  node.classList.toggle("error", isError);
  node.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => (node.hidden = true), isError ? 6000 : 3000);
}

async function api(path, options = {}) {
  const opts = { ...options };
  if (opts.json !== undefined) {
    opts.body = JSON.stringify(opts.json);
    opts.headers = { "Content-Type": "application/json", ...(opts.headers || {}) };
    delete opts.json;
  }
  const res = await fetch(path, opts);
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
    } catch { /* not JSON */ }
    throw new Error(detail);
  }
  return res.status === 204 ? null : res.json();
}

function newId() {
  return Math.random().toString(16).slice(2, 12);
}

// -------------------------------------------------------------------- state

const state = {
  config: null,
  project: null,
  segments: [],
  style: null,
  activeId: null,
  jobStatus: {},
  pollTimer: null,
  saveTimer: null,
  styleTimer: null,
  savePromise: null,
  dirty: false,
};

const video = $("#video");

// ------------------------------------------------------------------- router

async function route() {
  const match = location.hash.match(/^#\/p\/([0-9a-f]{32})$/);
  stopPolling();
  await flushSave();
  await flushStyle().catch(() => {});
  if (match) {
    await openProject(match[1]);
  } else {
    showHome();
  }
}

window.addEventListener("hashchange", route);
window.addEventListener("beforeunload", (e) => {
  if (state.dirty) {
    flushSave();
    e.preventDefault();
  }
});

// --------------------------------------------------------------------- home

async function showHome() {
  $("#editor-view").hidden = true;
  $("#home-view").hidden = false;
  $("#project-title").textContent = "";
  $("#save-status").textContent = "";
  video.removeAttribute("src");
  video.load();
  state.project = null;
  try {
    renderProjectList(await api("/api/projects"));
  } catch (err) {
    toast("Не удалось загрузить проекты: " + err.message, true);
  }
}

function renderProjectList(projects) {
  const list = $("#project-list");
  list.replaceChildren();
  $("#project-empty").hidden = projects.length > 0;
  for (const p of projects) {
    const date = new Date(p.created * 1000).toLocaleString("ru-RU", { dateStyle: "short", timeStyle: "short" });
    list.append(
      el("a", { class: "project-card", href: `#/p/${p.id}` },
        el("div", { class: "name", title: p.name }, p.name),
        el("div", { class: "meta" },
          el("span", {}, fmtDuration(p.duration)),
          el("span", {}, `${p.width}×${p.height}`),
          el("span", {}, `${p.segments.length} субт.`),
        ),
        el("div", { class: "meta" },
          el("span", {}, date),
          el("button", {
            class: "delete",
            onclick: async (e) => {
              e.preventDefault();
              if (!confirm(`Удалить проект «${p.name}»?`)) return;
              try {
                await api(`/api/projects/${p.id}`, { method: "DELETE" });
                showHome();
              } catch (err) {
                toast(err.message, true);
              }
            },
          }, "Удалить"),
        ),
      ),
    );
  }
}

// Upload ------------------------------------------------------------------

const dropzone = $("#dropzone");
["dragenter", "dragover"].forEach((t) =>
  dropzone.addEventListener(t, (e) => { e.preventDefault(); dropzone.classList.add("drag"); }));
["dragleave", "drop"].forEach((t) =>
  dropzone.addEventListener(t, (e) => { e.preventDefault(); dropzone.classList.remove("drag"); }));
dropzone.addEventListener("drop", (e) => {
  const file = e.dataTransfer.files[0];
  if (file) uploadFile(file);
});
$("#file-input").addEventListener("change", (e) => {
  const file = e.target.files[0];
  e.target.value = "";
  if (file) uploadFile(file);
});

function uploadFile(file) {
  const progress = $("#upload-progress");
  const bar = $(".progress-bar", progress);
  const label = $("span", progress);
  const error = $("#upload-error");
  error.hidden = true;
  progress.hidden = false;
  bar.style.width = "0";
  label.textContent = "Загрузка…";

  const form = new FormData();
  form.append("file", file);
  const xhr = new XMLHttpRequest();
  xhr.open("POST", "/api/projects");
  xhr.upload.onprogress = (e) => {
    if (!e.lengthComputable) return;
    const pct = Math.round((e.loaded / e.total) * 100);
    bar.style.width = pct + "%";
    label.textContent = pct < 100 ? `Загрузка ${pct}%` : "Анализ видео…";
  };
  xhr.onload = () => {
    progress.hidden = true;
    let body = {};
    try { body = JSON.parse(xhr.responseText); } catch { /* ignore */ }
    if (xhr.status === 201) {
      location.hash = `#/p/${body.id}`;
    } else {
      error.textContent = "Ошибка загрузки: " + (body.detail || xhr.statusText);
      error.hidden = false;
    }
  };
  xhr.onerror = () => {
    progress.hidden = true;
    error.textContent = "Ошибка сети при загрузке файла";
    error.hidden = false;
  };
  xhr.send(form);
}

// ------------------------------------------------------------------- editor

async function openProject(id) {
  let project;
  try {
    project = await api(`/api/projects/${id}`);
  } catch (err) {
    toast(err.message, true);
    location.hash = "#/";
    return;
  }
  state.project = project;
  state.segments = project.segments.map((s) => ({ ...s }));
  state.style = { ...state.config.default_style, ...project.style };
  state.jobStatus = Object.fromEntries(Object.entries(project.jobs).map(([k, j]) => [k, j.status]));
  state.dirty = false;

  $("#home-view").hidden = true;
  $("#editor-view").hidden = false;
  $("#project-title").textContent = project.name;
  $("#save-status").textContent = "";

  layoutStage();
  loadVideo();
  fillStyleForm();
  renderSegments();
  renderJobs(project);
  updateExportLinks();
  selectTab(state.segments.length ? "segments" : "transcribe");
  if (hasActiveJobs(project)) startPolling();
}

function loadVideo() {
  const p = state.project;
  const preparing = ["queued", "running"].includes(p.jobs.preview?.status);
  const overlay = $("#stage-overlay");
  if (p.jobs.preview?.status === "error") {
    overlay.hidden = false;
    overlay.textContent = "Не удалось подготовить видео для просмотра: " + p.jobs.preview.error;
    return;
  }
  if (preparing) {
    overlay.hidden = false;
    overlay.textContent = `Подготовка видео для браузера… ${Math.round((p.jobs.preview.progress || 0) * 100)}%`;
    return;
  }
  overlay.hidden = true;
  const src = `/api/projects/${p.id}/media`;
  if (!video.src.endsWith(src)) {
    video.src = src;
  }
}

// Stage sizing: keep the video's aspect ratio inside the available box -----

function layoutStage() {
  const p = state.project;
  if (!p) return;
  const box = $("#stage-box");
  const stage = $("#stage");
  const scale = Math.min(box.clientWidth / p.width, box.clientHeight / p.height);
  stage.style.width = Math.floor(p.width * scale) + "px";
  stage.style.height = Math.floor(p.height * scale) + "px";
  applyCaptionStyle();
}
new ResizeObserver(layoutStage).observe($("#stage-box"));

// Caption preview -----------------------------------------------------------

function hexToRgba(hex, alpha) {
  const n = parseInt(hex.slice(1), 16);
  return `rgba(${(n >> 16) & 255}, ${(n >> 8) & 255}, ${n & 255}, ${alpha})`;
}

function applyCaptionStyle() {
  const s = state.style;
  const stage = $("#stage");
  if (!s || !state.project) return;
  const scale = stage.clientHeight / 1080;
  const caption = $("#caption");
  // libass font size ≈ line height; CSS font-size is the em box, hence 0.86.
  caption.style.fontFamily = `"${s.font}", "DejaVu Sans", sans-serif`;
  caption.style.fontSize = s.size * scale * 0.86 + "px";
  caption.style.fontWeight = s.bold ? "700" : "400";
  caption.style.color = s.color;
  caption.style.padding = `0 ${40 * scale}px`;
  caption.style.top = caption.style.bottom = "";
  caption.style.transform = "";
  const margin = s.margin * scale + "px";
  if (s.position === "bottom") caption.style.bottom = margin;
  else if (s.position === "top") caption.style.top = margin;
  else { caption.style.top = "50%"; caption.style.transform = "translateY(-50%)"; }

  for (const span of $$("span", caption)) styleCaptionSpan(span, scale);
}

function styleCaptionSpan(span, scale) {
  const s = state.style;
  if (s.box) {
    span.style.background = hexToRgba(s.box_color, s.box_opacity);
    span.style.padding = `${4 * scale}px ${10 * scale}px`;
    span.style.webkitTextStroke = "0";
  } else {
    span.style.background = "none";
    span.style.padding = "0";
    span.style.webkitTextStroke = s.outline > 0 ? `${s.outline * 2 * scale}px ${s.outline_color}` : "0";
  }
}

let shownText = null;
function renderCaption(seg) {
  const text = seg ? seg.text.trim() : "";
  if (text === shownText) return;
  shownText = text;
  const caption = $("#caption");
  caption.replaceChildren();
  if (!text) return;
  const span = el("span", {}, text);
  caption.append(span);
  styleCaptionSpan(span, $("#stage").clientHeight / 1080);
}

// Playback loop --------------------------------------------------------------

function findSegmentAt(t) {
  return state.segments.find((s) => t >= s.start && t < s.end) || null;
}

function tick() {
  if (state.project) {
    const t = video.currentTime;
    const dur = state.project.duration || video.duration || 0;
    const seg = findSegmentAt(t);
    renderCaption(seg);
    $("#time-display").textContent = `${fmtTime(t)} / ${fmtTime(dur)}`;
    $("#playhead").style.left = dur ? `${(t / dur) * 100}%` : "0";
    $("#play-btn").textContent = video.paused ? "▶" : "❚❚";
    setActiveSegment(seg ? seg.id : null);
  }
  requestAnimationFrame(tick);
}
requestAnimationFrame(tick);

function setActiveSegment(id) {
  if (id === state.activeId) return;
  state.activeId = id;
  for (const node of $$(".segment")) node.classList.toggle("active", node.dataset.id === id);
  for (const node of $$(".timeline-cue")) node.classList.toggle("active", node.dataset.id === id);
  if (id && !video.paused) {
    const node = $(`.segment[data-id="${id}"]`);
    const editing = document.activeElement && node?.contains(document.activeElement);
    if (node && !editing) node.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }
}

$("#play-btn").addEventListener("click", togglePlay);
function togglePlay() {
  if (!video.src) return;
  if (video.paused) video.play(); else video.pause();
}
video.addEventListener("click", togglePlay);

function seek(t) {
  const dur = state.project?.duration || video.duration || 0;
  video.currentTime = Math.min(Math.max(0, t), dur);
}

$("#timeline").addEventListener("click", (e) => {
  const rect = e.currentTarget.getBoundingClientRect();
  seek(((e.clientX - rect.left) / rect.width) * (state.project?.duration || 0));
});

document.addEventListener("keydown", (e) => {
  if (!state.project || $("#editor-view").hidden) return;
  const tag = document.activeElement?.tagName;
  if (["INPUT", "TEXTAREA", "SELECT"].includes(tag)) return;
  if (e.code === "Space") { e.preventDefault(); togglePlay(); }
  else if (e.code === "ArrowLeft") { e.preventDefault(); seek(video.currentTime - 2); }
  else if (e.code === "ArrowRight") { e.preventDefault(); seek(video.currentTime + 2); }
});

// Tabs -------------------------------------------------------------------------

function selectTab(name) {
  for (const t of $$(".tab")) t.classList.toggle("active", t.dataset.tab === name);
  for (const p of $$("[data-panel]")) p.hidden = p.dataset.panel !== name;
}
for (const t of $$(".tab")) t.addEventListener("click", () => selectTab(t.dataset.tab));
for (const b of $$("[data-goto-tab]")) b.addEventListener("click", () => selectTab(b.dataset.gotoTab));

// Segments ---------------------------------------------------------------------

function sortSegments() {
  state.segments.sort((a, b) => a.start - b.start || a.end - b.end);
}

function renderSegments() {
  const list = $("#segment-list");
  list.replaceChildren();
  $("#segment-empty").hidden = state.segments.length > 0;
  $("#segment-count").textContent = state.segments.length ? `${state.segments.length} субтитров` : "";
  state.segments.forEach((seg, i) => list.append(segmentNode(seg, i)));
  state.activeId = undefined; // force re-highlight on next tick
  renderTimeline();
}

function segmentNode(seg, index) {
  const next = state.segments[index + 1];
  const overlaps = next && next.start < seg.end;

  const timeInput = (field) =>
    el("input", {
      value: fmtTime(seg[field]),
      title: field === "start" ? "Начало" : "Конец",
      onchange: (e) => {
        const t = parseTime(e.target.value);
        if (Number.isNaN(t)) {
          toast("Неверный формат времени. Пример: 1:05.250", true);
          e.target.value = fmtTime(seg[field]);
          return;
        }
        seg[field] = t;
        if (seg.end <= seg.start) seg.end = seg.start + 0.5;
        sortSegments();
        renderSegments();
        scheduleSave();
      },
      onkeydown: (e) => { if (e.key === "Enter") e.target.blur(); },
    });

  const textarea = el("textarea", {
    rows: Math.max(2, seg.text.split("\n").length),
    oninput: (e) => {
      seg.text = e.target.value;
      shownText = null;
      scheduleSave();
    },
    onfocus: () => {
      if (video.paused && !(video.currentTime >= seg.start && video.currentTime < seg.end)) seek(seg.start);
    },
    onkeydown: (e) => {
      if (e.key === "Enter" && e.altKey) {
        e.preventDefault();
        splitSegment(seg, e.target.selectionStart);
      }
    },
  });
  textarea.value = seg.text;

  return el("div", {
    class: "segment" + (overlaps ? " invalid" : ""),
    "data-id": seg.id,
    title: overlaps ? "Пересекается со следующим субтитром" : null,
  },
    el("div", { class: "segment-head" },
      el("span", { class: "segment-num", title: "Перейти", onclick: () => seek(seg.start) }, `#${index + 1}`),
      timeInput("start"),
      el("button", { class: "seg-btn", title: "Начало = текущая позиция", onclick: () => setBound(seg, "start") }, "⇤"),
      el("span", { class: "arrow" }, "→"),
      timeInput("end"),
      el("button", { class: "seg-btn", title: "Конец = текущая позиция", onclick: () => setBound(seg, "end") }, "⇥"),
      el("div", { class: "segment-actions" },
        el("button", { class: "seg-btn", title: "Воспроизвести", onclick: () => { seek(seg.start); video.play(); } }, "▶"),
        el("button", { class: "seg-btn", title: "Разделить (Alt+Enter в тексте)", onclick: () => splitSegment(seg, null) }, "✂"),
        next ? el("button", { class: "seg-btn", title: "Объединить со следующим", onclick: () => mergeWithNext(seg) }, "⤓") : null,
        el("button", { class: "seg-btn danger", title: "Удалить", onclick: () => deleteSegment(seg) }, "✕"),
      ),
    ),
    textarea,
  );
}

function renderTimeline() {
  const container = $("#timeline-cues");
  container.replaceChildren();
  const dur = state.project?.duration;
  if (!dur) return;
  for (const seg of state.segments) {
    container.append(el("div", {
      class: "timeline-cue",
      "data-id": seg.id,
      title: seg.text,
      style: `left:${(seg.start / dur) * 100}%;width:${Math.max(((seg.end - seg.start) / dur) * 100, 0.15)}%`,
    }));
  }
}

function setBound(seg, field) {
  const t = Math.round(video.currentTime * 1000) / 1000;
  if (field === "start" && t >= seg.end) return toast("Начало должно быть раньше конца", true);
  if (field === "end" && t <= seg.start) return toast("Конец должен быть позже начала", true);
  seg[field] = t;
  sortSegments();
  renderSegments();
  scheduleSave();
}

function splitSegment(seg, cursor) {
  const text = seg.text;
  let splitTime;
  const t = video.currentTime;
  if (cursor == null) {
    // Split at the playhead if it is inside the cue, otherwise in the middle.
    splitTime = t > seg.start + 0.1 && t < seg.end - 0.1 ? t : (seg.start + seg.end) / 2;
    const ratio = (splitTime - seg.start) / (seg.end - seg.start);
    cursor = nearestSpace(text, Math.round(text.length * ratio));
  } else {
    const ratio = text.length ? cursor / text.length : 0.5;
    splitTime = seg.start + (seg.end - seg.start) * ratio;
  }
  splitTime = Math.min(Math.max(splitTime, seg.start + 0.05), seg.end - 0.05);
  const first = text.slice(0, cursor).trim();
  const second = text.slice(cursor).trim();
  const newSeg = { id: newId(), start: round3(splitTime), end: seg.end, text: second };
  seg.end = round3(splitTime);
  seg.text = first;
  state.segments.splice(state.segments.indexOf(seg) + 1, 0, newSeg);
  renderSegments();
  scheduleSave();
  $(`.segment[data-id="${newSeg.id}"] textarea`)?.focus();
}

function nearestSpace(text, pos) {
  let best = pos;
  let bestDist = Infinity;
  for (let i = 0; i < text.length; i++) {
    if (/\s/.test(text[i]) && Math.abs(i - pos) < bestDist) { best = i; bestDist = Math.abs(i - pos); }
  }
  return best;
}

function round3(x) { return Math.round(x * 1000) / 1000; }

function mergeWithNext(seg) {
  const i = state.segments.indexOf(seg);
  const next = state.segments[i + 1];
  if (!next) return;
  seg.text = [seg.text.trim(), next.text.trim()].filter(Boolean).join(" ");
  seg.end = Math.max(seg.end, next.end);
  state.segments.splice(i + 1, 1);
  renderSegments();
  scheduleSave();
}

function deleteSegment(seg) {
  state.segments.splice(state.segments.indexOf(seg), 1);
  shownText = null;
  renderSegments();
  scheduleSave();
}

$("#add-cue-btn").addEventListener("click", () => {
  if (!state.project) return;
  const t = round3(video.currentTime);
  if (findSegmentAt(t)) return toast("В этой позиции уже есть субтитр", true);
  const next = state.segments.find((s) => s.start > t);
  const end = round3(Math.min(t + 2, next ? next.start : Infinity, state.project.duration));
  if (end - t < 0.1) return toast("Недостаточно места для нового субтитра", true);
  const seg = { id: newId(), start: t, end, text: "" };
  state.segments.push(seg);
  sortSegments();
  renderSegments();
  selectTab("segments");
  scheduleSave();
  const node = $(`.segment[data-id="${seg.id}"]`);
  node?.scrollIntoView({ block: "center" });
  $("textarea", node)?.focus();
});

$("#shift-btn").addEventListener("click", () => {
  const answer = prompt("На сколько секунд сдвинуть все субтитры? (отрицательное значение — раньше)", "0.5");
  if (answer == null) return;
  const delta = parseFloat(answer.replace(",", "."));
  if (Number.isNaN(delta)) return toast("Нужно число секунд", true);
  for (const s of state.segments) {
    s.start = round3(Math.max(0, s.start + delta));
    s.end = round3(Math.max(s.start + 0.1, s.end + delta));
  }
  renderSegments();
  scheduleSave();
});

$("#import-input").addEventListener("change", async (e) => {
  const file = e.target.files[0];
  e.target.value = "";
  if (!file) return;
  if (state.segments.length && !confirm("Заменить текущие субтитры импортированными?")) return;
  const form = new FormData();
  form.append("file", file);
  try {
    await flushSave();
    const project = await api(`/api/projects/${state.project.id}/import`, { method: "POST", body: form });
    state.segments = project.segments;
    shownText = null;
    renderSegments();
    toast(`Импортировано субтитров: ${project.segments.length}`);
  } catch (err) {
    toast(err.message, true);
  }
});

// Saving ---------------------------------------------------------------------

function scheduleSave() {
  state.dirty = true;
  $("#save-status").textContent = "Есть несохранённые изменения";
  clearTimeout(state.saveTimer);
  state.saveTimer = setTimeout(flushSave, 800);
}

async function flushSave() {
  clearTimeout(state.saveTimer);
  if (state.savePromise) await state.savePromise;
  if (!state.dirty || !state.project) return;
  state.dirty = false;
  const id = state.project.id;
  const payload = state.segments.map(({ id, start, end, text }) => ({ id, start, end, text }));
  $("#save-status").textContent = "Сохранение…";
  state.savePromise = api(`/api/projects/${id}/segments`, { method: "PUT", json: { segments: payload }, keepalive: true })
    .then(() => {
      if (!state.dirty) $("#save-status").textContent = "Сохранено";
    })
    .catch((err) => {
      state.dirty = true;
      $("#save-status").textContent = "Ошибка сохранения";
      toast("Не удалось сохранить: " + err.message, true);
    })
    .finally(() => { state.savePromise = null; });
  await state.savePromise;
}

// Style ----------------------------------------------------------------------

const styleForm = $("#style-form");

function fillStyleForm() {
  for (const input of styleForm.elements) {
    if (!input.name || !(input.name in state.style)) continue;
    if (input.type === "checkbox") input.checked = state.style[input.name];
    else input.value = state.style[input.name];
  }
  updateStyleOutputs();
}

function updateStyleOutputs() {
  for (const out of $$("output", styleForm)) {
    const v = state.style[out.dataset.for];
    out.textContent = out.dataset.for === "box_opacity" ? Math.round(v * 100) + "%" : v;
  }
  for (const node of $$("[data-when]", styleForm)) {
    const cond = node.dataset.when;
    const value = cond.startsWith("!") ? !state.style[cond.slice(1)] : state.style[cond];
    node.hidden = !value;
  }
}

styleForm.addEventListener("input", (e) => {
  const input = e.target;
  if (!input.name) return;
  let value = input.type === "checkbox" ? input.checked : input.value;
  if (input.type === "range" || input.type === "number") value = parseFloat(value);
  state.style[input.name] = value;
  updateStyleOutputs();
  applyCaptionStyle();
  scheduleStyleSave();
});

$("#style-reset").addEventListener("click", () => {
  state.style = { ...state.config.default_style };
  fillStyleForm();
  applyCaptionStyle();
  scheduleStyleSave();
});

function scheduleStyleSave() {
  clearTimeout(state.styleTimer);
  state.styleTimer = setTimeout(flushStyle, 500);
}

async function flushStyle() {
  if (!state.styleTimer || !state.project) return;
  clearTimeout(state.styleTimer);
  state.styleTimer = null;
  try {
    await api(`/api/projects/${state.project.id}/style`, { method: "PUT", json: state.style });
  } catch (err) {
    toast("Не удалось сохранить стиль: " + err.message, true);
    throw err;
  }
}

// Jobs -------------------------------------------------------------------------

function hasActiveJobs(project) {
  return Object.values(project.jobs).some((j) => ["queued", "running"].includes(j.status));
}

function startPolling() {
  stopPolling();
  state.pollTimer = setInterval(poll, 1000);
}

function stopPolling() {
  clearInterval(state.pollTimer);
  state.pollTimer = null;
}

async function poll() {
  if (!state.project) return stopPolling();
  let project;
  try {
    project = await api(`/api/projects/${state.project.id}`);
  } catch {
    return; // transient error, retry on next tick
  }
  if (project.id !== state.project?.id) return;
  const previous = state.jobStatus;
  state.jobStatus = Object.fromEntries(Object.entries(project.jobs).map(([k, j]) => [k, j.status]));
  state.project.jobs = project.jobs;

  if (previous.transcribe !== "done" && project.jobs.transcribe?.status === "done") {
    state.segments = project.segments;
    state.dirty = false;
    shownText = null;
    renderSegments();
    selectTab("segments");
    toast(`Готово: ${project.segments.length} субтитров (язык: ${project.language})`);
  }
  if (previous.preview !== "done" && project.jobs.preview?.status === "done") {
    loadVideo();
  } else if (["queued", "running", "error"].includes(project.jobs.preview?.status)) {
    loadVideo();
  }
  renderJobs(project);
  if (!hasActiveJobs(project)) stopPolling();
}

function renderJobStatus(container, job, labels) {
  if (!job) { container.hidden = true; return; }
  container.hidden = false;
  container.className = "job-status";
  container.replaceChildren();
  if (job.status === "queued" || job.status === "running") {
    const pct = Math.round((job.progress || 0) * 100);
    container.append(
      el("div", {}, job.status === "queued" ? "В очереди…" : labels.running),
      el("div", { class: "progress" },
        el("div", { class: "progress-bar", style: `width:${pct}%` }),
        el("span", {}, `${pct}%`)),
    );
  } else if (job.status === "error") {
    container.classList.add("error");
    container.textContent = "Ошибка: " + job.error;
  } else if (job.status === "done") {
    container.classList.add("done");
    container.textContent = labels.done;
  }
}

function renderJobs(project) {
  const tr = project.jobs.transcribe;
  renderJobStatus($("#transcribe-status"), tr, {
    running: "Распознавание речи… (первый запуск модели включает её загрузку)",
    done: `Распознавание завершено${project.language ? ` (язык: ${project.language})` : ""}.`,
  });
  const trBusy = ["queued", "running"].includes(tr?.status);
  $("#transcribe-btn").disabled = trBusy;

  const rd = project.jobs.render;
  renderJobStatus($("#render-status"), rd, {
    running: "Рендеринг видео…",
    done: "Видео готово.",
  });
  const rdBusy = ["queued", "running"].includes(rd?.status);
  $("#render-btn").disabled = rdBusy;
  const download = $("#render-download");
  download.hidden = rd?.status !== "done";
  download.href = `/api/projects/${project.id}/render.mp4?t=${Math.round(rd?.finished || 0)}`;
}

$("#transcribe-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  if (state.segments.length && !confirm("Текущие субтитры будут заменены результатом распознавания. Продолжить?")) return;
  const form = new FormData(e.target);
  const body = {
    model: form.get("model"),
    language: form.get("language") || null,
    task: form.get("task"),
    max_chars: parseInt(form.get("max_chars"), 10),
    max_line: parseInt(form.get("max_line"), 10),
  };
  try {
    await flushSave();
    const project = await api(`/api/projects/${state.project.id}/transcribe`, { method: "POST", json: body });
    state.project.jobs = project.jobs;
    state.jobStatus.transcribe = project.jobs.transcribe.status;
    renderJobs(project);
    startPolling();
  } catch (err) {
    toast(err.message, true);
  }
});

$("#render-btn").addEventListener("click", async () => {
  try {
    await flushSave();
    await flushStyle();
    const project = await api(`/api/projects/${state.project.id}/render`, { method: "POST" });
    state.project.jobs = project.jobs;
    renderJobs(project);
    startPolling();
  } catch (err) {
    toast(err.message, true);
  }
});

// Export links: make sure pending edits are saved before downloading.
function updateExportLinks() {
  for (const fmt of ["srt", "vtt", "ass"]) {
    const link = $(`#dl-${fmt}`);
    link.href = `/api/projects/${state.project.id}/subtitles.${fmt}`;
  }
}
for (const fmt of ["srt", "vtt", "ass"]) {
  $(`#dl-${fmt}`).addEventListener("click", async (e) => {
    if (!state.dirty && !state.styleTimer) return;
    e.preventDefault();
    await flushSave();
    await flushStyle().catch(() => {});
    location.href = e.currentTarget.href;
  });
}

// ---------------------------------------------------------------------- boot

(async function init() {
  try {
    state.config = await api("/api/config");
  } catch (err) {
    toast("Сервер недоступен: " + err.message, true);
    return;
  }
  $("#model-select").replaceChildren(
    ...state.config.models.map((m) => el("option", { value: m, selected: m === state.config.default_model }, m)));
  $("#font-select").replaceChildren(...state.config.fonts.map((f) => el("option", { value: f }, f)));
  route();
})();
