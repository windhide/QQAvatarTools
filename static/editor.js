"use strict";

const $ = (id) => document.getElementById(id);
const dropzone = $("dropzone"), fileInput = $("file-input");
const editorBox = $("editor"), canvas = $("canvas"), preview = $("preview");
const zoomSlider = $("zoom-slider"), zoomLabel = $("zoom-label");
const srcInfo = $("src-info"), alphaBadge = $("alpha-badge"), cropInfo = $("crop-info");
const napcatUrl = $("napcat-url"), napcatToken = $("napcat-token");
const napcatStatus = $("napcat-status"), resultBox = $("result"), logBox = $("log");
const btnUpload = $("btn-upload");

const ctx = canvas.getContext("2d");
const pctx = preview.getContext("2d");
const CANVAS_SIZE = 460;          // 逻辑边长（正方形 = 裁剪框）
const DPR = window.devicePixelRatio || 1;
const ZOOM_RANGE = 8;             // 相对最小缩放的倍数范围

let img = null;                   // HTMLImageElement
let imageId = null;
let srcMeta = null;               // {width,height,has_alpha,format}
let view = { scale: 1, tx: 0, ty: 0 };
let minScale = 1;
const rot = { quarter: 0, fine: 0 };   // 总角度 = quarter*90 + fine（度，顺时针为正）
const flip = { h: false, v: false };

const rotSlider = $("rot-slider"), rotLabel = $("rot-label");
const btnFlipH = $("btn-flip-h"), btnFlipV = $("btn-flip-v");

function totalAngle() { return rot.quarter * 90 + rot.fine; }

// 旋转扩边后的工作图尺寸（与 Pillow expand=True 同式，±1px 由服务端钳制兜底）
function workDims() {
  const a = totalAngle() * Math.PI / 180;
  const c = Math.abs(Math.cos(a)), s = Math.abs(Math.sin(a));
  return {
    w: Math.max(1, Math.round(srcMeta.width * c + srcMeta.height * s)),
    h: Math.max(1, Math.round(srcMeta.width * s + srcMeta.height * c)),
  };
}

function log(msg) {
  const t = new Date().toLocaleTimeString();
  logBox.textContent += `[${t}] ${msg}\n`;
  logBox.scrollTop = logBox.scrollHeight;
}

function showResult(ok, text) {
  resultBox.classList.remove("hidden", "ok", "err");
  resultBox.classList.add(ok ? "ok" : "err");
  resultBox.textContent = text;
}

// ---------- 视图 ----------

function clampView() {
  const wd = workDims();
  // 缩放范围 1/8 ~ 8 倍（相对铺满），缩小后允许画布出现留白（裁剪为透明）
  view.scale = Math.min(Math.max(view.scale, minScale / ZOOM_RANGE), minScale * ZOOM_RANGE);
  const bw = CANVAS_SIZE - wd.w * view.scale;
  const bh = CANVAS_SIZE - wd.h * view.scale;
  view.tx = Math.min(Math.max(bw, 0), Math.max(Math.min(bw, 0), view.tx));
  view.ty = Math.min(Math.max(bh, 0), Math.max(Math.min(bh, 0), view.ty));
}

function zoomAt(px, py, factor) {
  const ns = Math.min(Math.max(view.scale * factor, minScale / ZOOM_RANGE),
    minScale * ZOOM_RANGE);
  const k = ns / view.scale;
  view.tx = px - (px - view.tx) * k;
  view.ty = py - (py - view.ty) * k;
  view.scale = ns;
  clampView();
  render();
}

function fitView() {
  rot.quarter = 0; rot.fine = 0;
  flip.h = false; flip.v = false;
  rotSlider.value = "0";
  btnFlipH.classList.remove("active");
  btnFlipV.classList.remove("active");
  minScale = Math.max(CANVAS_SIZE / srcMeta.width, CANVAS_SIZE / srcMeta.height);
  view.scale = minScale;
  view.tx = (CANVAS_SIZE - srcMeta.width * minScale) / 2;
  view.ty = (CANVAS_SIZE - srcMeta.height * minScale) / 2;
  clampView();
  render();
}

