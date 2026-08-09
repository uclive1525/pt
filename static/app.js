const TOKEN_KEY = "mt_pt_token";
let token = localStorage.getItem(TOKEN_KEY) || "";
const titles = {
  dash: "首页概览", site: "站点配置", human: "拟人防封", tr: "Transmission",
  tasks: "监控任务", hobby: "爱好监控", ratio: "分享监控",
  access: "访问日志", ptlog: "PT日志", download: "下载日志", inklog: "墨水屏日志", sys: "系统设置",
};
const pageGroup = {
  dash: "overview", site: "site", human: "site", tr: "site",
  tasks: "task", hobby: "task", ratio: "task",
  access: "log", ptlog: "log", download: "log", inklog: "log", sys: "system",
};
const tabPageMap = { dash: "dash", tr: "tr", tasks: "tasks", ratio: "ratio" };
const pageTabMap = {
  dash: "dash",
  tr: "tr",
  tasks: "tasks", hobby: "tasks",
  ratio: "ratio",
};

function detectDevice() {
  const ua = navigator.userAgent || "";
  const phone = /Android|iPhone|iPod|Mobile|OpenHarmony|HarmonyOS|webOS|BlackBerry|IEMobile|Opera Mini/i.test(ua);
  const narrow = Math.min(window.innerWidth || 9999, screen.width || 9999) <= 900;
  return phone || narrow ? "mobile" : "pc";
}

function applyDeviceMode() {
  const mode = detectDevice();
  document.documentElement.dataset.device = mode;
  if (mode !== "mobile") closeNav();
  return mode;
}

function openNav() {
  if (document.documentElement.dataset.device !== "mobile") return;
  document.body.classList.add("nav-open");
  const mask = $("navMask");
  if (mask) mask.hidden = false;
}

function closeNav() {
  document.body.classList.remove("nav-open");
  const mask = $("navMask");
  if (mask) mask.hidden = true;
}

function syncMobileTab(name) {
  const key = pageTabMap[name] || "";
  document.querySelectorAll(".m-tab").forEach((t) => {
    const on = key && t.dataset.mtab === key;
    t.classList.toggle("active", on);
  });
}

function $(id) { return document.getElementById(id); }
function val(id) { return $(id).value; }
function set(id, v) { const el = $(id); if (el) el.value = v ?? ""; }
function boolSel(id, on) { const el = $(id); if (el) el.value = on ? "1" : "0"; }
function isOn(id) { const el = $(id); return el ? el.value === "1" : false; }

function errText(data, fallback) {
  const d = data && data.detail;
  if (typeof d === "string") return d;
  if (Array.isArray(d)) return d.map((x) => x.msg || JSON.stringify(x)).join("; ");
  if (d && typeof d === "object") return d.msg || JSON.stringify(d);
  return (data && data.message) || fallback || "请求失败";
}

async function api(path, opts = {}) {
  const headers = { "Content-Type": "application/json", ...(opts.headers || {}) };
  if (token) headers.Authorization = `Bearer ${token}`;
  const r = await fetch(path, { ...opts, headers });
  const data = await r.json().catch(() => ({}));
  if (r.status === 401 && path !== "/api/auth/login") {
    logout(true);
    throw new Error("请重新登录");
  }
  if (!r.ok) throw new Error(errText(data, r.statusText));
  return data;
}

function showApp(user) {
  const login = $("loginView");
  const app = $("appView");
  login.hidden = true;
  login.style.display = "none";
  app.hidden = false;
  app.style.display = "flex";
  $("topUser").textContent = user || "admin";
}

function showLogin() {
  const login = $("loginView");
  const app = $("appView");
  app.hidden = true;
  app.style.display = "none";
  login.hidden = false;
  login.style.display = "flex";
}

function logout(silent) {
  const t = token;
  token = "";
  localStorage.removeItem(TOKEN_KEY);
  if (!silent && t) {
    fetch("/api/auth/logout", {
      method: "POST",
      headers: { Authorization: `Bearer ${t}` },
    }).catch(() => {});
  }
  showLogin();
}

async function doSysLogin(e) {
  e.preventDefault();
  $("loginErr").classList.remove("show");
  try {
    const d = await api("/api/auth/login", {
      method: "POST",
      body: JSON.stringify({ username: val("sysUser").trim(), password: val("sysPass") }),
    });
    token = d.token;
    localStorage.setItem(TOKEN_KEY, token);
    showApp(d.username);
    try {
      await boot();
    } catch (bootErr) {
      console.error(bootErr);
    }
  } catch (err) {
    showLogin();
    $("loginErr").textContent = err.message || "登录失败";
    $("loginErr").classList.add("show");
  }
}

function goPage(name) {
  document.querySelectorAll(".page").forEach((p) => p.classList.remove("active"));
  document.querySelectorAll(".nav-item").forEach((n) => n.classList.remove("active"));
  document.querySelectorAll(".nav-sub").forEach((n) => n.classList.remove("has-active"));
  const page = $(`page-${name}`);
  if (!page) return;
  page.classList.add("active");
  const item = document.querySelector(`.nav-item[data-page="${name}"]`);
  if (item) item.classList.add("active");
  const g = pageGroup[name];
  if (g) {
    const sub = document.querySelector(`.nav-sub[data-group="${g}"]`);
    if (sub) {
      sub.classList.add("open", "has-active");
    }
  }
  $("pageTitle").textContent = titles[name] || name;
  syncMobileTab(name);
  closeNav();
  if (name === "hobby") loadWishes().catch(() => {});
  if (name === "ratio") loadRatio();
  if (name === "tasks") loadTasks();
  if (name === "tr") { fillTrSelects(); renderTrServers(); loadTrOverview().catch(() => {}); }
  if (name === "access") refreshLogs("access", logPageState.access || 1);
  if (name === "ptlog") refreshLogs("pt", logPageState.pt || 1);
  if (name === "download") refreshLogs("download", logPageState.download || 1);
  if (name === "inklog") refreshLogs("ink", logPageState.ink || 1);
  if (name === "dash") {
    loadDash();
    loadPersonal().catch(() => {});
  }
  if (name === "sys") {
    updateInkLink();
    loadAppVersion();
  }
}

function updateInkLink() {
  const url = `${location.origin}/generate-image`;
  if ($("inkApiUrl")) $("inkApiUrl").value = url;
  if ($("btnPreviewInk")) $("btnPreviewInk").href = `${url}?istest=1`;
}

async function loadAppVersion() {
  const el = $("appVersion");
  if (!el) return;
  try {
    const d = await api("/api/version");
    el.textContent = d.version || "-";
  } catch {
    el.textContent = "-";
  }
}

function splitKw(s) {
  return (s || "").split(/[,，\n]/).map((x) => x.trim()).filter(Boolean);
}

async function loadConfig() {
  const c = await api("/api/config");
  set("apiKey", "");
  $("apiKeyStatus").textContent = c.api_key_set
    ? `· 已配置 ${c.api_key_fp || ""}`
    : "· 未配置";
  $("apiKey").placeholder = c.api_key_set
    ? `已保存 ${c.api_key_fp || ""}，重新粘贴可更换`
    : "在此粘贴完整令牌";
  set("apiBase", c.api_base);
  set("webBase", c.web_base);
  set("proxy", c.proxy);
  set("mode", c.mode);
  set("pageSize", c.page_size);
  set("clientVersion", c.client_version || "1.1.4");
  set("webVersion", c.web_version || "1140");
  set("intervalMin", c.interval_min);
  set("intervalMax", c.interval_max);
  set("actDelayMin", c.action_delay_min);
  set("actDelayMax", c.action_delay_max);
  set("pageDelayMin", c.page_delay_min);
  set("pageDelayMax", c.page_delay_max);
  set("maxPerHour", c.max_actions_per_hour);
  set("quietStart", c.quiet_start);
  set("quietEnd", c.quiet_end);
  boolSel("humanMode", c.human_mode);
  boolSel("uaRotate", c.ua_rotate);
  set("keywords", (c.keywords || []).join(","));
  set("excludeKw", (c.exclude_keywords || []).join(","));
  set("kwMatch", c.keyword_match || "any");
  boolSel("autoDl", c.auto_download);
  set("hobbyMaxVer", c.hobby_max_versions ?? 3);
  boolSel("ratioAssist", c.ratio_assist);
  set("ratioPages", c.ratio_pages ?? 3);
  set("ratioMinGb", c.ratio_min_size_gb ?? 5);
  set("ratioMaxGb", c.ratio_max_size_gb ?? 80);
  set("ratioMinSeed", c.ratio_min_seeders ?? 1);
  set("ratioMaxSeed", c.ratio_max_seeders ?? 8);
  set("ratioMinLeech", c.ratio_min_leechers ?? 0);
  set("ratioTopN", c.ratio_top_n);
  boolSel("ratioPreferFree", c.ratio_prefer_free);
  boolSel("ratioAutoDl", c.ratio_auto_download);
  boolSel("ratioScheduleEnabled", c.ratio_schedule_enabled);
  set("ratioScheduleStart", c.ratio_schedule_start || "14:00");
  set("ratioScheduleEnd", c.ratio_schedule_end || "18:00");
  setRatioWeekdays(c.ratio_schedule_weekdays);
  updateRatioScheduleStatus(c);
  window.__trServers = c.tr_servers || [];
  window.__trDefaultId = c.tr_default_id || "";
  window.__trAutoServerId = c.tr_auto_server_id || "";
  window.__trRatioServerId = c.tr_ratio_server_id || c.tr_auto_server_id || "";
  boolSel("trAutoHobby", c.tr_auto_hobby !== false);
  boolSel("trAutoRatio", c.tr_auto_ratio !== false);
  boolSel("ratioTrPush", c.tr_auto_ratio !== false);
  boolSel("trAutoManual", c.tr_auto_manual !== false);
  boolSel("trManageEnabled", c.tr_manage_enabled);
  set("trManageInterval", c.tr_manage_interval_min ?? 60);
  boolSel("trManageDeleteData", c.tr_manage_delete_data !== false);
  boolSel("trManageOnlyFinished", c.tr_manage_only_finished !== false);
  boolSel("trManageRuleRatio", c.tr_manage_rule_ratio !== false);
  set("trManageMinRatio", c.tr_manage_min_ratio ?? 1);
  boolSel("trManageRuleSeedDays", c.tr_manage_rule_seed_days !== false);
  set("trManageSeedDays", c.tr_manage_seed_days ?? 3);
  boolSel("trManageRuleIdleDays", c.tr_manage_rule_idle_days);
  set("trManageIdleDays", c.tr_manage_idle_days ?? 7);
  boolSel("trManageRuleError", c.tr_manage_rule_error);
  boolSel("trManageRuleMaxSeed", c.tr_manage_rule_max_seed);
  set("trManageMaxSeed", c.tr_manage_max_seed ?? 100);
  updateTrManageStatus(c);
  boolSel("checkinEnabled", c.checkin_enabled);
  set("checkinStart", c.checkin_start || "09:00");
  set("checkinEnd", c.checkin_end || "12:00");
  set("checkinMinAct", c.checkin_min_actions ?? 2);
  set("checkinMaxAct", c.checkin_max_actions ?? 5);
  updateCheckinStatus(c);
  boolSel("wishEnabled", c.wish_enabled);
  set("wishTitle", c.wish_title || "想看清单");
  set("wishIntro", c.wish_intro || "留下片名或关键词，我们会参考收录到监控列表。");
  updateWishLink(c.wish_token, c.wish_enabled);
  set("inkCity", c.ink_city || "四川省成都市郫都区");
  if ($("inkWt")) $("inkWt").value = ["1005", "1010", "0", "1"].includes(String(c.ink_wt)) ? String(c.ink_wt) : "0";
  renderTrServers();
  fillTrSelects();
  return c;
}

function updateCheckinStatus(c) {
  const el = $("checkinStatus");
  if (!el) return;
  if (!c.checkin_enabled) {
    el.textContent = "已关闭";
    return;
  }
  const last = c.checkin_last_at || "从未";
  const next = c.checkin_next_at || "待调度";
  el.textContent = `上次 ${last} · 下次 ${next} · 时段 ${c.checkin_start || "09:00"}-${c.checkin_end || "12:00"}`;
}

function updateRatioScheduleStatus(c) {
  const el = $("ratioScheduleStatus");
  if (!el) return;
  if (!c.ratio_schedule_enabled) {
    el.textContent = "已关闭（开启后由爱好扫描顺带刷新）";
    return;
  }
  const names = ["一", "二", "三", "四", "五", "六", "日"];
  const days = (c.ratio_schedule_weekdays || [0, 1, 2, 3, 4, 5, 6]).map((d) => names[d]).join("");
  const last = c.ratio_schedule_last_at || "从未";
  const next = c.ratio_schedule_next_at || "待调度";
  el.textContent = `星期${days || "无"} · 时段 ${c.ratio_schedule_start || "14:00"}-${c.ratio_schedule_end || "18:00"} · 上次 ${last} · 下次 ${next}`;
}

function setRatioWeekdays(days) {
  const box = $("ratioWeekdays");
  if (!box) return;
  const set = new Set((days && days.length ? days : [0, 1, 2, 3, 4, 5, 6]).map(Number));
  box.querySelectorAll("input[type=checkbox]").forEach((el) => {
    el.checked = set.has(Number(el.value));
  });
}

function getRatioWeekdays() {
  const box = $("ratioWeekdays");
  if (!box) return [0, 1, 2, 3, 4, 5, 6];
  const days = [...box.querySelectorAll("input[type=checkbox]:checked")].map((el) => Number(el.value));
  return days.length ? days : [0, 1, 2, 3, 4, 5, 6];
}

function fillTrSelects(onlyEnabled = false) {
  const all = window.__trServers || [];
  const servers = onlyEnabled
    ? all.filter((s) => s.enabled !== false && (s.url || "").trim())
    : all;
  const opts = servers.map((s) => `<option value="${esc(s.id)}">${esc(s.name || s.id)}${s.enabled === false ? "（停用）" : ""}</option>`).join("");
  ["trAutoServer", "trDefaultServer", "trRatioServer"].forEach((id) => {
    const el = $(id);
    if (!el) return;
    el.innerHTML = (all.length ? all.map((s) => `<option value="${esc(s.id)}">${esc(s.name || s.id)}${s.enabled === false ? "（停用）" : ""}</option>`).join("") : "") || `<option value="">未配置</option>`;
  });
  if ($("trPickerSelect")) {
    $("trPickerSelect").innerHTML = opts || `<option value="">未配置</option>`;
  }
  if ($("trAutoServer")) $("trAutoServer").value = window.__trAutoServerId || (all[0] && all[0].id) || "";
  if ($("trDefaultServer")) $("trDefaultServer").value = window.__trDefaultId || (all[0] && all[0].id) || "";
  if ($("trRatioServer")) $("trRatioServer").value = window.__trRatioServerId || window.__trAutoServerId || (all[0] && all[0].id) || "";
  renderTrServerTabs();
}

function getTrViewServerId() {
  return window.__trViewServerId || "";
}

function setTrViewServerId(id) {
  window.__trViewServerId = id || "";
  renderTrServerTabs();
}

function renderTrServerTabs() {
  const box = $("trServerTabs");
  if (!box) return;
  const enabled = (window.__trServers || []).filter((s) => s.enabled !== false && (s.url || "").trim());
  const cur = getTrViewServerId();
  const tabs = [{ id: "", name: `全部汇总${enabled.length > 1 ? ` (${enabled.length})` : ""}` }]
    .concat(enabled.map((s) => ({ id: s.id, name: s.name || s.id })));
  box.innerHTML = tabs.map((t) => {
    const on = (t.id || "") === (cur || "");
    return `<button type="button" class="tr-tab${on ? " active" : ""}" data-tr-view="${esc(t.id)}">${esc(t.name)}</button>`;
  }).join("");
  if ($("trViewScope")) {
    if (!enabled.length) $("trViewScope").textContent = "未配置服务";
    else if (!cur) $("trViewScope").textContent = enabled.length > 1 ? "多服务汇总" : (enabled[0].name || "");
    else {
      const s = enabled.find((x) => x.id === cur);
      $("trViewScope").textContent = s ? s.name : "指定服务";
    }
  }
  document.body.classList.toggle("tr-multi-view", !cur && enabled.length > 1);
  document.body.classList.toggle("tr-single-view", !!cur);
}

function renderTrStats(stats) {
  const s = stats || {};
  if ($("trStatTotal")) $("trStatTotal").textContent = s.total ?? 0;
  if ($("trStatDown")) $("trStatDown").textContent = s.downloading ?? 0;
  if ($("trStatSeed")) $("trStatSeed").textContent = s.seeding ?? 0;
  if ($("trStatPaused")) $("trStatPaused").textContent = s.paused ?? 0;
  if ($("trStatRateDown")) $("trStatRateDown").textContent = s.rate_down_text || "0";
  if ($("trStatRateUp")) $("trStatRateUp").textContent = s.rate_up_text || "0";
  if ($("trStatSize")) $("trStatSize").textContent = s.size_text || "-";
  if ($("trStatDownloaded")) $("trStatDownloaded").textContent = s.downloaded_text || "-";
  if ($("trStatUploaded")) $("trStatUploaded").textContent = s.uploaded_text || "-";
  if ($("trStatRatioVal")) $("trStatRatioVal").textContent = s.ratio != null ? Number(s.ratio).toFixed(2) : "-";
  if ($("trStatRatio")) $("trStatRatio").textContent = `累计 ↓${s.downloaded_text || "-"} · ↑${s.uploaded_text || "-"}`;
  if ($("trStatFree")) {
    const free = s.free_text || "-";
    $("trStatFree").textContent = s.total_text ? `${free} / ${s.total_text}` : free;
  }
}

function renderTrServerStats(servers) {
  const box = $("trServerStatPanel");
  if (!box) return;
  const rows = servers || [];
  const multi = !getTrViewServerId() && rows.length > 1;
  if (!multi) {
    box.innerHTML = "";
    box.hidden = true;
    return;
  }
  box.hidden = false;
  box.innerHTML = `<div class="tr-server-stat">${rows.map((s) => {
    if (!s.ok) {
      return `<button type="button" class="item bad" data-tr-view="${esc(s.id)}">
        <b>${esc(s.name)}</b>
        <span class="muted" style="color:#CF1322">${esc(s.error || "连接失败")}</span>
        <span class="go">查看 ›</span>
      </button>`;
    }
    const st = s.stats || {};
    const sess = (s.session && s.session.cumulative) || {};
    const freeHint = s.total_text
      ? `剩余 ${esc(s.free_text || "-")} / ${esc(s.total_text)}`
      : `剩余 ${esc(s.free_text || "-")}`;
    return `<button type="button" class="item" data-tr-view="${esc(s.id)}">
      <b>${esc(s.name)}</b>
      <div class="muted">任务 ${st.total ?? 0} · 下 ${st.downloading ?? 0} · 种 ${st.seeding ?? 0}</div>
      <div class="muted">↓${esc(st.rate_down_text || "0")} · ↑${esc(st.rate_up_text || "0")}</div>
      <div class="muted">${freeHint}</div>
      <div class="muted">累计 ↓${esc(sess.downloaded_text || "-")} ↑${esc(sess.uploaded_text || "-")}</div>
      <span class="go">查看 ›</span>
    </button>`;
  }).join("")}</div>`;
}

function updateTrManageStatus(c) {
  const el = $("trManageStatus");
  if (!el) return;
  if (!c.tr_manage_enabled) {
    el.textContent = "未启用";
    return;
  }
  const last = c.tr_manage_last_at || "从未";
  const next = c.tr_manage_next_at || "待调度";
  const res = c.tr_manage_last_result || "-";
  el.textContent = `上次 ${last} · 下次 ${next} · ${res}`;
}