// 画布(0,0,W,W) 反变换到工作图（旋转扩边后）坐标；允许超出图像边界 → 透明填充
function cropRect() {
  const s = view.scale;
  return {
    x: Math.round(-view.tx / s),
    y: Math.round(-view.ty / s),
    size: Math.max(16, Math.round(CANVAS_SIZE / s)),
  };
}

function applyRotation(dQuarter, fine) {
  if (!img || !srcMeta) return;
  const wd0 = workDims();
  const cx = view.tx + wd0.w * view.scale / 2;   // 旋转围绕图像中心，保持中心不动
  const cy = view.ty + wd0.h * view.scale / 2;
  if (dQuarter) rot.quarter += dQuarter;
  if (fine !== undefined) rot.fine = fine;
  const wd = workDims();
  minScale = Math.max(CANVAS_SIZE / wd.w, CANVAS_SIZE / wd.h);
  view.tx = cx - wd.w * view.scale / 2;
  view.ty = cy - wd.h * view.scale / 2;
  clampView();
  render();
}

function render() {
  if (!img) return;
  const wd = workDims();
  const s = view.scale;
  const rad = totalAngle() * Math.PI / 180;
  ctx.setTransform(DPR, 0, 0, DPR, 0, 0);
  ctx.clearRect(0, 0, CANVAS_SIZE, CANVAS_SIZE);
  ctx.imageSmoothingEnabled = true;
  ctx.imageSmoothingQuality = "high";
  const cx = view.tx + wd.w * s / 2, cy = view.ty + wd.h * s / 2;
  ctx.save();
  ctx.translate(cx, cy);
  ctx.rotate(rad);
  ctx.scale(flip.h ? -1 : 1, flip.v ? -1 : 1);
  ctx.drawImage(img, -srcMeta.width * s / 2, -srcMeta.height * s / 2,
    srcMeta.width * s, srcMeta.height * s);
  ctx.restore();

  // 圆形参考线（QQ 头像显示为圆形）
  ctx.beginPath();
  ctx.arc(CANVAS_SIZE / 2, CANVAS_SIZE / 2, CANVAS_SIZE / 2 - 6, 0, Math.PI * 2);
  ctx.strokeStyle = "rgba(255,255,255,.35)";
  ctx.setLineDash([6, 6]);
  ctx.lineWidth = 1.5;
  ctx.stroke();
  ctx.setLineDash([]);

  // 预览（与主画布同一变换：先翻转，再绕中心旋转）
  const c = cropRect();
  pctx.setTransform(1, 0, 0, 1, 0, 0);
  pctx.clearRect(0, 0, 128, 128);
  pctx.imageSmoothingQuality = "high";
  const k = 128 / c.size;
  pctx.translate(64, 64);
  pctx.rotate(rad);
  pctx.scale((flip.h ? -1 : 1) * k, (flip.v ? -1 : 1) * k);
  pctx.drawImage(img, -srcMeta.width / 2, -srcMeta.height / 2);

  // 信息
  const ratio = view.scale / minScale;
  zoomLabel.textContent = `${ratio >= 1 ? ratio.toFixed(2) : ratio.toFixed(3)}×`;
  zoomSlider.value = String(Math.round(Math.log(ratio) / Math.log(ZOOM_RANGE) * 100));
  rotLabel.textContent = `${totalAngle().toFixed(1)}°`;
  const pad = c.x < 0 || c.y < 0 || c.x + c.size > wd.w || c.y + c.size > wd.h;
  cropInfo.textContent = `裁剪输出：${c.size} × ${c.size} px` + (pad ? " · 含透明边" : "");
}

// ---------- 交互 ----------

let dragging = false, lastX = 0, lastY = 0;
canvas.addEventListener("pointerdown", (e) => {
  dragging = true; lastX = e.clientX; lastY = e.clientY;
  canvas.setPointerCapture(e.pointerId);
  canvas.classList.add("dragging");
});
canvas.addEventListener("pointermove", (e) => {
  if (!dragging) return;
  const rect = canvas.getBoundingClientRect();
  const css = CANVAS_SIZE / rect.width;   // CSS 可能被 max-width 缩小
  view.tx += (e.clientX - lastX) * css;
  view.ty += (e.clientY - lastY) * css;
  lastX = e.clientX; lastY = e.clientY;
  clampView(); render();
});
canvas.addEventListener("pointerup", () => { dragging = false; canvas.classList.remove("dragging"); });
canvas.addEventListener("wheel", (e) => {
  e.preventDefault();
  const rect = canvas.getBoundingClientRect();
  const px = (e.clientX - rect.left) * (CANVAS_SIZE / rect.width);
  const py = (e.clientY - rect.top) * (CANVAS_SIZE / rect.height);
  zoomAt(px, py, e.deltaY < 0 ? 1.15 : 1 / 1.15);
}, { passive: false });