function renderTrTorrents(items) {
  const body = $("trTorrentBody");
  if (!body) return;
  const filter = ($("trStatusFilter") && val("trStatusFilter")) || "all";
  const sid = getTrViewServerId();
  const showServer = !sid;
  document.body.classList.toggle("tr-single-view", !!sid);
  let rows = items || [];
  if (filter === "downloading") rows = rows.filter((x) => x.status === 4);
  else if (filter === "seeding") rows = rows.filter((x) => x.status === 6);
  else if (filter === "paused") rows = rows.filter((x) => x.status === 0);
  else if (filter === "error") rows = rows.filter((x) => x.error);
  else if (filter === "done") rows = rows.filter((x) => x.finished);
  if ($("trListHint")) {
    $("trListHint").textContent = showServer
      ? `共 ${rows.length} 条（多服务）`
      : `共 ${rows.length} 条`;
  }
  const cols = showServer ? 10 : 9;
  if (!rows.length) {
    body.innerHTML = `<tr><td colspan="${cols}" class="muted">暂无任务</td></tr>`;
    return;
  }
  body.innerHTML = rows.map((t) => {
    const pct = Math.max(0, Math.min(100, Number(t.percent) || 0));
    const cls = t.error ? "err" : (t.finished ? "done" : "");
    const st = t.error
      ? `<span class="badge badge-danger">异常</span>`
      : `<span class="badge ${t.status === 4 ? "badge-info" : t.status === 6 ? "badge-ok" : "badge-warn"}">${esc(t.status_text || "-")}</span>`;
    const serverTd = showServer
      ? `<td class="tr-col-server"><button type="button" class="btn-link" data-tr-view="${esc(t.server_id || "")}">${esc(t.server_name || "-")}</button></td>`
      : "";
    const sidAttr = esc(t.server_id || "");
    const tid = esc(t.id);
    const paused = Number(t.status) === 0;
    const iconPause = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="6" y="5" width="4" height="14" rx="1"/><rect x="14" y="5" width="4" height="14" rx="1"/></svg>`;
    const iconPlay = `<svg viewBox="0 0 24 24" fill="currentColor"><path d="M8 5v14l11-7z"/></svg>`;
    const iconRm = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M4 7h16M9 7V5a1 1 0 011-1h4a1 1 0 011 1v2m-9 0l1 12a2 2 0 002 2h6a2 2 0 002-2l1-12M10 11v6m4-6v6"/></svg>`;
    const iconRmData = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M4 7h16M10 11v6m4-6v6M9 7V5a1 1 0 011-1h4a1 1 0 011 1v2m-9 0l1 12a2 2 0 002 2h6a2 2 0 002-2l1-12"/><path d="M3 3l18 18"/></svg>`;
    const acts = `<td class="tr-ops">
      <div class="task-actions tr-actions">
        <button type="button" class="act-btn" data-tr-act="${paused ? "start" : "stop"}" data-sid="${sidAttr}" data-tid="${tid}" title="${paused ? "继续" : "暂停"}">${paused ? iconPlay : iconPause}<span>${paused ? "继续" : "暂停"}</span></button>
        <button type="button" class="act-btn danger" data-tr-act="remove" data-sid="${sidAttr}" data-tid="${tid}" title="删任务">${iconRm}<span>删任务</span></button>
        <button type="button" class="act-btn danger" data-tr-act="remove_data" data-sid="${sidAttr}" data-tid="${tid}" title="删文件">${iconRmData}<span>删文件</span></button>
      </div>
    </td>`;
    return `<tr title="${esc(t.error_string || t.name || "")}">
      <td class="col-title">${esc(t.name)}</td>
      ${serverTd}
      <td class="td-status">${st}</td>
      <td class="td-progress"><span class="tr-progress ${cls}"><span class="tr-progress-bar"><i style="width:${pct}%"></i></span>${pct}%</span></td>
      <td class="td-num">${esc(t.size_text || "-")}</td>
      <td class="td-num">${esc(t.rate_down_text || "0")}</td>
      <td class="td-num">${esc(t.rate_up_text || "0")}</td>
      <td class="td-num">${t.ratio ?? 0}</td>
      <td class="td-num">${t.peers ?? 0}</td>
      ${acts}
    </tr>`;
  }).join("");
}

async function trTorrentAction(serverId, torrentId, action) {
  await api("/api/transmission/action", {
    method: "POST",
    body: JSON.stringify({
      server_id: String(serverId || ""),
      torrent_ids: [Number(torrentId)],
      action,
    }),
  });
  await loadTrOverview();
}

async function saveTrManage() {
  await savePartial({
    tr_manage_enabled: isOn("trManageEnabled"),
    tr_manage_interval_min: Number(val("trManageInterval") || 60),
    tr_manage_delete_data: isOn("trManageDeleteData"),
    tr_manage_only_finished: isOn("trManageOnlyFinished"),
    tr_manage_rule_ratio: isOn("trManageRuleRatio"),
    tr_manage_min_ratio: Number(val("trManageMinRatio") || 1),
    tr_manage_rule_seed_days: isOn("trManageRuleSeedDays"),
    tr_manage_seed_days: Number(val("trManageSeedDays") || 3),
    tr_manage_rule_idle_days: isOn("trManageRuleIdleDays"),
    tr_manage_idle_days: Number(val("trManageIdleDays") || 7),
    tr_manage_rule_error: isOn("trManageRuleError"),
    tr_manage_rule_max_seed: isOn("trManageRuleMaxSeed"),
    tr_manage_max_seed: Number(val("trManageMaxSeed") || 100),
  });
  await loadConfig();
  if ($("trManageHint")) $("trManageHint").textContent = "已保存";
}

async function runTrManage(dry) {
  const d = await api("/api/transmission/manage/run", {
    method: "POST",
    body: JSON.stringify({ dry_run: !!dry }),
  });
  const n = d.count || 0;
  const msg = dry
    ? `预演命中 ${n} 个`
    : `已清理 ${n} 个${(d.errors || []).length ? `，错误 ${(d.errors || []).length}` : ""}`;
  if ($("trManageHint")) $("trManageHint").textContent = msg;
  if (n && d.removed && d.removed.length) {
    const lines = d.removed.slice(0, 8).map((x) => `${x.server_name || ""} ${x.name || x.id} (${(x.reasons || []).join("/")})`);
    alert(`${msg}\n${lines.join("\n")}${d.removed.length > 8 ? "\n…" : ""}`);
  } else {
    alert(msg);
  }
  await loadConfig();
  await loadTrOverview().catch(() => {});
}

async function loadTrOverview() {
  const sid = getTrViewServerId();
  if ($("trViewHint")) $("trViewHint").textContent = "加载中…";
  renderTrServerTabs();
  try {
    const d = await api(`/api/transmission/torrents${sid ? `?server_id=${encodeURIComponent(sid)}` : ""}`);
    window.__trTorrentItems = d.items || [];
    window.__trOverviewServers = d.servers || [];
    renderTrStats(d.stats || {});
    renderTrServerStats(d.servers || []);
    renderTrTorrents(window.__trTorrentItems);
    const errN = (d.errors || []).length;
    const okN = (d.servers || []).filter((x) => x.ok).length;
    if ($("trViewHint")) {
      $("trViewHint").textContent = sid
        ? `已更新 ${(d.items || []).length} 条`
        : `已汇总 ${okN} 服务 · ${(d.items || []).length} 条${errN ? ` · ${errN} 失败` : ""}`;
    }
  } catch (e) {
    if ($("trViewHint")) $("trViewHint").textContent = e.message || "加载失败";
    throw e;
  }
}

async function ensureTrServers() {
  try {
    const d = await api("/api/transmission/servers");
    window.__trServers = d.items || d.servers || [];
    window.__trDefaultId = d.default_id || window.__trDefaultId || "";
    window.__trAutoServerId = d.auto_server_id || window.__trAutoServerId || "";
    window.__trRatioServerId = d.ratio_server_id || window.__trRatioServerId || window.__trAutoServerId || "";
  } catch (_) {
    if (!window.__trServers) window.__trServers = [];
  }
  return window.__trServers;
}

async function pickTrServer() {
  await ensureTrServers();
  const servers = (window.__trServers || []).filter((s) => s.enabled !== false && (s.url || "").trim());
  if (!servers.length) throw new Error("请先在 Transmission 页配置并启用服务");
  if (servers.length === 1) return servers[0].id;
  fillTrSelects(true);
  const def = window.__trDefaultId && servers.some((s) => s.id === window.__trDefaultId)
    ? window.__trDefaultId
    : servers[0].id;
  $("trPickerSelect").value = def;
  $("trPicker").hidden = false;
  return new Promise((resolve, reject) => {
    const ok = () => {
      const id = $("trPickerSelect").value;
      cleanup();
      if (!id) reject(new Error("请选择 Transmission 服务"));
      else resolve(id);
    };
    const cancel = () => {
      cleanup();
      reject(new Error("已取消"));
    };
    const cleanup = () => {
      $("trPicker").hidden = true;
      $("trPickerOk").onclick = null;
      $("trPickerCancel").onclick = null;
    };
    $("trPickerOk").onclick = ok;
    $("trPickerCancel").onclick = cancel;
  });
}

async function downloadToTr(torrentId, name) {
  const serverId = await pickTrServer();
  return api("/api/download/tr", {
    method: "POST",
    body: JSON.stringify({ torrent_id: String(torrentId), name: name || "", server_id: serverId || "" }),
  });
}

function renderTrServers() {
  const box = $("trServerList");
  if (!box) return;
  const servers = window.__trServers || [];
  if (!servers.length) {
    box.innerHTML = `<div class="empty muted">暂无服务，点击右上角添加</div>`;
    return;
  }
  box.innerHTML = servers.map((s) => `
    <div class="tr-card">
      <div>
        <h4>${esc(s.name)} ${s.enabled ? '<span class="badge badge-ok">启用</span>' : '<span class="badge badge-warn">停用</span>'}</h4>
        <div class="meta">${esc(s.url || "-")}${s.user ? " · " + esc(s.user) : ""}${s.download_dir ? " · " + esc(s.download_dir) : ""}</div>
      </div>
      <div class="actions">
        <button class="btn-link" data-tr-edit="${esc(s.id)}">编辑</button>
        <button class="btn-link" data-tr-test="${esc(s.id)}">测试</button>
        <button class="btn-link" data-tr-del="${esc(s.id)}">删除</button>
      </div>
    </div>`).join("");
}

function openTrEditor(server) {
  $("trEditorTitle").textContent = server && server.id ? "编辑服务" : "添加服务";
  set("trEditId", (server && server.id) || "");
  set("trEditName", (server && server.name) || "");
  boolSel("trEditEnabled", !server || server.enabled !== false);
  set("trEditUrl", (server && server.url) || "http://host.docker.internal:9091");
  set("trEditUser", (server && server.user) || "");
  set("trEditPass", "");
  $("trEditPass").placeholder = server && server.pass_set ? "已保存，留空不改" : "可选";
  set("trEditDir", (server && server.download_dir) || "");
  boolSel("trEditPaused", server && server.paused);
  $("trEditHint").textContent = "";
  $("trEditor").hidden = false;
}

function closeTrEditor() {
  $("trEditor").hidden = true;
}

async function persistTrServers(servers, extra = {}) {
  await savePartial({
    tr_servers: servers,
    tr_default_id: extra.tr_default_id != null ? extra.tr_default_id : (val("trDefaultServer") || window.__trDefaultId || ""),
    tr_auto_server_id: extra.tr_auto_server_id != null ? extra.tr_auto_server_id : (val("trAutoServer") || window.__trAutoServerId || ""),
    tr_ratio_server_id: extra.tr_ratio_server_id != null ? extra.tr_ratio_server_id : (val("trRatioServer") || window.__trRatioServerId || ""),
    tr_auto_hobby: isOn("trAutoHobby"),
    tr_auto_ratio: isOn("trAutoRatio"),
    tr_auto_manual: isOn("trAutoManual"),
  });
  await loadConfig();
}

async function saveTr() {
  await persistTrServers(window.__trServers || []);
}

async function savePartial(body) {
  await api("/api/config", { method: "POST", body: JSON.stringify(body) });
}

async function saveSite() {
  const body = {
    api_base: val("apiBase"),
    web_base: val("webBase"),
    proxy: val("proxy"),
    mode: val("mode"),
    page_size: Number(val("pageSize")),
    client_version: val("clientVersion"),
    web_version: val("webVersion"),
  };
  const key = val("apiKey").trim();
  if (key) body.api_key = key;
  await savePartial(body);
  set("apiKey", "");
  await loadConfig();
}

async function saveCheckin() {
  let minA = Number(val("checkinMinAct") || 2);
  let maxA = Number(val("checkinMaxAct") || 5);
  if (maxA < minA) maxA = minA;
  await savePartial({
    checkin_enabled: isOn("checkinEnabled"),
    checkin_start: val("checkinStart").trim() || "09:00",
    checkin_end: val("checkinEnd").trim() || "12:00",
    checkin_min_actions: minA,
    checkin_max_actions: maxA,
  });
  await loadConfig();
}

async function saveHuman() {
  await savePartial({
    interval_min: Number(val("intervalMin")),
    interval_max: Number(val("intervalMax")),
    action_delay_min: Number(val("actDelayMin")),
    action_delay_max: Number(val("actDelayMax")),
    page_delay_min: Number(val("pageDelayMin")),
    page_delay_max: Number(val("pageDelayMax")),
    max_actions_per_hour: Number(val("maxPerHour")),
    quiet_start: val("quietStart"),
    quiet_end: val("quietEnd"),
    human_mode: isOn("humanMode"),
    ua_rotate: isOn("uaRotate"),
  });
}

async function saveHobby() {
  let maxV = Number(val("hobbyMaxVer") || 3);
  if (!Number.isFinite(maxV) || maxV < 1) maxV = 3;
  if (maxV > 10) maxV = 10;
  await savePartial({
    keywords: splitKw(val("keywords")),
    exclude_keywords: splitKw(val("excludeKw")),
    keyword_match: val("kwMatch"),
    auto_download: isOn("autoDl"),
    hobby_max_versions: maxV,
  });
  await api("/api/tasks/prune", { method: "POST" }).catch(() => {});
}

function updateWishLink(token, enabled) {
  const el = $("wishLink");
  if (!el) return;
  if (!token) {
    el.value = "";
    return;
  }
  el.value = `${location.origin}/wish/${token}${enabled ? "" : "（未启用）"}`;
}

function wishStatusLabel(st) {
  return ({ new: "新提交", adopted: "已采纳", ignored: "已忽略" })[st] || st || "新提交";
}

function wishCardHtml(w) {
  const st = w.status || "new";
  return `
    <article class="wish-item" data-wish-id="${esc(w.id)}">
      <div class="wish-top">
        <b>${esc(w.nickname || "匿名")}</b>
        <span class="wish-tag ${esc(st)}">${esc(wishStatusLabel(st))}</span>
        <span class="wish-meta" style="margin-left:auto">${esc(w.ts || "")}</span>
      </div>
      <div class="wish-kw">${esc(w.keywords || "-")}</div>
      ${w.note ? `<div class="wish-note">${esc(w.note)}</div>` : ""}
      <div class="wish-meta">IP ${esc(w.ip || "-")}</div>
      <div class="wish-acts">
        <button type="button" class="btn btn-primary" data-wish-adopt="${esc(w.id)}">采纳到关键词</button>
        <button type="button" class="btn" data-wish-ignore="${esc(w.id)}">忽略</button>
        <button type="button" class="btn" data-wish-del="${esc(w.id)}">删除</button>
      </div>
    </article>`;
}

async function loadWishes() {
  const info = await api("/api/wish/info");
  boolSel("wishEnabled", info.enabled);
  set("wishTitle", info.title || "想看清单");
  if (info.intro != null) set("wishIntro", info.intro);
  updateWishLink(info.token, info.enabled);
  if ($("wishStat")) {
    $("wishStat").textContent = `共 ${info.total || 0} 条 · 待处理 ${info.new_count || 0} 条`;
  }
  const d = await api("/api/wish/submissions");
  const rows = d.items || [];
  if (!$("wishBody")) return;
  if (!rows.length) {
    $("wishBody").innerHTML = `<div class="empty muted">暂无收集记录</div>`;
    return;
  }
  $("wishBody").innerHTML = rows.map(wishCardHtml).join("");
}

async function saveWishPage() {
  if (isOn("wishEnabled")) {
    const info = await api("/api/wish/info");
    if (!info.token) await api("/api/wish/token", { method: "POST" });
  }
  await savePartial({
    wish_enabled: isOn("wishEnabled"),
    wish_title: val("wishTitle").trim() || "想看清单",
    wish_intro: val("wishIntro").trim(),
  });
  await loadConfig();
  await loadWishes();
}

async function saveRatio() {
  await savePartial({
    ratio_assist: isOn("ratioAssist"),
    ratio_pages: Number(val("ratioPages")),
    ratio_min_size_gb: Number(val("ratioMinGb")),
    ratio_max_size_gb: Number(val("ratioMaxGb")),
    ratio_min_seeders: Number(val("ratioMinSeed")),
    ratio_max_seeders: Number(val("ratioMaxSeed")),
    ratio_min_leechers: Number(val("ratioMinLeech")),
    ratio_top_n: Number(val("ratioTopN")),
    ratio_prefer_free: isOn("ratioPreferFree"),
    ratio_auto_download: isOn("ratioAutoDl"),
    tr_auto_ratio: isOn("ratioTrPush"),
    tr_ratio_server_id: val("trRatioServer") || window.__trRatioServerId || "",
    ratio_schedule_enabled: isOn("ratioScheduleEnabled"),
    ratio_schedule_start: val("ratioScheduleStart").trim() || "14:00",
    ratio_schedule_end: val("ratioScheduleEnd").trim() || "18:00",
    ratio_schedule_weekdays: getRatioWeekdays(),
  });
  await loadConfig();
}

async function testSite() {
  const key = val("apiKey").trim();
  const body = { api_base: val("apiBase") };
  if (key) body.api_key = key;
  const d = await api("/api/site/test", { method: "POST", body: JSON.stringify(body) });
  set("apiKey", "");
  if (d.api_base) set("apiBase", d.api_base);
  await loadConfig();
  $("siteTestHint").textContent = `连接成功：${d.username || "-"} (${d.fingerprint || ""})`;
  return d;
}

function fmtNext(s) {
  if (!s) return "-";
  const m = String(s).match(/(\d{2}):(\d{2}):(\d{2})/);
  return m ? `${m[1]}:${m[2]}:${m[3]}` : String(s);
}

function applyRunState(running, nextRun) {
  const on = !!running;
  if ($("kpiRun")) $("kpiRun").textContent = on ? "运行中" : "已停止";
  if ($("kpiNext")) $("kpiNext").textContent = fmtNext(nextRun);
  if ($("dashHint")) {
    $("dashHint").textContent = on
      ? (nextRun ? `已启动 · 下次 ${fmtNext(nextRun)}` : "已启动")
      : "已停止";
  }
  const badge = $("runBadge");
  if (badge) {
    badge.textContent = on ? "运行中" : "已停止";
    badge.className = `badge ${on ? "badge-ok" : "badge-warn"}`;
  }
}

async function loadDash() {
  const d = await api("/api/dashboard");
  $("kpiKw").textContent = d.keywords;
  $("kpiAct").textContent = d.actions_last_hour;
  $("kpiHuman").textContent = d.human_mode ? "开启" : "关闭";
  $("kpiKey").textContent = d.api_key_set ? "已配置" : "未配置";
  $("kpiQuiet").textContent = d.quiet ? "是" : "否";
  $("dKw").textContent = d.keywords;
  if ($("dTasks")) $("dTasks").textContent = d.task_count || 0;
  $("dQuota").textContent = `${d.actions_last_hour}/${d.max_actions || 40}`;
  if ($("dRatio")) $("dRatio").textContent = (d.ratio_tips || []).length;
  applyRunState(d.running, d.next_run);
}

function drawLine(svgId, values, color) {
  const svg = $(svgId);
  if (!svg) return;
  const w = 320, h = 120, pad = 8;
  if (!values.length) {
    svg.innerHTML = "";
    return;
  }
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;
  const pts = values.map((v, i) => {
    const x = pad + (i / Math.max(values.length - 1, 1)) * (w - pad * 2);
    const y = h - pad - ((v - min) / span) * (h - pad * 2);
    return [x, y];
  });
  const line = pts.map(([x, y]) => `${x.toFixed(1)},${y.toFixed(1)}`).join(" ");
  const area = `${pad},${h - pad} ${line} ${w - pad},${h - pad}`;
  svg.innerHTML = `
    <defs><linearGradient id="g-${svgId}" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0%" stop-color="${color}" stop-opacity=".28"/>
      <stop offset="100%" stop-color="${color}" stop-opacity="0"/>
    </linearGradient></defs>
    <polygon fill="url(#g-${svgId})" points="${area}" />
    <polyline fill="none" stroke="${color}" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" points="${line}" />`;
}