zoomSlider.addEventListener("input", () => {
  const target = minScale * Math.pow(ZOOM_RANGE, zoomSlider.value / 100);
  const cx = CANVAS_SIZE / 2, cy = CANVAS_SIZE / 2;
  const k = target / view.scale;
  view.tx = cx - (cx - view.tx) * k;
  view.ty = cy - (cy - view.ty) * k;
  view.scale = target;
  clampView(); render();
});
$("btn-zoom-in").onclick = () => zoomAt(CANVAS_SIZE / 2, CANVAS_SIZE / 2, 1.25);
$("btn-zoom-out").onclick = () => zoomAt(CANVAS_SIZE / 2, CANVAS_SIZE / 2, 0.8);
$("btn-rot-l").onclick = () => applyRotation(-1);
$("btn-rot-r").onclick = () => applyRotation(1);
rotSlider.addEventListener("input", () => applyRotation(0, parseFloat(rotSlider.value)));
rotSlider.addEventListener("dblclick", () => { rotSlider.value = "0"; applyRotation(0, 0); });
btnFlipH.onclick = () => { flip.h = !flip.h; btnFlipH.classList.toggle("active", flip.h); render(); };
btnFlipV.onclick = () => { flip.v = !flip.v; btnFlipV.classList.toggle("active", flip.v); render(); };
$("btn-reset").onclick = fitView;
$("btn-replace").onclick = () => fileInput.click();
canvas.addEventListener("dblclick", fitView);

// ---------- 文件载入 ----------

function loadFile(file) {
  if (!file) return;
  const name = file.name.toLowerCase();
  if (!/\.(png|jpe?g|webp|bmp)$/.test(name)) {
    log(`不支持的文件：${file.name}`);
    return;
  }
  file.arrayBuffer().then((buf) =>
    fetch("/api/image", {
      method: "POST",
      headers: { "Content-Type": "application/octet-stream" },
      body: buf,
    }).then((r) => r.json())
  ).then((res) => {
    if (!res.ok) { log(`导入失败：${res.error}`); showResult(false, res.error); return; }
    imageId = res.image_id;
    srcMeta = { width: res.width, height: res.height, has_alpha: res.has_alpha, format: res.format };
    const url = URL.createObjectURL(file);
    const im = new Image();
    im.onload = () => {
      img = im;
      minScale = Math.max(CANVAS_SIZE / srcMeta.width, CANVAS_SIZE / srcMeta.height);
      fitView();
      dropzone.classList.add("hidden");
      editorBox.classList.remove("hidden");
      btnUpload.disabled = false;
      srcInfo.textContent =
        `源图：${srcMeta.width} × ${srcMeta.height} px · ${srcMeta.format}` +
        (srcMeta.has_alpha ? " · 含透明通道" : "");
      alphaBadge.classList.toggle("hidden", !srcMeta.has_alpha);
      log(`已导入 ${file.name}（${srcMeta.width}×${srcMeta.height}${srcMeta.has_alpha ? "，保留透明" : ""}）`);
    };
    im.src = url;
  }).catch((e) => log(`导入出错：${e}`));
}

dropzone.addEventListener("click", () => fileInput.click());
fileInput.addEventListener("change", () => { loadFile(fileInput.files[0]); fileInput.value = ""; });
["dragover", "dragenter"].forEach((ev) =>
  dropzone.addEventListener(ev, (e) => { e.preventDefault(); dropzone.classList.add("dragover"); }));
["dragleave", "drop"].forEach((ev) =>
  dropzone.addEventListener(ev, (e) => { e.preventDefault(); dropzone.classList.remove("dragover"); }));
dropzone.addEventListener("drop", (e) => loadFile(e.dataTransfer.files[0]));
window.addEventListener("dragover", (e) => e.preventDefault());
window.addEventListener("drop", (e) => e.preventDefault());

// ---------- 内置 NapCat 登录 ----------