function renderPersonal(d) {
  const s = d.stats || {};
  $("pUsername").textContent = s.username || "-";
  $("pUid").textContent = s.uid ? `UID ${s.uid}` : "";
  $("pSynced").textContent = s.ts ? `同步于 ${s.ts}` : "尚未同步，请刷新";
  $("pBonus").textContent = s.bonus != null ? Number(s.bonus).toFixed(1) : "-";
  $("pInvite").textContent = `${s.invites ?? 0}/${s.invite_limit ?? 0}`;
  $("pRatio").textContent = s.share_rate != null ? Number(s.share_rate).toFixed(2) : "-";
  $("pUp").textContent = s.uploaded_text || "-";
  $("pDown").textContent = s.downloaded_text || "-";
  $("pActive").textContent = `${s.seeding ?? 0} / ${s.leeching ?? 0}`;
  const sys = d.system || {};
  if ($("pSysGrid")) $("pSysGrid").className = "sys-grid";
  $("pSysGrid").innerHTML = [
    ["监控任务", sys.task_total],
    ["已下载", sys.task_downloaded],
    ["待处理", sys.task_pending],
    ["失败", sys.task_failed],
    ["近1小时操作", sys.actions_last_hour],
    ["访问日志", sys.access_logs],
    ["PT日志", sys.pt_logs],
    ["下载日志", sys.download_logs],
    ["墨水屏日志", sys.ink_logs],
  ].map(([k, v]) => `<div class="sys-item"><span>${k}</span><b>${v ?? 0}</b></div>`).join("");
  const hist = (d.history || []).slice(-60);
  drawLine("chartRatio", hist.map((x) => Number(x.share_rate) || 0), "#3B6FF5");
  const upGb = hist.map((x) => (Number(x.uploaded) || 0) / (1024 ** 3));
  const downGb = hist.map((x) => (Number(x.downloaded) || 0) / (1024 ** 3));
  const svg = $("chartTraffic");
  if (svg) {
    const w = 320, h = 120, pad = 8;
    const all = [...upGb, ...downGb];
    if (!all.length) svg.innerHTML = "";
    else {
      const min = Math.min(...all);
      const max = Math.max(...all);
      const span = max - min || 1;
      const ptsOf = (vals) => vals.map((v, i) => {
        const x = pad + (i / Math.max(vals.length - 1, 1)) * (w - pad * 2);
        const y = h - pad - ((v - min) / span) * (h - pad * 2);
        return [x, y];
      });
      const line = (vals, color, id) => {
        const pts = ptsOf(vals);
        const linePts = pts.map(([x, y]) => `${x.toFixed(1)},${y.toFixed(1)}`).join(" ");
        const area = `${pad},${h - pad} ${linePts} ${w - pad},${h - pad}`;
        return `
          <defs><linearGradient id="${id}" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stop-color="${color}" stop-opacity=".22"/>
            <stop offset="100%" stop-color="${color}" stop-opacity="0"/>
          </linearGradient></defs>
          <polygon fill="url(#${id})" points="${area}" />
          <polyline fill="none" stroke="${color}" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" points="${linePts}" />`;
      };
      svg.innerHTML = line(upGb, "#389e0d", "g-up") + line(downGb, "#E05A5A", "g-down");
    }
  }
  const rows = (d.history || []).slice().reverse().slice(0, 30);
  if (!rows.length) {
    $("pHistoryBody").innerHTML = `<tr><td colspan="6" class="muted">暂无历史，点击刷新获取首条快照</td></tr>`;
  } else {
    $("pHistoryBody").innerHTML = rows.map((r) => `
      <tr>
        <td class="mono">${esc(r.ts || "-")}</td>
        <td>${Number(r.share_rate || 0).toFixed(2)}</td>
        <td>${esc(r.uploaded_text || "-")}</td>
        <td>${esc(r.downloaded_text || "-")}</td>
        <td>${Number(r.bonus || 0).toFixed(1)}</td>
        <td>${r.seeding ?? 0} / ${r.leeching ?? 0}</td>
      </tr>`).join("");
  }
}

async function loadPersonal(refresh = false) {
  const d = refresh
    ? await api("/api/personal/refresh", { method: "POST" })
    : await api("/api/personal");
  renderPersonal(d);
  if (!refresh && !(d.stats && d.stats.username)) {
    const fresh = await api("/api/personal/refresh", { method: "POST" });
    renderPersonal(fresh);
  }
}

const ACTION_LABEL = {
  http: "接口访问",
  pt_login: "PT登录",
  profile_sync: "个人数据",
  checkin: "自动签到",
  wish_collect: "兴趣收集",
  scheduler: "调度",
  system: "系统",
  human_delay: "拟人等待",
  hobby_prune: "任务对齐",
  scan_skip: "跳过扫描",
  search: "搜索种子",
  gen_dl_token: "下载令牌",
  enrich: "补全详情",
  ratio_tips: "分享监控",
  scan: "扫描",
  torrent_save: "保存种子",
  tr_push: "推送TR",
  hobby_dl: "爱好下载",
  ratio_auto_dl: "分享下载",
  legacy: "历史",
  access: "访问",
  download: "下载",
  pt: "PT",
  ink_refresh: "墨水屏刷新",
  ink: "墨水屏",
  official_api: "官方请求",
  ota_upgrade: "OTA升级",
  ota_query: "OTA升级",
  device_logs: "设备上报",
  event: "事件",
};

const DETAIL_LABEL = {
  method: "方法",
  path: "路径",
  status: "状态码",
  ip: "IP",
  username: "用户",
  uid: "UID",
  share_rate: "分享率",
  uploaded: "上传",
  downloaded: "下载",
  seeding: "做种",
  leeching: "下载中",
  bonus: "魔力值",
  mode: "模式",
  keyword: "关键词",
  keywords: "关键词",
  page: "页码",
  page_size: "页大小",
  result_count: "结果数",
  sample: "样本",
  items: "条目",
  count: "数量",
  max_gb: "最大体积GB",
  min_seeders: "最少做种",
  torrent_id: "种子ID",
  torrent_name: "种子名",
  name: "名称",
  cn_name: "中文名",
  file: "文件",
  bytes: "字节",
  size_text: "体积",
  source: "来源",
  battery: "电量",
  battery_pct: "电量%",
  bv: "电压",
  devid: "设备号",
  model: "型号",
  fwv: "设备固件",
  fver: "OTA版本",
  fmd5: "OTA MD5",
  headers: "请求头",
  api: "接口",
  url: "URL",
  response: "响应",
  ok: "成功",
  hint: "提示",
  id_key: "ID参数",
  wt: "刷新间隔",
  ip: "IP",
  discount: "优惠",
  seeders: "做种数",
  douban_rating: "豆瓣",
  server_id: "服务ID",
  server_name: "TR服务",
  server_url: "RPC地址",
  duplicate: "重复",
  paused: "暂停添加",
  download_dir: "下载目录",
  error: "错误",
  errors: "错误列表",
  error_count: "错误数",
  updated: "已更新",
  matched: "匹配数",
  matched_ids: "匹配ID",
  downloaded_ids: "下载ID",
  pruned: "清理数",
  kept: "保留数",
  removed: "移除数",
  reason: "原因",
  event: "事件",
  next_run: "下次执行",
  interval_sec: "间隔秒",
  seconds: "等待秒",
  kind_delay: "延迟类型",
  api_base: "API地址",
  fingerprint: "指纹",
  score: "评分",
  tips: "提示",
};

function fmtDetailValue(v) {
  if (v === true) return "是";
  if (v === false) return "否";
  if (v == null) return "-";
  if (typeof v === "number") return String(v);
  if (typeof v === "string") return v;
  return null;
}

function listDetailHtml(arr) {
  if (!Array.isArray(arr) || !arr.length) return "";
  if (typeof arr[0] !== "object") {
    return `<div class="log-chips">${arr.slice(0, 20).map((x) => `<span class="log-chip">${esc(String(x))}</span>`).join("")}</div>`;
  }
  return `<div class="log-sublist">${arr.slice(0, 8).map((it) => {
    const title = it.cn_name || it.name || it.id || "-";
    const bits = [];
    if (it.id) bits.push(`#${it.id}`);
    if (it.size || it.size_text) bits.push(it.size || it.size_text);
    if (it.seeders != null) bits.push(`做种 ${it.seeders}`);
    if (it.douban_rating && it.douban_rating !== "0") bits.push(`豆瓣 ${it.douban_rating}`);
    if (it.score != null) bits.push(`分 ${it.score}`);
    if (it.tips) bits.push(it.tips);
    return `<div class="log-subitem"><div class="t">${esc(title)}</div><div class="s">${esc(bits.join(" · "))}</div></div>`;
  }).join("")}${arr.length > 8 ? `<div class="log-more">另有 ${arr.length - 8} 条…</div>` : ""}</div>`;
}

function detailHtml(detail, id) {
  if (!detail || typeof detail !== "object") return "";
  const skip = new Set();
  const entries = Object.entries(detail).filter(([k, v]) => {
    if (skip.has(k)) return false;
    if (v === "" || v == null) return false;
    if (Array.isArray(v) && !v.length) return false;
    return true;
  });
  if (!entries.length) return "";
  const simple = [];
  const complex = [];
  entries.forEach(([k, v]) => {
    if (Array.isArray(v) || (typeof v === "object" && v !== null)) complex.push([k, v]);
    else simple.push([k, v]);
  });
  const simpleHtml = simple.map(([k, v]) => {
    const label = DETAIL_LABEL[k] || k;
    return `<div class="kv"><span class="k">${esc(label)}</span><span class="v">${esc(fmtDetailValue(v) ?? String(v))}</span></div>`;
  }).join("");
  const complexHtml = complex.map(([k, v]) => {
    const label = DETAIL_LABEL[k] || k;
    if (Array.isArray(v)) {
      return `<div class="log-block"><div class="log-block-hd">${esc(label)}（${v.length}）</div>${listDetailHtml(v)}</div>`;
    }
    return `<div class="log-block"><div class="log-block-hd">${esc(label)}</div><pre class="log-json">${esc(JSON.stringify(v, null, 2))}</pre></div>`;
  }).join("");
  return `
    <details class="log-morebox" ${simple.length <= 4 && !complex.length ? "open" : ""}>
      <summary>详情 ${simple.length + complex.length} 项</summary>
      ${simpleHtml ? `<div class="log-detail">${simpleHtml}</div>` : ""}
      ${complexHtml}
    </details>`;
}

function renderLogFeed(elId, items, emptyText) {
  const el = $(elId);
  if (!el) return;
  if (!items || !items.length) {
    el.innerHTML = `<div class="log-empty">${esc(emptyText || "暂无日志")}</div>`;
    return;
  }
  el.innerHTML = items.map((row, i) => {
    const level = row.level || "info";
    const action = row.action || "event";
    const tone = level === "error" ? "err" : level === "warn" ? "warn"
      : action === "checkin" ? "checkin"
      : action === "wish_collect" ? "wish"
      : action === "official_api" ? "mute"
      : action === "ota_upgrade" || action === "ota_query" ? "wish"
      : action === "http" ? "mute" : "ok";
    const time = row.ts || "-";
    const hm = time.length >= 19 ? time.slice(11, 19) : time;
    const day = time.length >= 10 ? time.slice(0, 10) : "";
    const tagCls = action === "checkin" ? "log-tag checkin"
      : action === "wish_collect" || action === "ota_upgrade" || action === "ota_query" ? "log-tag wish"
      : action === "official_api" ? "log-tag mute"
      : "log-tag";
    return `
      <article class="log-item tone-${tone}">
        <div class="log-rail" aria-hidden="true"></div>
        <div class="log-body">
          <div class="log-top">
            <div class="log-time">
              <b>${esc(hm)}</b>
              <span>${esc(day)}</span>
            </div>
            <span class="${tagCls}">${esc(ACTION_LABEL[action] || action)}</span>
            ${level === "error" ? '<span class="log-tag err">失败</span>' : ""}
          </div>
          <div class="log-msg">${esc(row.message || "")}</div>
          ${detailHtml(row.detail, `${elId}-${i}`)}
        </div>
      </article>`;
  }).join("");
}

const logPageState = { access: 1, pt: 1, download: 1, ink: 1 };
const LOG_PAGE_SIZE = 30;

function renderPager(elId, kind, meta) {
  const el = $(elId);
  if (!el) return;
  const total = meta.total || 0;
  const page = meta.page || 1;
  const pages = meta.pages || 1;
  const size = meta.page_size || LOG_PAGE_SIZE;
  if (!total) {
    el.innerHTML = "";
    return;
  }
  const from = (page - 1) * size + 1;
  const to = Math.min(page * size, total);
  el.innerHTML = `
    <div class="pager-inner">
      <span class="pager-info">第 ${from}-${to} 条 / 共 ${total} 条</span>
      <div class="pager-btns">
        <button type="button" class="btn" data-log-page="${kind}" data-to="1" ${page <= 1 ? "disabled" : ""}>首页</button>
        <button type="button" class="btn" data-log-page="${kind}" data-to="${page - 1}" ${page <= 1 ? "disabled" : ""}>上一页</button>
        <span class="pager-cur">${page} / ${pages}</span>
        <button type="button" class="btn" data-log-page="${kind}" data-to="${page + 1}" ${page >= pages ? "disabled" : ""}>下一页</button>
        <button type="button" class="btn" data-log-page="${kind}" data-to="${pages}" ${page >= pages ? "disabled" : ""}>末页</button>
      </div>
    </div>`;
}

async function refreshLogs(kind, page) {
  const map = {
    access: ["access", "accessLogs", "accessPager", "暂无访问日志"],
    pt: ["pt", "ptLogs", "ptPager", "暂无 PT 日志"],
    download: ["download", "downloadLogs", "downloadPager", "暂无下载日志"],
    ink: ["ink", "inkLogs", "inkPager", "暂无墨水屏日志"],
  };
  const [apiKind, elId, pagerId, empty] = map[kind] || map.access;
  const p = Math.max(1, Number(page || logPageState[apiKind] || 1));
  logPageState[apiKind] = p;
  const d = await api(`/api/logs?kind=${apiKind}&page=${p}&page_size=${LOG_PAGE_SIZE}`);
  renderLogFeed(elId, d.items || [], empty);
  renderPager(pagerId, apiKind, d);
}

async function refreshAccessLogs() { return refreshLogs("access", 1); }
async function refreshDownloadLogs() { return refreshLogs("download", 1); }
async function refreshPtLogs() { return refreshLogs("pt", 1); }
async function refreshInkLogs() { return refreshLogs("ink", 1); }

function actionBtns(opts) {
  const { id, name, dl = true, tr = true, rm = false, dlAttr = "data-dl" } = opts;
  const n = esc(name || "");
  const i = esc(id);
  const iconDl = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 3v12m0 0l-4-4m4 4l4-4"/><path d="M4 17v2a2 2 0 002 2h12a2 2 0 002-2v-2"/></svg>`;
  const iconTr = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M4 17l6-6 4 4 6-8"/><path d="M4 21h16"/></svg>`;
  const iconRm = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M4 7h16M9 7V5a1 1 0 011-1h4a1 1 0 011 1v2m-9 0l1 12a2 2 0 002 2h6a2 2 0 002-2l1-12M10 11v6m4-6v6"/></svg>`;
  return `<div class="task-actions">
    ${dl ? `<button type="button" class="act-btn primary" ${dlAttr}="${i}" data-name="${n}" title="下载种子">${iconDl}<span>下载</span></button>` : ""}
    ${tr ? `<button type="button" class="act-btn tr" data-tr="${i}" data-name="${n}" title="推送到 Transmission">${iconTr}<span>下载至TR</span></button>` : ""}
    ${rm ? `<button type="button" class="act-btn danger" data-rm="${i}" title="删除任务">${iconRm}<span>删除</span></button>` : ""}
  </div>`;
}

function ratioCardHtml(r) {
  const title = r.cn_name || r.small_descr || r.name || "-";
  const cover = r.cover
    ? `<img class="task-cover" src="${esc(r.cover)}" alt="" loading="lazy" referrerpolicy="no-referrer" onerror="this.classList.add('broken')" />`
    : `<div class="task-cover placeholder"></div>`;
  const labels = (r.labels || []).slice(0, 4).map((x) => `<span class="tag">${esc(x)}</span>`).join("");
  const db = r.douban_rating && r.douban_rating !== "0"
    ? (r.douban
      ? `<a class="score douban" href="${esc(r.douban)}" target="_blank" rel="noreferrer">豆瓣 ${esc(r.douban_rating)}</a>`
      : `<span class="score douban">豆瓣 ${esc(r.douban_rating)}</span>`)
    : "";
  const imdb = r.imdb_rating && r.imdb_rating !== "0"
    ? (r.imdb
      ? `<a class="score imdb" href="${esc(r.imdb)}" target="_blank" rel="noreferrer">IMDb ${esc(r.imdb_rating)}</a>`
      : `<span class="score imdb">IMDb ${esc(r.imdb_rating)}</span>`)
    : "";
  const disc = r.discount ? `<span class="tag free">${esc(r.discount)}</span>` : "";
  const tip = r.tips ? `<span class="tag">${esc(r.tips)}</span>` : "";
  const score = r.score != null ? `<span class="badge badge-info">魔力 ${r.score}</span>` : "";
  const weeks = r.weeks != null ? `<span class="badge badge-ok">周龄 ${r.weeks}</span>` : (r.demand != null ? `<span class="badge badge-ok">供需 ${r.demand}</span>` : "");
  return `
    <article class="task-card">
      ${cover}
      <div class="task-main">
        <div class="task-title-row">
          <h3 class="task-cn" title="${esc(title)}">${esc(title)}</h3>
        </div>
        <div class="task-en" title="${esc(r.name)}">${esc(r.name || "")}</div>
        <div class="task-meta">
          ${db}${imdb}${disc}${tip}${labels}
        </div>
        <div class="task-stats">
          <span>${esc(r.size_text || "-")}</span>
          <span>完成 ${r.downloads ?? "-"}</span>
          <span>做种 ${r.seeders ?? "-"}</span>
          <span>下载 ${r.leechers ?? "-"}</span>
          <span>${esc(r.created_date || "")}</span>
        </div>
      </div>
      <div class="task-side">
        <div class="task-metrics">${score}${weeks}</div>
        ${actionBtns({ id: r.id, name: r.name, dl: true, tr: true, rm: false, dlAttr: "data-dl" })}
      </div>
    </article>`;
}

async function loadRatio() {
  const d = await api("/api/ratio/tips");
  const rows = d.items || [];
  if (!rows.length) {
    $("ratioBody").innerHTML = `<div class="empty muted">暂无推荐，点击刷新</div>`;
    return;
  }
  $("ratioBody").innerHTML = rows.map(ratioCardHtml).join("");
}