const builtinStatus = $("builtin-status"), qrArea = $("qr-area"), qrImg = $("qr-img");
const quickList = $("quick-list"), btnStart = $("btn-builtin-start");
const btnStop = $("btn-builtin-stop"), btnElevate = $("btn-elevate");
let builtinLoggedIn = false;
let serverGone = false;   // 提权重启期间页面重连用

function setBuiltin(cls, html) {
  builtinStatus.className = "status " + cls;
  builtinStatus.innerHTML = html;
}

async function pollBuiltin() {
  let st;
  try {
    st = await (await fetch("/api/builtin/status")).json();
    if (serverGone) {
      serverGone = false;
      log("工具已重启（管理员模式），继续…");
      if (localStorage.getItem("ntav_autostart") === "1") {
        localStorage.removeItem("ntav_autostart");
        startBuiltin();
      }
    }
  } catch (e) {
    if (!serverGone) { serverGone = true; setBuiltin("err", "● 服务重启中，等待恢复…"); }
    return;
  }
  const s = st.ok ? st : {};
  btnElevate.classList.toggle("hidden", !!s.admin);
  qrArea.classList.add("hidden");
  quickList.innerHTML = "";

  if (s.logged_in) {
    builtinLoggedIn = true;
    const lg = s.login || {};
    setBuiltin("ok", `● 已登录：${lg.nickname || "QQ"}（${lg.user_id}）`);
    btnStart.disabled = true; btnStart.textContent = "已登录";
    btnStop.disabled = false;
    return;
  }
  builtinLoggedIn = false;
  btnStart.disabled = false; btnStart.textContent = "启动并登录";
  btnStop.disabled = !s.boot_alive;

  if (!s.qq_exe) {
    setBuiltin("err", "● 未检测到新版 QQ（NTQQ）。请先安装 QQ 桌面版。");
    return;
  }
  if (!s.boot_alive) {
    setBuiltin("", s.admin
      ? "● 未启动 — 点击「启动并登录」（建议先退出桌面 QQ）"
      : "● 未启动 — 注入 QQ 需要管理员权限，请点击下方按钮提权后重试");
    return;
  }
  if (!s.webui_up) {
    setBuiltin("", "● QQ 正在后台启动…（首次约需 10–30 秒）");
    return;
  }
  // 已启动待登录：显示二维码与快速登录
  setBuiltin("", "● 等待登录 — 扫码或选择快速登录");
  if (s.qr_png) {
    qrImg.src = "data:image/png;base64," + s.qr_png;
    qrArea.classList.remove("hidden");
  }
  const items = Array.isArray(s.quick_list) ? s.quick_list : [];
  for (const it of items.slice(0, 5)) {
    const uin = String(it.uin ?? it.uin ?? it.qq ?? "");
    if (!uin) continue;
    const name = it.nick || it.nickname || it.name || "";
    const b = document.createElement("button");
    b.textContent = `快速登录：${name ? name + " " : ""}(${uin})`;
    b.onclick = () => {
      fetch("/api/builtin/quicklogin", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ uin }),
      }).then((r) => r.json()).then((res) => {
        if (!res.ok) log(`快速登录失败：${res.error}`);
      });
    };
    quickList.appendChild(b);
  }
}

async function startBuiltin() {
  btnStart.disabled = true; btnStart.textContent = "启动中…";
  setBuiltin("", "● 正在启动内置 QQ…");
  try {
    // 不带任何 uin：每次打开都从扫码开始，不沿用上次登录
    const res = await (await fetch("/api/builtin/start", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: "{}",
    })).json();
    if (!res.ok) {
      setBuiltin("err", "● 启动失败：" + res.error);
      log("启动失败：" + res.error);
      const lg = await (await fetch("/api/builtin/log")).json();
      if (lg.log) log("NapCat 日志尾部：\n" + lg.log.split("\n").slice(-8).join("\n"));
      btnStart.disabled = false; btnStart.textContent = "启动并登录";
    } else {
      log(`内置 NapCat 已启动（PID ${res.pid}），等待 QQ 登录…`);
    }
  } catch (e) {
    setBuiltin("err", "● 启动出错：" + e);
    btnStart.disabled = false; btnStart.textContent = "启动并登录";
  }
}

btnStart.onclick = startBuiltin;
$("btn-qr-refresh").onclick = async (e) => {
  e.preventDefault();
  await fetch("/api/builtin/qrrefresh", { method: "POST" });
  log("已请求刷新登录二维码");
};
btnStop.onclick = async () => {
  if (!confirm("停止将结束所有 QQ 进程（包括手动打开的桌面 QQ）。继续？")) return;
  await fetch("/api/builtin/stop", { method: "POST" });
  log("已停止内置 QQ（所有 QQ 进程已结束）");
};
btnElevate.onclick = async () => {
  if (!confirm("将以管理员身份重启本工具（浏览器页面会短暂断开，恢复后自动继续）。继续？")) return;
  localStorage.setItem("ntav_autostart", "1");
  await fetch("/api/builtin/elevate", { method: "POST" });
  serverGone = true;
};

setInterval(pollBuiltin, 2000);
pollBuiltin();

// ---------- NapCat 配置 ----------

function saveConfig() {
  return fetch("/api/config", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ napcat_url: napcatUrl.value.trim(), token: napcatToken.value.trim() }),
  }).then((r) => r.json());
}

function setStatus(cls, text) {
  napcatStatus.className = "status " + cls;
  napcatStatus.textContent = text;
}

async function testConnection() {
  await saveConfig();
  setStatus("", "测试中…");
  try {
    const res = await (await fetch("/api/napcat/status")).json();
    if (res.ok && res.login) {
      setStatus("ok", `已连接 · ${res.login.nickname}（${res.login.user_id}）`);
      log(`NapCat 连接正常：${res.login.nickname}（${res.login.user_id}）`);
    } else {
      setStatus("err", `连接失败：${res.error}`);
      log(`NapCat 测试失败：${res.error}`);
    }
  } catch (e) {
    setStatus("err", `连接失败：${e}`);
  }
}

$("btn-save-config").onclick = async () => {
  await saveConfig();
  setStatus("", "已保存（未测试）");
  log("NapCat 设置已保存");
};
$("btn-test").onclick = testConnection;

// ---------- 上传 ----------

btnUpload.onclick = async () => {
  if (!img || !imageId) return;
  const c = cropRect();
  const angle = +totalAngle().toFixed(1);
  btnUpload.disabled = true;
  btnUpload.textContent = "上传中…";
  const extras = [
    angle ? `旋转 ${angle}°` : "",
    flip.h ? "水平翻转" : "",
    flip.v ? "垂直翻转" : "",
  ].filter(Boolean).join("，");
  log(`开始上传：源图裁剪 ${c.size}×${c.size} px @ (${c.x},${c.y})` +
    (extras ? ` · ${extras}` : ""));
  try {
    const res = await (await fetch("/api/avatar", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        image_id: imageId, x: c.x, y: c.y, size: c.size,
        angle, flip_h: flip.h, flip_v: flip.v,
      }),
    })).json();
    if (res.ok) {
      const s = res.sent;
      showResult(true,
        `上传成功 ✓（${res.mode === "builtin" ? "内置通道" : "外置通道"}）\n` +
        `无损 PNG ${s.width}×${s.height}（${(s.bytes / 1024).toFixed(0)} KiB）` +
        (res.login && res.login.nickname ? `\n账号：${res.login.nickname}（${res.login.user_id}）` : "") +
        `\n如未立即生效，重启 QQ 或等待片刻后刷新。`);
      log("NapCat 返回成功");
    } else {
      showResult(false, `上传失败：${res.error || res.detail}\n${res.hint || ""}`);
      log(`上传失败：${res.error || res.detail}`);
    }
  } catch (e) {
    showResult(false, `请求出错：${e}`);
  } finally {
    btnUpload.disabled = false;
    btnUpload.textContent = "上传到 QQ 头像";
  }
};

// ---------- 初始化 ----------

canvas.width = CANVAS_SIZE * DPR;
canvas.height = CANVAS_SIZE * DPR;
canvas.style.width = CANVAS_SIZE + "px";
canvas.style.height = CANVAS_SIZE + "px";

fetch("/api/config").then((r) => r.json()).then((cfg) => {
  napcatUrl.value = cfg.napcat_url || "";
  napcatToken.value = cfg.token || "";
});
log("就绪。点击右侧「启动并登录」用本机 QQ 登录（零安装），然后拖入图片即可上传。");