function esc(s) {
  return String(s || "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

function statusBadge(st) {
  const map = {
    downloaded: ["badge-ok", "已下载"],
    matched: ["badge-info", "已匹配"],
    pending: ["badge-warn", "待下载"],
    failed: ["badge-danger", "失败"],
  };
  const [cls, text] = map[st] || ["badge-info", st || "-"];
  return `<span class="badge ${cls}">${text}</span>`;
}

async function loadTasks() {
  const d = await api("/api/tasks?source=hobby");
  const filter = ($("taskStatusFilter") && val("taskStatusFilter")) || "all";
  let rows = d.items || [];
  if (filter !== "all") rows = rows.filter((x) => x.status === filter);
  if ($("taskCountHint")) $("taskCountHint").textContent = `共 ${rows.length} 条`;
  if (!$("taskBody")) return;
  if (!rows.length) {
    $("taskBody").innerHTML = `<div class="empty muted">暂无监控任务，请先配置爱好关键词并扫描</div>`;
    return;
  }
  $("taskBody").innerHTML = rows.map((r) => {
    const title = r.cn_name || r.small_descr || r.name || "-";
    const cover = r.cover
      ? `<img class="task-cover" src="${esc(r.cover)}" alt="" loading="lazy" referrerpolicy="no-referrer" onerror="this.classList.add('broken')" />`
      : `<div class="task-cover placeholder"></div>`;
    const labels = (r.labels || []).slice(0, 4).map((x) => `<span class="tag">${esc(x)}</span>`).join("");
    const db = r.douban_rating && r.douban_rating !== "0"
      ? (r.douban
        ? `<a class="score douban" href="${esc(r.douban)}" target="_blank" rel="noreferrer">豆瓣 ${esc(r.douban_rating)}</a>`
        : `<span class="score douban">豆瓣 ${esc(r.douban_rating)}</span>`)
      : "";
    const imdb = r.imdb_rating && r.imdb_rating !== "0"
      ? (r.imdb
        ? `<a class="score imdb" href="${esc(r.imdb)}" target="_blank" rel="noreferrer">IMDb ${esc(r.imdb_rating)}</a>`
        : `<span class="score imdb">IMDb ${esc(r.imdb_rating)}</span>`)
      : "";
    const disc = r.discount ? `<span class="tag free">${esc(r.discount)}</span>` : "";
    return `
    <article class="task-card">
      ${cover}
      <div class="task-main">
        <div class="task-title-row">
          <h3 class="task-cn" title="${esc(title)}">${esc(title)}</h3>
        </div>
        <div class="task-en" title="${esc(r.name)}">${esc(r.name || "")}</div>
        <div class="task-meta">
          ${db}${imdb}${disc}${labels}
        </div>
        <div class="task-stats">
          <span>${esc(r.size_text || "-")}</span>
          <span>做种 ${r.seeders ?? "-"}</span>
          <span>下载 ${r.leechers ?? "-"}</span>
          <span>完成 ${r.downloads ?? "-"}</span>
          <span>关键词 ${esc(r.keyword || "-")}</span>
          <span class="mono">${esc(r.updated_at || r.created_at || "-")}</span>
        </div>
      </div>
      <div class="task-side">
        ${statusBadge(r.status)}
        ${actionBtns({ id: r.id, name: r.name, dl: true, tr: true, rm: true, dlAttr: "data-redl" })}
      </div>
    </article>`;
  }).join("");
}

async function downloadTorrentFile(torrentId, name) {
  const headers = { "Content-Type": "application/json" };
  if (token) headers.Authorization = `Bearer ${token}`;
  const r = await fetch("/api/download", {
    method: "POST",
    headers,
    body: JSON.stringify({ torrent_id: String(torrentId), name: name || "" }),
  });
  if (r.status === 401) {
    logout(true);
    throw new Error("请重新登录");
  }
  const ctype = r.headers.get("content-type") || "";
  if (!r.ok || ctype.includes("application/json")) {
    const data = await r.json().catch(() => ({}));
    throw new Error(errText(data, r.statusText));
  }
  const blob = await r.blob();
  let filename = `${torrentId}.torrent`;
  const cd = r.headers.get("Content-Disposition") || "";
  const m = /filename\*=UTF-8''([^;]+)|filename=\"?([^\";]+)\"?/i.exec(cd);
  if (m) filename = decodeURIComponent((m[1] || m[2] || filename).trim());
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(a.href);
}

async function refreshRatio() {
  await saveRatio().catch(() => {});
  const d = await api("/api/ratio/tips", { method: "POST" });
  const rows = d.items || [];
  if (!rows.length) {
    $("ratioBody").innerHTML = `<div class="empty muted">暂无推荐</div>`;
    return;
  }
  $("ratioBody").innerHTML = rows.map(ratioCardHtml).join("");
}

async function boot() {
  await loadConfig();
  await loadDash();
  await loadPersonal().catch(() => {});
}

$("loginForm").addEventListener("submit", doSysLogin);
$("btnLogout").onclick = () => { closeNav(); logout(false); };
if ($("btnMenu")) $("btnMenu").onclick = () => openNav();
if ($("btnAsideClose")) $("btnAsideClose").onclick = () => closeNav();
if ($("navMask")) $("navMask").onclick = () => closeNav();
document.querySelectorAll(".m-tab").forEach((btn) => {
  btn.onclick = () => {
    const key = btn.dataset.mtab;
    if (key === "more") {
      openNav();
      return;
    }
    const page = tabPageMap[key];
    if (page) goPage(page);
  };
});
window.addEventListener("resize", () => {
  clearTimeout(window.__deviceResizeTimer);
  window.__deviceResizeTimer = setTimeout(applyDeviceMode, 120);
});
applyDeviceMode();
document.querySelectorAll(".nav-item").forEach((btn) => {
  btn.onclick = () => goPage(btn.dataset.page);
});
document.querySelectorAll(".nav-sub-title").forEach((btn) => {
  btn.onclick = () => {
    const sub = btn.closest(".nav-sub");
    if (sub) sub.classList.toggle("open");
  };
});
$("btnSaveSite").onclick = () => saveSite().then(() => alert("已保存")).catch((e) => alert(e.message));
$("btnSaveCheckin").onclick = () =>
  saveCheckin()
    .then(() => { if ($("checkinHint")) $("checkinHint").textContent = "已保存并重新调度"; alert("签到设置已保存"); })
    .catch((e) => alert(e.message));
$("btnRunCheckin").onclick = () => {
  const btn = $("btnRunCheckin");
  btn.disabled = true;
  if ($("checkinHint")) $("checkinHint").textContent = "执行中…";
  api("/api/checkin/run", { method: "POST" })
    .then((r) => {
      if ($("checkinHint")) $("checkinHint").textContent = `完成，浏览 ${r.browsed || 0} 次`;
      alert(`签到完成，随机浏览 ${r.browsed || 0} 次`);
      return loadConfig();
    })
    .catch((e) => { if ($("checkinHint")) $("checkinHint").textContent = e.message; alert(e.message); })
    .finally(() => { btn.disabled = false; });
};
$("btnTestSite").onclick = () => testSite().then(() => alert("API Key 有效")).catch((e) => { $("siteTestHint").textContent = e.message; alert(e.message); });
$("btnClearKey").onclick = () =>
  api("/api/site/clear_key", { method: "POST" })
    .then(() => loadConfig())
    .then(() => { $("siteTestHint").textContent = "已清除"; alert("已清除 API Key"); })
    .catch((e) => alert(e.message));
$("btnSaveHuman").onclick = () => saveHuman().then(() => alert("已保存")).catch((e) => alert(e.message));
$("btnSaveTr").onclick = () => saveTr().then(() => alert("已保存")).catch((e) => alert(e.message));
if ($("btnRefreshTrView")) {
  $("btnRefreshTrView").onclick = () => loadTrOverview().catch((e) => alert(e.message));
}
if ($("trStatusFilter")) {
  $("trStatusFilter").onchange = () => renderTrTorrents(window.__trTorrentItems || []);
}
if ($("btnSaveTrManage")) {
  $("btnSaveTrManage").onclick = () => saveTrManage().then(() => alert("清理规则已保存")).catch((e) => alert(e.message));
}
if ($("btnTrManageDry")) {
  $("btnTrManageDry").onclick = () => runTrManage(true).catch((e) => alert(e.message));
}
if ($("btnTrManageRun")) {
  $("btnTrManageRun").onclick = () => {
    if (!confirm("确认立即按规则清理？可能删除任务与本地文件。")) return;
    runTrManage(false).catch((e) => alert(e.message));
  };
}
if ($("trTorrentBody")) {
  $("trTorrentBody").addEventListener("click", (e) => {
    const btn = e.target.closest("[data-tr-act]");
    if (!btn) return;
    const act = btn.dataset.trAct;
    const sid = btn.dataset.sid;
    const tid = btn.dataset.tid;
    const tip = act === "remove_data" ? "删除任务并删除本地文件？" : act === "remove" ? "仅删除任务保留文件？" : "";
    if (tip && !confirm(tip)) return;
    trTorrentAction(sid, tid, act).catch((err) => alert(err.message));
  });
}
document.body.addEventListener("click", (e) => {
  const tab = e.target.closest("[data-tr-view]");
  if (!tab || tab.closest("#trPicker")) return;
  const id = tab.getAttribute("data-tr-view") || "";
  if (id === getTrViewServerId() && !tab.classList.contains("item") && !tab.classList.contains("btn-link")) return;
  setTrViewServerId(id);
  loadTrOverview().catch((err) => alert(err.message));
});
$("btnAddTr").onclick = () => openTrEditor(null);
$("trEditCancel").onclick = () => closeTrEditor();
$("trEditSave").onclick = () => {
  const servers = [...(window.__trServers || [])];
  const id = val("trEditId") || Math.random().toString(36).slice(2, 10);
  const row = {
    id,
    name: val("trEditName").trim() || "未命名",
    enabled: isOn("trEditEnabled"),
    url: val("trEditUrl").trim(),
    user: val("trEditUser").trim(),
    pass: val("trEditPass"),
    download_dir: val("trEditDir").trim(),
    paused: isOn("trEditPaused"),
    pass_set: false,
  };
  const idx = servers.findIndex((s) => s.id === id);
  if (idx >= 0) {
    if (!row.pass) {
      row.pass = "";
      row.pass_set = !!servers[idx].pass_set;
    }
    servers[idx] = row;
  } else {
    servers.push(row);
  }
  persistTrServers(servers)
    .then(() => { closeTrEditor(); alert("已保存"); })
    .catch((e) => { $("trEditHint").textContent = e.message; alert(e.message); });
};
$("trEditTest").onclick = () => {
  const body = {
    name: val("trEditName").trim(),
    url: val("trEditUrl").trim(),
    user: val("trEditUser").trim(),
    password: val("trEditPass"),
    download_dir: val("trEditDir").trim(),
    paused: isOn("trEditPaused"),
  };
  if (!body.password && val("trEditId")) body.server_id = val("trEditId");
  api("/api/transmission/test", { method: "POST", body: JSON.stringify(body) })
    .then((d) => { $("trEditHint").textContent = `OK ${d.version || ""}`; alert("连接成功"); })
    .catch((e) => { $("trEditHint").textContent = e.message; alert(e.message); });
};
$("trServerList").addEventListener("click", (e) => {
  const edit = e.target.closest("[data-tr-edit]");
  if (edit) {
    const s = (window.__trServers || []).find((x) => x.id === edit.dataset.trEdit);
    if (s) openTrEditor(s);
    return;
  }
  const test = e.target.closest("[data-tr-test]");
  if (test) {
    api("/api/transmission/test", { method: "POST", body: JSON.stringify({ server_id: test.dataset.trTest }) })
      .then((d) => alert(`「${d.name || ""}」连接成功 ${d.version || ""}`))
      .catch((err) => alert(err.message));
    return;
  }
  const del = e.target.closest("[data-tr-del]");
  if (del) {
    if (!confirm("确定删除该服务？")) return;
    const servers = (window.__trServers || []).filter((x) => x.id !== del.dataset.trDel);
    persistTrServers(servers).catch((err) => alert(err.message));
  }
});
$("btnSaveHobby").onclick = () =>
  saveHobby()
    .then(() => loadTasks().catch(() => {}))
    .then(() => alert("已保存，任务列表已按关键词对齐"))
    .catch((e) => alert(e.message));
if ($("btnSaveWish")) {
  $("btnSaveWish").onclick = () =>
    saveWishPage()
      .then(() => { if ($("wishHint")) $("wishHint").textContent = "已保存"; })
      .catch((e) => alert(e.message));
}
if ($("btnCopyWish")) {
  $("btnCopyWish").onclick = async () => {
    const v = ($("wishLink") && $("wishLink").value || "").replace(/（未启用）$/, "");
    if (!v) return alert("请先生成链接");
    try {
      await navigator.clipboard.writeText(v);
      if ($("wishHint")) $("wishHint").textContent = "链接已复制";
    } catch (_) {
      prompt("复制链接", v);
    }
  };
}
if ($("btnRegenWish")) {
  $("btnRegenWish").onclick = () => {
    if (!confirm("重新生成后旧链接将失效，继续？")) return;
    api("/api/wish/token", { method: "POST" })
      .then(() => loadWishes())
      .then(() => { if ($("wishHint")) $("wishHint").textContent = "已重新生成"; })
      .catch((e) => alert(e.message));
  };
}
if ($("btnRefreshWish")) $("btnRefreshWish").onclick = () => loadWishes().catch((e) => alert(e.message));
if ($("wishBody")) {
  $("wishBody").addEventListener("click", (e) => {
    const adopt = e.target.closest("[data-wish-adopt]");
    if (adopt) {
      api(`/api/wish/${adopt.dataset.wishAdopt}/adopt`, { method: "POST" })
        .then((r) => {
          if ($("keywords") && Array.isArray(r.keywords)) set("keywords", r.keywords.join(","));
          return loadWishes();
        })
        .then(() => alert("已写入关键词"))
        .catch((err) => alert(err.message));
      return;
    }
    const ign = e.target.closest("[data-wish-ignore]");
    if (ign) {
      api(`/api/wish/${ign.dataset.wishIgnore}/status`, {
        method: "POST",
        body: JSON.stringify({ status: "ignored" }),
      })
        .then(() => loadWishes())
        .catch((err) => alert(err.message));
      return;
    }
    const del = e.target.closest("[data-wish-del]");
    if (del) {
      if (!confirm("删除该条收集记录？")) return;
      api(`/api/wish/${del.dataset.wishDel}`, { method: "DELETE" })
        .then(() => loadWishes())
        .catch((err) => alert(err.message));
    }
  });
}
$("btnSaveRatio").onclick = () =>
  saveRatio()
    .then(() => { if ($("ratioHint")) $("ratioHint").textContent = "已保存并重新调度"; alert("已保存"); })
    .catch((e) => alert(e.message));
$("btnStart").onclick = () => {
  const btn = $("btnStart");
  btn.disabled = true;
  api("/api/scheduler/start", { method: "POST" })
    .then((st) => {
      applyRunState(true, st && st.next_run);
      return loadDash();
    })
    .catch((e) => alert(e.message || "启动失败"))
    .finally(() => { btn.disabled = false; });
};
$("btnStop").onclick = () => {
  const btn = $("btnStop");
  btn.disabled = true;
  api("/api/scheduler/stop", { method: "POST" })
    .then(() => {
      applyRunState(false, null);
      return loadDash();
    })
    .catch((e) => alert(e.message || "停止失败"))
    .finally(() => { btn.disabled = false; });
};
$("btnScan").onclick = () => api("/api/scan", { method: "POST" }).then((r) => { alert(`匹配 ${r.matched.length}，下载 ${r.downloaded.length}`); return loadDash(); }).catch((e) => alert(e.message));
$("btnScanHobby").onclick = () =>
  saveHobby()
    .then(() => api("/api/scan", { method: "POST" }))
    .then((r) => {
      const rm = (r.pruned && r.pruned.removed) || 0;
      alert(`匹配 ${r.matched.length}，下载 ${r.downloaded.length}，清理无关 ${rm}`);
      return loadTasks().catch(() => {});
    })
    .catch((e) => alert(e.message));
$("btnRefreshRatio").onclick = () => refreshRatio().catch((e) => alert(e.message));
$("btnRefreshTasks").onclick = () => loadTasks().catch((e) => alert(e.message));
$("btnEnrichTasks").onclick = () =>
  api("/api/tasks/enrich", { method: "POST" })
    .then((r) => { alert(`已补全 ${r.updated} 条`); return loadTasks(); })
    .catch((e) => alert(e.message));
$("btnRefreshPersonal").onclick = () =>
  loadPersonal(true).then(() => alert("已刷新")).catch((e) => alert(e.message));
$("btnScanTasks").onclick = () =>
  api("/api/scan", { method: "POST" })
    .then((r) => { alert(`匹配 ${r.matched.length}，下载 ${r.downloaded.length}`); return loadTasks(); })
    .catch((e) => alert(e.message));
$("taskStatusFilter").onchange = () => loadTasks().catch((e) => alert(e.message));
$("btnRefreshAccess").onclick = () => refreshAccessLogs().catch((e) => alert(e.message));
$("btnRefreshPt").onclick = () => refreshPtLogs().catch((e) => alert(e.message));
$("btnRefreshDownload").onclick = () => refreshDownloadLogs().catch((e) => alert(e.message));
if ($("btnRefreshInkLog")) $("btnRefreshInkLog").onclick = () => refreshInkLogs().catch((e) => alert(e.message));
document.body.addEventListener("click", (e) => {
  const btn = e.target.closest("[data-log-page]");
  if (!btn || btn.disabled) return;
  const kind = btn.dataset.logPage;
  const to = Number(btn.dataset.to || 1);
  refreshLogs(kind, to).catch((err) => alert(err.message));
});
if ($("btnCopyInk")) {
  $("btnCopyInk").onclick = async () => {
    const v = ($("inkApiUrl") && $("inkApiUrl").value) || "";
    if (!v) return;
    try {
      await navigator.clipboard.writeText(v);
      alert("已复制");
    } catch {
      $("inkApiUrl").select();
      document.execCommand("copy");
      alert("已复制");
    }
  };
}
if ($("btnSaveInk")) {
  $("btnSaveInk").onclick = async () => {
    try {
      const wt = ($("inkWt") && $("inkWt").value) || "0";
      await api("/api/config", {
        method: "POST",
        body: JSON.stringify({
          ink_city: ($("inkCity").value || "四川省成都市郫都区").trim() || "四川省成都市郫都区",
          ink_wt: ["1005", "1010", "0", "1"].includes(wt) ? wt : "0",
        }),
      });
      if ($("inkHint")) {
        const label = { "1005": "5 分钟", "1010": "10 分钟", "0": "1 小时", "1": "2 小时" }[wt] || "1 小时";
        $("inkHint").textContent = `已保存 · 刷新 ${label}`;
      }
    } catch (e) {
      alert(e.message || String(e));
    }
  };
}
updateInkLink();
$("btnChangePass").onclick = () =>
  api("/api/auth/password", {
    method: "POST",
    body: JSON.stringify({ old_password: val("oldPass"), new_password: val("newPass") }),
  }).then(() => alert("密码已修改")).catch((e) => alert(e.message));

$("ratioBody").addEventListener("click", (e) => {
  const tr = e.target.closest("[data-tr]");
  if (tr) {
    const name = tr.getAttribute("data-name") || "";
    tr.disabled = true;
    downloadToTr(tr.dataset.tr, name)
      .then((r) => {
        const tip = r.tr && r.tr.duplicate ? "TR 中已存在" : "已推送到";
        const sn = (r.tr && r.tr.server_name) || "Transmission";
        alert(`${tip} ${sn}${r.tr && r.tr.name ? "：" + r.tr.name : ""}`);
      })
      .catch((err) => alert(err.message))
      .finally(() => { tr.disabled = false; });
    return;
  }
  const btn = e.target.closest("[data-dl]");
  if (!btn) return;
  const name = btn.getAttribute("data-name") || "";
  btn.disabled = true;
  downloadTorrentFile(btn.dataset.dl, name)
    .then(() => alert("种子已保存到浏览器下载目录，并同步到服务器 downloads/"))
    .catch((err) => alert(err.message))
    .finally(() => { btn.disabled = false; });
});

$("taskBody").addEventListener("click", (e) => {
  const tr = e.target.closest("[data-tr]");
  if (tr) {
    const name = tr.getAttribute("data-name") || "";
    tr.disabled = true;
    downloadToTr(tr.dataset.tr, name)
      .then((r) => {
        const tip = r.tr && r.tr.duplicate ? "TR 中已存在" : "已推送到";
        const sn = (r.tr && r.tr.server_name) || "Transmission";
        alert(`${tip} ${sn}${r.tr && r.tr.name ? "：" + r.tr.name : ""}`);
        return loadTasks();
      })
      .catch((err) => alert(err.message))
      .finally(() => { tr.disabled = false; });
    return;
  }
  const dl = e.target.closest("[data-redl]");
  if (dl) {
    const name = dl.getAttribute("data-name") || "";
    dl.disabled = true;
    downloadTorrentFile(dl.dataset.redl, name)
      .then(() => { alert("种子已保存到浏览器下载目录"); return loadTasks(); })
      .catch((err) => alert(err.message))
      .finally(() => { dl.disabled = false; });
    return;
  }
  const rm = e.target.closest("[data-rm]");
  if (rm) {
    if (!confirm("确定删除该任务？")) return;
    rm.disabled = true;
    api(`/api/tasks/${rm.dataset.rm}`, { method: "DELETE" })
      .then(() => loadTasks())
      .catch((err) => alert(err.message))
      .finally(() => { rm.disabled = false; });
  }
});

(async () => {
  if (!token) {
    showLogin();
    return;
  }
  try {
    const me = await api("/api/auth/me");
    showApp(me.username);
    await boot();
  } catch {
    showLogin();
  }
})();

setInterval(() => {
  if (!token || $("appView").hidden) return;
  loadDash().catch(() => {});
}, 10000);
