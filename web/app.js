"use strict";
/* Play-by-Word. 경기 하나를 1회부터 끝까지 읽으며 야구 영어와 스페인어를 익힌다.
   자료는 lexicon.js (표현 사전), relations.js (맞대결), MLB Stats API (문장) 셋이고 문장은 저장하지 않는다.
   공부 방식: 뜻은 가려 둔다. 모르는 말만 누른다. 누른 말은 '공부할 말', 누르지 않고 읽은 말은 '아는 말'이 된다.
   한 판의 순서: 예습(떠올리기) -> 읽기(전 타석) -> 문제 -> 기사. */
const P = new URLSearchParams(location.search);
const API = P.get("api") || "https://statsapi.mlb.com/api";
const REL_SRC = P.get("rel") || "relations.js";
const LEX = window.LEXICON;
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const split = id => [id.slice(0, 2), id.slice(3)];
const narrow = () => matchMedia("(max-width:900px)").matches;
const CLS = { V: "동사", N: "명사", M: "꾸미는 말" };
const LANG = { en: "영어", es: "스페인어" };
const other = l => (l === "en" ? "es" : "en");
const TIER = { 1: "가장 자주 쓰는 100개에 드는 말", 2: "자주 쓰는 300개에 드는 말", 3: "자주 쓰는 700개에 드는 말", 4: "가끔 쓰는 말" };
const GAME_STATUS = { "Scheduled": "예정", "Pre-Game": "경기 전", "Warmup": "경기 전", "In Progress": "진행 중", "Postponed": "연기", "Suspended": "중단", "Cancelled": "취소" };
const KIND = { single: "bat", double: "bat", triple: "bat", home_run: "bat", sac_fly: "bat", sac_bunt: "bat", walk: "walk", intent_walk: "walk",
  hit_by_pitch: "walk", strikeout: "pitch", strikeout_double_play: "pitch", field_out: "field", force_out: "field",
  grounded_into_double_play: "field", double_play: "field", field_error: "field", fielders_choice: "field", fielders_choice_out: "field" };
/* 사전의 사건 이름에 없는 것들. 타석이 주루 플레이로 끝났을 때 나온다 */
const EVENT_KO = { stolen_base_2b: "2루 도루", stolen_base_3b: "3루 도루", stolen_base_home: "홈 도루", caught_stealing_3b: "3루 도루 실패", caught_stealing_home: "홈 도루 실패",
  pickoff_2b: "2루 견제사", pickoff_3b: "3루 견제사", pickoff_caught_stealing_2b: "견제에 걸린 2루 도루 실패", pickoff_caught_stealing_3b: "견제에 걸린 3루 도루 실패",
  pickoff_caught_stealing_home: "견제에 걸린 홈 도루 실패", wild_pitch: "폭투", passed_ball: "포일", balk: "보크", other_out: "주루사", runner_double_play: "주루 병살", game_advisory: "경기 알림" };
const PBF = "allPlays,result,type,event,eventType,description,about,atBatIndex,inning,halfInning,isTopInning";
const QUICK = ["660271", "592450", "669373", "673490", "808982"];
const STEPS = [0.25, 0.5, 0.7, 0.8, 0.9, 0.95];
/* 스페인어 입문자를 위한 기초 낱말. 표현 사전은 야구 표현만 담으므로 관사, 전치사, 서수 같은 말은 여기서 푼다 */
const BASIC_ES = {
  el: "그 (남성 단수 명사 앞)", la: "그 (여성 단수 명사 앞)", los: "그 (남성 복수 명사 앞)", las: "그 (여성 복수 명사 앞)", un: "하나의 (남성)", una: "하나의 (여성)",
  al: "a + el. ~에게, ~쪽으로", del: "de + el. ~의, ~에서", a: "~에게, ~쪽으로. 사람이 목적어일 때도 앞에 붙는다", de: "~의, ~에서", en: "~에서, ~에", con: "~으로, ~와 함께",
  por: "~으로, ~쪽으로", para: "~을 위해, ~쪽으로", entre: "~사이로", sin: "~없이", tras: "~뒤에", ante: "~을 상대로", contra: "~에 맞서", hacia: "~쪽으로",
  hasta: "~까지", desde: "~에서부터", sobre: "~위로", durante: "~동안", y: "그리고", e: "그리고 (i 소리 앞)", o: "또는", pero: "그러나", que: "~하는, ~라는", mientras: "~하는 동안",
  cuando: "~할 때", como: "~로서, ~처럼", si: "만약", su: "그의", sus: "그의 (복수 명사 앞)", se: "동사 앞에 붙어 '스스로 ~되다'", le: "그에게", lo: "그것을", les: "그들에게",
  "más": "더", muy: "매우", no: "아니다", ya: "이미", luego: "그 뒤에", "también": "또한", "después": "뒤에", antes: "앞서", ahora: "이제", "aquí": "여기", "así": "이렇게",
  es: "~이다", fue: "~이었다", son: "~이다 (복수)", era: "~이었다", hay: "~이 있다", ha: "~했다 (완료형을 만든다)", han: "~했다 (복수, 완료형을 만든다)",
  este: "이 (남성)", esta: "이 (여성)", ese: "그 (남성)", esa: "그 (여성)", otro: "다른 (남성)", otra: "다른 (여성)", todo: "모든", todos: "모든 (복수)", cada: "각",
  uno: "하나", dos: "둘", tres: "셋", cuatro: "넷", cinco: "다섯", seis: "여섯", siete: "일곱", ocho: "여덟", nueve: "아홉", diez: "열",
  "1ra": "primera. 첫째 (1회, 1루)", "2da": "segunda. 둘째 (2회, 2루)", "3ra": "tercera. 셋째 (3회, 3루)", "4ta": "cuarta. 넷째", "5ta": "quinta. 다섯째",
  "6ta": "sexta. 여섯째", "7ma": "séptima. 일곱째", "8va": "octava. 여덟째", "9na": "novena. 아홉째", "10ma": "décima. 열째",
  "1ro": "primero. 첫째", "1er": "primer. 첫", "2do": "segundo. 둘째", "3ro": "tercero. 셋째", "3er": "tercer. 셋째", "4to": "cuarto. 넷째", "5to": "quinto. 다섯째",
  "6to": "sexto. 여섯째", "7mo": "séptimo. 일곱째", "8vo": "octavo. 여덟째", "9no": "noveno. 아홉째", "10mo": "décimo. 열째",
};
/* 맞대결의 동사를 스페인어로 보여 줄 때 쓰는 꼴. 스페인어 캡션에서 '<선수> 동사 a <선수>'로 자주 나오는 것만 */
const ES_REL = { "strike out": "poncha a", k: "poncha a", fan: "abanica a", freeze: "congela a", whiff: "abanica a", "punch out": "poncha a", "sit down": "poncha a",
  ring: "poncha a", get: "domina a", retire: "retira a", induce: "domina a", coax: "domina a", "set down": "retira a", nab: "pesca a", "throw out": "saca a",
  catch: "atrapa a", "pick off": "sorprende a", "cut down": "saca a", "gun down": "saca a", nail: "saca a", rob: "le roba a", plate: "remolca a", score: "impulsa a" };

/* ---------- 공부 기록 (이 브라우저에만 남는다) ---------- */
function loadStore() {
  let d = {};
  try { d = JSON.parse(localStorage.getItem("pbw2") || "{}") || {}; } catch (e) { /* 저장이 막힌 환경에서는 이번 방문 동안만 기억한다 */ }
  const set = (o, l) => new Set(((o || {})[l]) || []);
  return { lang: d.lang === "en" || d.lang === "es" ? d.lang : "", both: !!d.both, read: Array.isArray(d.read) ? d.read : [],
    known: { en: set(d.known, "en"), es: set(d.known, "es") }, study: { en: set(d.study, "en"), es: set(d.study, "es") } };
}
function saveStore() {
  const arr = o => ({ en: [...o.en], es: [...o.es] });
  try { localStorage.setItem("pbw2", JSON.stringify({ lang: store.lang, both: store.both, read: store.read, known: arr(store.known), study: arr(store.study) })); } catch (e) { /* 위와 같음 */ }
}
const store = loadStore();
if (P.get("lang") === "en" || P.get("lang") === "es") store.lang = P.get("lang");
if (P.get("both")) store.both = P.get("both") === "1";
const state = { date: P.get("date") || "2026-10-28", pk: null, g: null, tab: P.get("tab") || "prep", keepTab: !!P.get("tab"), lang: store.lang, both: store.both,
  nameTok: new Set(), sel: null, gl: {}, checked: new Set(), read: new Set(), looked: {}, rv: {}, prep: null, quiz: null, base: { en: 0, es: 0 },
  relId: P.get("player") || null, relEdge: null, relCache: {} };
const statusOf = (l, key) => (store.study[l].has(key) ? "study" : store.known[l].has(key) ? "known" : "new");
function markKnown(l, key) { store.study[l].delete(key); store.known[l].add(key); }
function markStudy(l, key) { store.known[l].delete(key); store.study[l].add(key); }

async function getJSON(path) {
  const r = await fetch(API + path);
  if (!r.ok) throw new Error("HTTP " + r.status);
  return r.json();
}
function fail(what, e) { $("#msg").innerHTML = `<div class="err">${esc(what)} (${esc(e.message || e)}). 인터넷 연결을 확인한 뒤 날짜를 다시 골라 보세요.</div>`; }

/* ---------- 문장에서 표현 찾기: 이름을 건너뛰고, 사전의 '글에 나오는 꼴'과 가장 길게 맞는 것을 고른다 ---------- */
const WORD = /[A-Za-zÀ-ÖØ-öø-ÿ0-9][A-Za-zÀ-ÖØ-öø-ÿ0-9'’\-]*/g;
function tag(text, lang) {
  const forms = LEX[lang].forms, toks = [];
  let m, last = 0;
  WORD.lastIndex = 0;
  while ((m = WORD.exec(text))) {
    if (m.index > last) toks.push({ s: text.slice(last, m.index), w: false });
    toks.push({ s: m[0], w: true, i: m.index });
    last = m.index + m[0].length;
  }
  if (last < text.length) toks.push({ s: text.slice(last), w: false });
  let start = true;
  toks.forEach((t, n) => {
    if (!t.w) { if (/[.!?:]\s*$/.test(t.s)) start = true; return; }
    const base = t.s.replace(/['’]s$/, ""), low = base.toLowerCase(), nx = toks[n + 1];
    const cap = /^[A-ZÀ-Þ]/.test(base) && /[a-zß-ÿ]/.test(base);
    const caps = /^[A-Z]{2,3}$/.test(base) && state.nameTok.has(low);          // TJ, CJ 같은 이름
    const init = /^[A-Z]$/.test(base) && nx && !nx.w && nx.s.startsWith(".");   // J.T. 같은 머리글자
    t.name = (cap && (state.nameTok.has(low) || !start)) || caps || !!init;
    t.low = t.s.toLowerCase().replace(/’/g, "'");
    start = false;
  });
  const out = [];
  for (let i = 0; i < toks.length;) {
    const t = toks[i];
    if (!t.w || t.name || /^\d/.test(t.s)) { out.push({ text: t.s, name: !!t.name, w: t.w }); i++; continue; }
    let hit = null;
    for (let n = 4; n >= 1 && !hit; n--) {
      let j = i, ok = true; const parts = [];
      for (let k = 0; k < n; k++) {
        const w = toks[j];
        if (!w || !w.w || w.name) { ok = false; break; }
        parts.push(w.low);
        if (k < n - 1) { const sep = toks[j + 1]; if (!sep || sep.w || sep.s !== " ") { ok = false; break; } j += 2; }
      }
      if (ok && forms[parts.join(" ")]) hit = { end: j, keys: forms[parts.join(" ")] };
    }
    if (!hit) { out.push({ text: t.s, w: true }); i++; continue; }
    let prev = null;
    for (let k = out.length - 1; k >= 0; k--) if (out[k].text.trim()) { prev = out[k]; break; }
    let key = hit.keys[0];
    if (prev && prev.name) { const v = hit.keys.find(k => k.endsWith("|V")); if (v) key = v; }   // 이름 바로 뒤는 동사로 읽는다
    const e = toks[hit.end];
    out.push({ text: text.slice(t.i, e.i + e.s.length), key });
    i = hit.end + 1;
  }
  out.forEach((s, i) => { if (s.key) { const nx = out.slice(i + 1).find(x => x.text.trim()); s.obj = !!(nx && nx.name); } });   // 뒤에 사람 이름이 오는가
  return out;
}
const TAGC = new Map();
function tagged(text, lang) {
  const k = lang + "\n" + text;
  if (!TAGC.has(k)) TAGC.set(k, tag(text, lang));
  return TAGC.get(k);
}
/* 뜻이 "A / B" 꼴이면 A 는 뒤에 사람이 올 때(…을 삼진으로 잡다), B 는 아닐 때(삼진을 당하다). 짧은 뜻은 첫 풀이만 */
function shortKo(ko, obj) {
  const p = ko.split(" / "), s = p.length > 1 ? p[obj ? 0 : 1] : ko;
  const t = s.split(" (")[0].split(",")[0].replace(/^\([^)]*\)\s*/, "").trim();
  if (t) return t;
  const m = s.match(/:\s*([^)]+)\)/);   // 뜻 전체가 괄호 속 설명일 때
  return m ? m[1].trim() : s.replace(/[()]/g, "").trim();
}
const fullKo = ko => ko.replace(" / ", ", ");
const evName = (e, fallback) => LEX.events[e] || EVENT_KO[e] || fallback || e;
function hint(u) { return u.ev.length && u.ev[0][1] >= 0.4 ? `주로 ${evName(u.ev[0][0])} 장면에 쓰는 말 (뜻 준비 중)` : "뜻 준비 중"; }
function unitHTML(seg, lang, edge) {
  const id = lang + ":" + seg.key;
  return `<span class="u ${statusOf(lang, seg.key)}${state.sel === id ? " sel" : ""}" tabindex="0" role="button" data-id="${esc(id)}"${seg.obj ? ' data-o="1"' : ""}${edge ? ` data-e="${edge}"` : ""}>${esc(seg.text)}</span>`;
}
function plainHTML(seg, lang) {
  if (lang !== "es" || seg.name || !seg.w) return esc(seg.text);
  const low = seg.text.toLowerCase();
  return BASIC_ES[low] ? `<span class="b" tabindex="0" role="button" data-b="${esc(low)}">${esc(seg.text)}</span>` : esc(seg.text);
}
const wordsHTML = (text, lang) => tagged(text, lang).map(s => (s.key ? unitHTML(s, lang) : plainHTML(s, lang))).join("");
/* 문장 아래의 뜻풀이 줄. 누른 자리에서만 뜻을 보여 준다. 같은 말이 다음에 또 나오면 다시 떠올려 보게 하려는 것 */
function glsHTML(key) {
  return (state.gl[key] || []).map(e => {
    if (e.b) return `<span class="ge b"><b>${esc(e.w)}</b>${esc(BASIC_ES[e.b])}</span>`;
    const [l, k] = split(e.id), u = LEX[l].units[k];
    return `<button class="ge" data-more="${esc(e.id)}" title="자세히 보기"><b>${esc(e.w)}</b>${esc(u.ko ? shortKo(u.ko, e.o) : hint(u))}</button>`;
  }).join("");
}
function sent(text, lang, key, cls) {
  return `<p class="sent${cls ? " " + cls : ""}" lang="${lang}" data-s="${esc(key)}">${wordsHTML(text, lang)}</p><div class="gls" data-g="${esc(key)}">${glsHTML(key)}</div>`;
}
function addGloss(el, entry) {
  const s = el.closest("[data-s]");
  if (!s) return false;
  const key = s.dataset.s, list = state.gl[key] || (state.gl[key] = []);
  if (!list.some(x => (entry.b ? x.b === entry.b : x.id === entry.id))) list.push(entry);
  const g = $$("[data-g]").find(n => n.dataset.g === key);
  if (g) g.innerHTML = glsHTML(key);
  return !!g;
}

/* ---------- 경기 목록 ---------- */
async function loadDate() {
  $("#games").innerHTML = `<span class="note">경기 목록을 불러오는 중…</span>`;
  $("#msg").innerHTML = "";
  try {
    const day = state.date;
    const d = await getJSON(`/v1/schedule?sportId=1&date=${encodeURIComponent(day)}`);
    if (state.date !== day) return;   // 그사이 다른 날짜를 골랐으면 버린다
    const games = (d.dates || []).flatMap(x => x.games || []);
    if (!games.length) { $("#games").innerHTML = `<span class="note">이 날은 경기가 없습니다. 시즌 중인 날짜를 골라 보세요 (예: 2026-10-28 월드시리즈 5차전).</span>`; return; }
    $("#games").innerHTML = games.map(g => {
      const a = g.teams.away, h = g.teams.home, fin = /Final|Completed|Game Over/.test(g.status.detailedState);
      return `<button class="game" data-pk="${g.gamePk}" aria-pressed="false">${esc(a.team.name)} ${fin ? `${a.score ?? ""} : ${h.score ?? ""}` : "vs"} ${esc(h.team.name)}<small>${fin ? "종료" : esc(GAME_STATUS[g.status.detailedState] || g.status.detailedState)}</small></button>`;
    }).join("");
    const first = games.find(g => /Final|Completed/.test(g.status.detailedState));
    if (first) loadGame(first.gamePk);
  } catch (e) { $("#games").innerHTML = ""; fail("경기 목록을 받지 못했습니다", e); }
}

/* ---------- 경기 하나: 전 타석의 기록 문장(영어, 스페인어), 하이라이트 캡션, 기사 ---------- */
async function loadGame(pk) {
  state.pk = pk; state.g = null; state.prep = null; state.quiz = null; state.sel = null;
  state.gl = {}; state.checked = new Set(); state.looked = {}; state.rv = {};
  state.read = new Set((store.read.find(x => x[0] === pk) || [0, []])[1]);
  state.prepSeen = { en: new Set(), es: new Set() };
  state.base = { en: store.known.en.size, es: store.known.es.size };
  if (state.tab !== "rel" && !state.keepTab) state.tab = "prep";
  state.keepTab = false;
  $$(".game").forEach(b => b.setAttribute("aria-pressed", String(+b.dataset.pk === pk)));
  $("#msg").innerHTML = "";
  idleCard(); render();
  try {
    const [feed, pbpEs, cEn, cEs] = await Promise.all([
      getJSON(`/v1.1/game/${pk}/feed/live`),
      getJSON(`/v1/game/${pk}/playByPlay?language=es&fields=${PBF}`).catch(() => ({ allPlays: [] })),
      getJSON(`/v1/game/${pk}/content`),
      getJSON(`/v1/game/${pk}/content?language=es`).catch(() => ({})),
    ]);
    if (state.pk !== pk) return;
    build(feed, pbpEs, cEn, cEs);
    render();
  } catch (e) { state.pk = null; render(); fail("경기 자료를 받지 못했습니다", e); }
}
function addNames(s) { String(s || "").toLowerCase().split(/[\s\-]+/).forEach(x => { x = x.replace(/[.,']/g, ""); if (x.length > 1 && !["de", "la", "del", "los", "las", "van", "von", "jr", "sr", "ii", "iii", "st"].includes(x)) state.nameTok.add(x); }); }
function paragraphs(body) {   // 리캡 본문은 HTML 일 때도 있고 마크다운일 때도 있다. 글자만 남긴다
  const doc = new DOMParser().parseFromString(body, "text/html");
  doc.querySelectorAll("script,iframe,blockquote,style,figure,video").forEach(n => n.remove());
  doc.body.querySelectorAll("p,div,li,br,h1,h2,h3,h4").forEach(n => n.after("\n\n"));
  const md = t => t.replace(/!\[[^\]]*\]\([^)]*\)/g, "").replace(/\[([^\]]+)\]\((?:[^()]|\([^()]*\))*\)/g, "$1")
    .replace(/(\*\*|__)(.+?)\1/g, "$2").replace(/^\s*#{1,6}\s+/, "").replace(/^\s*[-*]\s+/, "").replace(/\s+/g, " ").trim();
  return doc.body.textContent.split(/\n{2,}/).map(md).filter(t => t && !/^https?:\S+$/.test(t));
}
function build(feed, pbpEs, cEn, cEs) {
  const gd = feed.gameData, ld = feed.liveData;
  state.nameTok = new Set(); TAGC.clear();
  Object.values(gd.players || {}).forEach(p => [p.fullName, p.useName, p.lastName, p.firstName, p.boxscoreName].forEach(addNames));
  ["away", "home"].forEach(s => { const t = gd.teams[s]; [t.name, t.teamName, t.clubName, t.locationName, t.shortName].forEach(addNames); });
  addNames((gd.venue || {}).name);
  const all = ld.plays.allPlays, byPid = {}, esBy = {};
  all.forEach(p => (p.playEvents || []).forEach(e => { if (e.playId) byPid[e.playId] = p.about.atBatIndex; }));
  (pbpEs.allPlays || []).forEach(p => { esBy[p.atBatIndex ?? (p.about || {}).atBatIndex] = p.result || {}; });
  const items = c => (((c.highlights || {}).highlights || {}).items) || [];
  const esItem = {}; items(cEs).forEach(x => { esItem[x.id] = x; });
  const caps = {};
  items(cEn).forEach(x => {
    const abi = byPid[x.guid];
    if (abi === undefined) return;
    const y = esItem[x.id] || {}, cur = caps[abi];
    const c = { tEn: (x.title || "").trim(), dEn: (x.description || "").trim(), tEs: (y.title || "").trim(), dEs: (y.description || "").trim() };
    if (c.tEs === c.tEn) c.tEs = ""; if (c.dEs === c.dEn) c.dEs = "";
    if (!cur || (!cur.dEn && c.dEn)) caps[abi] = c;
  });
  const team = s => ({ name: gd.teams[s].name, abbr: gd.teams[s].abbreviation });
  const ls = ld.linescore || {};
  const g = { pk: state.pk, away: team("away"), home: team("home"), date: (gd.datetime || {}).officialDate || state.date,
    lines: (ls.innings || []).map(i => ({ n: i.num, a: (i.away || {}).runs, h: (i.home || {}).runs })),
    R: { a: ((ls.teams || {}).away || {}).runs, h: ((ls.teams || {}).home || {}).runs }, plays: [], halves: [], recap: {}, gu: {}, pt: {}, pn: {} };
  let pa = 0, ps = 0, no = 0;
  for (const p of all) {
    const r = p.result || {};
    if (!r.description) continue;
    const es = esBy[p.about.atBatIndex] || {}, a = r.awayScore ?? pa, h = r.homeScore ?? ps;
    const play = { abi: p.about.atBatIndex, no: ++no, inning: p.about.inning, top: p.about.isTopInning, half: p.about.inning + (p.about.isTopInning ? "T" : "B"),
      type: r.eventType, event: r.event, en: r.description, es: es.description || "", cap: caps[p.about.atBatIndex] || {}, away: a, home: h, runs: (a - pa) + (h - ps),
      bid: (p.matchup.batter || {}).id, pid: (p.matchup.pitcher || {}).id };
    g.plays.push(play);
    let hv = g.halves[g.halves.length - 1];
    if (!hv || hv.key !== play.half) { hv = { key: play.half, inning: play.inning, top: play.top, plays: [] }; g.halves.push(hv); }
    hv.plays.push(play);
    pa = a; ps = h;
  }
  if (g.R.a === undefined) { g.R.a = pa; g.R.h = ps; }
  for (const [lang, c] of [["en", cEn], ["es", cEs]]) {
    const r = (((c.editorial || {}).recap || {}).mlb) || {};
    if (r.body) g.recap[lang] = { headline: r.headline || "", by: (r.contributors || []).map(x => x.name).join(", "), ps: paragraphs(r.body) };
  }
  state.g = g;
}
const capText = (p, l) => (l === "en" ? p.cap.dEn || p.cap.tEn : p.cap.dEs || p.cap.tEs) || "";
function gameUnits(l) {   // 이 경기의 기록 문장과 캡션에 나오는 표현: 횟수, 나온 자리, 예문
  const g = state.g, U = LEX[l].units;
  if (g.gu[l]) return g.gu[l];
  const m = new Map();
  for (const p of g.plays) for (const [kind, text] of [["기록 문장", p[l]], ["캡션", capText(p, l)]]) {
    if (!text) continue;
    const segs = tagged(text, l);
    segs.forEach((s, i) => { if (!s.key) return; const e = m.get(s.key) || { n: 0, occ: [] }; e.n++; e.occ.push({ p, kind, text, segs, i }); m.set(s.key, e); });
  }
  // 예문과 문제는 그 말이 주로 쓰이는 사건의 타석에서 고른다. 한국어 뜻이 그 쓰임을 기준으로 적혀 있어서다 (slam 은 홈런 장면의 뜻으로 풀었는데 '담장에 부딪히다'로도 쓰인다)
  for (const [k, e] of m) { const ev = U[k].ev.map(x => x[0]); e.fit = ev.length ? e.occ.filter(o => ev.includes(o.p.type)) : e.occ; e.ex = (e.fit[0] || e.occ[0]).text; }
  return (g.gu[l] = m);
}
/* 아는 말이 사전 전체의 쓰임 가운데 차지하는 몫 = 처음 보는 경기에서 만날 표현을 얼마나 아는가.
   다음 목표까지 몇 개가 남았는지는 '자주 쓰는 말부터' 센다. 빈도순이 가장 빨리 오른다는 것이 분석 결과였다 */
const COV = {};
function cover(l) {
  const U = LEX[l].units, K = store.known[l];
  if (!COV[l]) { const keys = Object.keys(U).sort((a, b) => U[b].f - U[a].f); let F = 0, O = 0; for (const k of keys) { F += U[k].f; O += U[k].fo || 0; } COV[l] = { keys, F, O }; }
  const { keys, F, O } = COV[l];
  let f = 0, o = 0;
  for (const k of K) { const u = U[k]; if (u) { f += u.f; o += u.fo || 0; } }
  const cur = F ? f / F : 0, target = STEPS.find(s => s > cur + 1e-9);
  let need = 0, acc = f;
  if (target) for (const k of keys) { if (acc / F >= target) break; if (!K.has(k)) { acc += U[k].f; need++; } }
  return { cap: Math.floor(100 * cur), off: O ? Math.floor(100 * o / O) : null, target: target ? Math.round(target * 100) : null, need };
}

/* ---------- 머리: 점수판(읽은 회가 채워진다), 진도, 단계 ---------- */
function counts(l) {
  const gu = gameUnits(l); let k = 0, s = 0;
  for (const key of gu.keys()) { const st = statusOf(l, key); if (st === "known") k++; else if (st === "study") s++; }
  return { n: gu.size, k, s };
}
function renderHead() {
  const g = state.g, l = state.lang, el = $("#ghead"), mini = $("#mini");
  if ($("#card").classList.contains("idle")) idleCard();   // 공부할 말 목록도 지금 기록에 맞춘다
  if (!g || !l || !g.plays.length) { el.innerHTML = ""; if (mini) mini.textContent = ""; return; }
  const c = counts(l), nRead = g.halves.filter(h => state.read.has(h.key)).length;
  if (state.tab === "rel") { el.innerHTML = ""; if (mini) mini.textContent = ""; return; }
  if (mini) mini.innerHTML = `<b class="k">아는 말 ${c.k}</b><b class="s">공부할 말 ${c.s}</b><span>읽은 회 ${nRead}/${g.halves.length}</span>`;
  const cv = cover(l), n = c.n || 1, pct = x => (100 * x / n).toFixed(1), has = new Set(g.halves.map(h => h.key));
  const cell = (v, key) => (has.has(key)
    ? `<td><a href="#h-${key}" data-jump="${key}"${state.read.has(key) ? ' class="rd"' : ""} title="${key.slice(0, -1)}회${key.endsWith("T") ? "초" : "말"}${state.read.has(key) ? ", 읽음" : ""}">${v ?? 0}</a></td>` : `<td class="x">x</td>`);
  el.innerHTML = `<div class="ghead">
    <div class="gsc"><h2>${esc(g.away.name)} ${g.R.a} : ${g.R.h} ${esc(g.home.name)}</h2><p class="gd">${esc(g.date)}</p>
      <table class="line"><tr><th></th>${g.lines.map(i => `<th>${i.n}</th>`).join("")}<th class="r">R</th></tr>
        <tr><td class="t">${esc(g.away.abbr)}</td>${g.lines.map(i => cell(i.a, i.n + "T")).join("")}<td class="r">${g.R.a}</td></tr>
        <tr><td class="t">${esc(g.home.abbr)}</td>${g.lines.map(i => cell(i.h, i.n + "B")).join("")}<td class="r">${g.R.h}</td></tr></table>
      <p class="lnote">읽은 회는 칸이 채워집니다. 칸을 누르면 그 회로 갑니다.</p></div>
    <div class="meter"><h3>이 경기의 ${LANG[l]} 표현 ${c.n}개</h3>
      <div class="bar" role="img" aria-label="아는 말 ${c.k}개, 공부할 말 ${c.s}개, 아직 안 본 말 ${c.n - c.k - c.s}개"><i class="k" style="width:${pct(c.k)}%"></i><i class="s" style="width:${pct(c.s)}%"></i></div>
      <p class="cnt"><b class="k">아는 말 ${c.k}</b><b class="s">공부할 말 ${c.s}</b><span>아직 안 본 말 ${c.n - c.k - c.s}</span></p>
      <p class="rd">처음 보는 경기에서 만날 표현 가운데 캡션은 <b>${cv.cap}%</b>${cv.off !== null ? `, 기록 문장은 <b>${cv.off}%</b>` : ""}를 이미 압니다.
        ${cv.target ? `다음 목표는 캡션 ${cv.target}%입니다. 자주 쓰는 말부터 ${cv.need}개를 더 익히면 닿습니다.` : "캡션의 표현 95%를 넘겼습니다."}</p></div></div>`;
}
function renderTabs() {
  const t = (id, name, n) => `<button class="tab${n ? "" : " aux"}" role="tab" data-tab="${id}" aria-selected="${state.tab === id}">${n ? `<i>${n}</i>` : ""}${name}</button>`;
  $("#tabs").innerHTML = state.lang ? t("prep", "예습", 1) + t("read", "읽기", 2) + t("quiz", "문제", 3) + t("recap", "기사", 4) + `<span class="sep"></span>` + t("rel", "맞대결") + `<span class="mini" id="mini"></span>` : "";
}
function render() {
  document.body.dataset.lang = state.lang || "en";
  $$(".seg button").forEach(b => b.setAttribute("aria-pressed", String(b.dataset.setlang === state.lang)));
  $("#both").checked = state.both;
  renderTabs(); renderHead();
  const v = $("#view");
  if (!state.lang) { v.innerHTML = `<div class="choose"><h2>어느 말을 공부할까요?</h2><p>한 번에 한 언어만 봅니다. 위에서 언제든 바꿀 수 있습니다.</p>
    <div class="two"><button class="en" data-setlang="en">영어<small>기록 문장과 캡션의 표현을 넓힙니다</small></button><button class="es" data-setlang="es">스페인어<small>기초 낱말 풀이와 함께 처음부터 읽습니다</small></button></div></div>`; return; }
  if (state.tab === "rel") { renderRel(); return; }
  if (!state.pk) { v.innerHTML = ""; return; }
  if (!state.g) { v.innerHTML = `<p class="note">이 경기의 기록과 캡션을 받아 오는 중…</p>`; return; }
  if (!state.g.plays.length) { v.innerHTML = `<p class="note">이 경기에는 아직 타석 기록이 없습니다.</p>`; return; }
  ({ prep: renderPrep, read: renderRead, quiz: renderQuiz, recap: renderRecap }[state.tab] || renderPrep)();
}

/* ---------- 1. 예습: 지난번에 몰랐던 말과 이 경기에 자주 나오는 낯선 말을 먼저 떠올려 본다 ---------- */
function prepStart() {
  const l = state.lang, gu = gameUnits(l), U = LEX[l].units, seen = state.prepSeen[l];   // 이 경기에서 이미 예습한 말은 다시 내지 않는다
  const mine = [...gu.entries()].filter(([k]) => U[k].ko && !seen.has(k) && statusOf(l, k) === "study").sort((a, b) => b[1].n - a[1].n).map(([key, e]) => ({ key, ex: e.ex, n: e.n }));
  const away = [...store.study[l]].filter(k => U[k] && U[k].ko && !gu.has(k) && !seen.has(k)).sort((a, b) => U[b].f - U[a].f).map(key => ({ key, ex: null, n: 0 }));
  const fresh = [...gu.entries()].filter(([k]) => U[k].ko && !seen.has(k) && statusOf(l, k) === "new").sort((a, b) => b[1].n - a[1].n || U[a[0]].t - U[b[0]].t).map(([key, e]) => ({ key, ex: e.ex, n: e.n }));
  state.prep = { lang: l, list: [...mine.slice(0, 6), ...away.slice(0, 3), ...fresh].slice(0, 10), i: 0, shown: false, res: [] };
  state.prep.list.forEach(x => seen.add(x.key));
}
function baseLine(l, u) {   // 기본형과 꼴. 스페인어 동사에는 입문자용 풀이를 한 줄 붙인다
  if (u.c !== "V" && u.fm.length < 2) return "";
  let s = `기본형 ${esc(u.u)}${u.fm.length ? `, 글에 나오는 꼴 ${u.fm.map(esc).join(", ")}` : ""}.`;
  if (l === "es" && u.c === "V") s += u.u.endsWith("se") ? " se가 붙으면 주어 자신에게 일어나는 일입니다 (se poncha: 삼진을 당하다)." : " -a나 -e로 끝나면 '그가 ~한다', -ó는 '~했다', -ndo는 '~하면서'입니다.";
  return `<p class="base">${s}</p>`;
}
function renderPrep() {
  const l = state.lang;
  if (!state.prep || state.prep.lang !== l) prepStart();
  const pr = state.prep, U = LEX[l].units, n = pr.list.length;
  const dots = `<div class="dots" aria-hidden="true">${pr.list.map((x, i) => `<i class="${pr.res[i] || (i === pr.i ? "cur" : "")}"></i>`).join("")}</div>`;
  let top;
  if (!n) top = `<div class="sum"><p>이 경기의 표현 가운데 예습할 낯선 말이 없습니다. 바로 읽어도 됩니다.</p><button class="btn" data-tab="read">읽기 시작</button></div>`;
  else if (pr.i >= n) {
    const k = pr.res.filter(x => x === "k").length;
    top = `<div class="sum">${dots}<p>예습 ${n}개를 마쳤습니다. 알고 있던 말이 ${k}개, 공부할 말이 ${n - k}개입니다. 공부할 말은 읽는 동안 굵은 밑줄로 표시되고 문제에 먼저 나옵니다.</p>
      <div class="row2"><button class="btn" data-tab="read">읽기 시작</button><button class="btn ghost" data-prep="again">낯선 말 더 예습하기</button></div></div>`;
  } else {
    const it = pr.list[pr.i], u = U[it.key], was = statusOf(l, it.key) === "study";
    const seg = it.ex ? tagged(it.ex, l).find(s => s.key === it.key) || {} : {};
    const body = it.ex ? `<p class="sent" lang="${l}">${tagged(it.ex, l).map(s => (s.key === it.key ? `<mark class="tgt">${esc(s.text)}</mark>` : esc(s.text))).join("")}</p>`
      : `<p class="sent lone" lang="${l}"><mark class="tgt">${esc(u.fm[0] || u.u)}</mark></p>`;
    top = `<div class="flash">${dots}<p class="cnt">${pr.i + 1} / ${n}. ${it.ex ? `${was ? "지난번에 몰랐던 말입니다. " : ""}이 경기에 ${it.n}번 나옵니다.` : "지난번에 몰랐던 말입니다. 이 경기에는 나오지 않습니다."}</p>
      ${body}
      ${pr.shown ? `<p class="a">${esc(fullKo(u.ko))}</p>${u.ko.includes(" / ") && seg.key ? `<p class="more">이 문장에서는 "${esc(shortKo(u.ko, seg.obj))}"입니다. 뒤에 선수 이름이 ${seg.obj ? "오지 않으면" : "오면"} "${esc(shortKo(u.ko, !seg.obj))}"입니다.</p>` : ""}${baseLine(l, u)}
        <div class="row2"><button class="btn" data-prep="k">알고 있었어요</button><button class="btn ghost" data-prep="s">몰랐어요</button></div>`
      : `<p class="ask">칠한 말의 뜻을 먼저 떠올려 보세요.</p><div class="row2"><button class="btn" data-prep="show">뜻 보기</button><button class="btn ghost" data-prep="k">이미 알아요</button></div>`}
      <p class="keys">키보드로도 넘길 수 있습니다. 스페이스는 뜻 보기, 1은 아는 말, 2는 모르는 말입니다.</p></div>`;
  }
  $("#view").innerHTML = `<p class="lead">읽기 전에 이 경기에 자주 나오는 낯선 말을 먼저 떠올려 봅니다. 지난 경기에서 몰랐던 말이 있으면 그것부터 나옵니다.</p>${top}${patternsHTML()}`;
}
function prepAct(what) {
  const pr = state.prep, l = state.lang;
  if (!pr || state.tab !== "prep") return;
  if (what === "again") state.prep = null;
  else if (pr.i >= pr.list.length) return;
  else if (what === "show" || (what === "s" && !pr.shown)) pr.shown = true;   // 모른다고 하면 뜻부터 보여 준다
  else { (what === "k" ? markKnown : markStudy)(l, pr.list[pr.i].key); pr.res[pr.i] = what; pr.i++; pr.shown = false; saveStore(); renderHead(); }
  renderPrep();
}

/* ---------- 문형: 기록 문장은 몇 가지 틀로 쓰인다. 가로가 틀(통합 관계), 세로가 그 자리에 갈아 끼우는 말(계열 관계) ---------- */
function sentences(segs) {
  const out = []; let cur = [], prev = "";
  for (const s of segs) {
    cur.push(s);
    if (s.key || s.w) { prev = s.text; continue; }
    if (/[.!?]/.test(s.text) && !/^(Jr|Sr|[A-Z])$/.test(prev)) { out.push(cur); cur = []; }
  }
  if (cur.some(s => s.key || s.w)) out.push(cur);
  return out;
}
function skeleton(sen) {
  const parts = [], lit = t => { const last = parts[parts.length - 1]; if (last && last.t === "L") last.text += t; else parts.push({ t: "L", text: t }); };
  for (const s of sen) {
    const last = parts[parts.length - 1];
    if (s.name) { if (!last || last.t !== "P") parts.push({ t: "P" }); }
    else if (s.key) parts.push({ t: "S", key: s.key, text: s.text });
    else if (s.w) { if (last && last.t === "P" && /^(Jr|Sr|II|III)$/.test(s.text)) continue; lit(/^\d/.test(s.text) ? "#" : s.text.toLowerCase()); }
    else if (last && last.t === "P" && !/[^\s.'’\-]/.test(s.text)) parts.push({ t: "L", text: " " });   // 이름 사이의 빈칸과 점
    else lit(s.text.replace(/\s+/g, " "));
  }
  const merged = [];
  for (const p of parts) {   // 이름 뒤 빈칸 다음에 또 이름이 오면 한 사람이다
    const a = merged[merged.length - 1], b = merged[merged.length - 2];
    if (p.t === "P" && a && a.t === "L" && a.text === " " && b && b.t === "P") { merged.pop(); continue; }
    merged.push(p);
  }
  return { key: merged.map(p => (p.t === "P" ? "<P>" : p.t === "S" ? "<S>" : p.text)).join("").replace(/\s+/g, " ").trim(), parts: merged };
}
function patterns(l) {
  const g = state.g;
  if (g.pt[l]) return g.pt[l];
  const m = new Map();
  for (const p of g.plays) {
    if (!p[l]) continue;
    for (const sen of sentences(tagged(p[l], l))) {
      const sk = skeleton(sen);
      if (!sk.parts.some(x => x.t === "S")) continue;
      const e = m.get(sk.key) || { n: 0, parts: sk.parts, fill: sk.parts.map(() => new Map()), ex: sen.map(s => s.text).join("").trim() };
      e.n++;
      sk.parts.forEach((pt, i) => { if (pt.t === "S" && e.fill[i]) { const f = e.fill[i].get(pt.key) || { n: 0, text: pt.text }; f.n++; e.fill[i].set(pt.key, f); } });
      m.set(sk.key, e);
    }
  }
  g.pn[l] = m;
  return (g.pt[l] = [...m.values()].filter(e => e.n >= 4).sort((a, b) => b.n - a.n).slice(0, 5));   // 네 번 넘게 나온 틀만, 다섯 개까지
}
function patternsHTML() {
  const l = state.lang, ps = patterns(l);
  if (!ps.length) return "";
  const lits = t => t.trim().split(/\s+/).filter(Boolean).map(w => (w.includes("#") ? esc(w.replace("#", "숫자")) : plainHTML({ text: w, w: /^[\wÀ-ÿ]/.test(w) }, l))).join(" ");
  return `<section class="ptns"><h3>이 경기의 문형</h3><p class="note">기록 문장은 몇 가지 틀로 쓰입니다. 가로로 읽으면 문장의 틀이고, 세로로 쌓인 말은 그 자리에 갈아 끼울 수 있는 말입니다. 옆의 숫자는 이 경기에 나온 횟수입니다. 모르는 말은 눌러 보세요.</p>
    ${ps.map((e, n) => `<div class="ptn"><div class="pn">틀 ${n + 1}. 이 경기에 ${e.n}번</div><div class="ptr" data-s="pt${l}${n}">${e.parts.map((pt, i) => {
      if (pt.t === "P") return `<span class="nm">선수</span>`;
      if (pt.t === "L") return pt.text.trim() ? `<span class="lt">${lits(pt.text)}</span>` : "";
      const fs = [...e.fill[i].entries()].sort((a, b) => b[1].n - a[1].n).slice(0, 5);
      return `<span class="colx">${fs.map(([key, f]) => `<span>${unitHTML({ key, text: f.text }, l)}${fs.length > 1 ? `<small>${f.n}</small>` : ""}</span>`).join("")}</span>`;
    }).join("")}</div><div class="gls" data-g="pt${l}${n}">${glsHTML("pt" + l + n)}</div><p class="pex" lang="${l}">${esc(e.ex)}</p></div>`).join("")}</section>`;
}

/* ---------- 2. 읽기: 1회부터 전 타석. 모르는 말만 누른다 ---------- */
const ansText = p => `${evName(p.type, p.event)}${p.runs ? `, ${p.runs}점` : ""} (${state.g.away.abbr} ${p.away} : ${p.home} ${state.g.home.abbr})`;
function paHTML(p) {
  const l = state.lang, o = other(l), cap = capText(p, l), ocap = capText(p, o);
  return `<article class="pa${p.runs ? " sc" : ""}"><span class="no"${p.runs ? ' title="점수가 난 타석"' : ""}>${p.no}</span>
    <div class="tx">${p[l] ? sent(p[l], l, l + "r" + p.abi) : `<p class="empty">이 타석의 ${LANG[l]} 기록 문장을 받지 못했습니다.</p>`}${state.both && p[o] ? sent(p[o], o, o + "r" + p.abi, "oth") : ""}</div>
    ${state.checked.has(p.abi) ? `<span class="ansv">${esc(ansText(p))}</span>` : `<button class="ans" data-ans="${p.abi}">결과 보기</button>`}
    ${cap ? `<div class="capb"><span class="capt">하이라이트 캡션. 같은 장면을 이렇게도 적습니다.</span>${sent(cap, l, l + "c" + p.abi)}${state.both && ocap ? sent(ocap, o, o + "c" + p.abi, "oth") : ""}</div>` : ""}</article>`;
}
function hendHTML(key) {
  const l = state.lang, U = LEX[l].units;
  if (!state.read.has(key)) return `<button class="btn ghost sm" data-done="${key}">이 회 다 읽었어요</button><span class="empty">누르지 않고 읽은 말은 아는 말로 셉니다.</span>`;
  const ids = [...(state.looked[key] || [])].filter(id => id.startsWith(l + ":"));
  const rows = ids.map(id => {
    const u = U[id.slice(3)], st = state.rv[id], ko = u.ko ? fullKo(u.ko) : hint(u);
    return `<div class="rv"><span class="rw" lang="${l}">${esc(u.fm[0] || u.u)}</span>${!st ? `<span class="rk">뜻을 떠올려 보세요.</span><button class="btn ghost sm" data-rv="open" data-id="${esc(id)}">뜻 보기</button>`
      : st === "open" ? `<span class="rk">${esc(ko)}</span><button class="btn sm" data-rv="known" data-id="${esc(id)}">떠올렸어요</button><button class="btn ghost sm" data-rv="still" data-id="${esc(id)}">아직이에요</button>`
      : `<span class="rk">${esc(ko)}</span><span class="${st === "known" ? "done" : "kept"}">${st === "known" ? "아는 말로 옮겼습니다" : "공부할 말에 남겼습니다"}</span>`}</div>`;
  }).join("");
  return `<span class="done">읽음</span>${ids.length ? `<div class="rev"><h4>이 회에 눌러 본 말 ${ids.length}개를 다시 떠올려 봅니다</h4>${rows}</div>` : `<span class="empty">눌러 본 말 없이 읽었습니다.</span>`}`;
}
function gained() { const l = state.lang; return Math.max(0, store.known[l].size - state.base[l]); }
function renderRead() {
  const g = state.g, l = state.lang;
  $("#view").innerHTML = `<p class="lead">1회초부터 끝까지 모든 타석의 기록 문장입니다. 뜻은 가려 두었습니다. 모르는 말만 누르면 문장 아래에 뜻이 나오고 공부할 말로 적힙니다. 한 회를 다 읽었다고 누르면 누르지 않은 말은 아는 말로 셉니다.${l === "es" ? " 관사나 전치사 같은 기초 낱말도 누르면 풀이가 나옵니다." : ""}</p>
    <p class="legend"><span><b class="new">점선</b>아직 안 본 말</span><span><b class="study">굵은 밑줄</b>공부할 말</span><span><b>밑줄 없음</b>아는 말</span><span><i class="dot"></i>점수가 난 타석</span></p>`
    + g.halves.map(h => `<section class="half" id="h-${h.key}" data-h="${h.key}"><h3><span class="hn">${h.inning}회${h.top ? "초" : "말"}</span><span class="ht">${esc((h.top ? g.away : g.home).name)} 공격</span><span class="hr">${h.plays.reduce((s, p) => s + p.runs, 0) || "무"}득점</span></h3>
      ${h.plays.map(paHTML).join("")}<div class="hend" id="e-${h.key}">${hendHTML(h.key)}</div></section>`).join("")
    + `<div class="next"><p>마지막 타석까지 왔습니다. 이 경기의 문장으로 만든 문제를 풀어 보세요.</p><button class="btn" data-tab="quiz">문제 풀기</button></div>`;
}
function doneHalf(key) {   // 이 회에서 누르지 않은 말은 아는 말로
  const l = state.lang;
  for (const p of state.g.plays) if (p.half === key) for (const text of [p[l], capText(p, l)]) if (text)
    for (const s of tagged(text, l)) if (s.key && !store.study[l].has(s.key)) store.known[l].add(s.key);
  state.read.add(key);
  store.read = [...store.read.filter(x => x[0] !== state.pk), [state.pk, [...state.read]]].slice(-40);   // 최근 마흔 경기까지만 기억한다
  saveStore();
  const sec = $("#h-" + key);
  if (sec) { $$(".u", sec).forEach(restyle); $("#e-" + key).innerHTML = hendHTML(key); }
  renderHead();
}
function restyle(n) {   // 표현 하나의 표시를 지금 기록에 맞춘다
  const [l, key] = split(n.dataset.id);
  n.classList.remove("new", "known", "study"); n.classList.add(statusOf(l, key));
  n.classList.toggle("sel", state.sel === n.dataset.id);
}
function select(id, sheet) {
  const old = state.sel;
  showCard(id, sheet);
  $$(".u").forEach(n => { if (n.dataset.id === id || n.dataset.id === old) restyle(n); });
}
function lookup(el) {   // 표현을 눌렀다: 그 자리에 뜻을 보이고, 공부할 말로 적고, 카드를 연다
  const id = el.dataset.id, [l, key] = split(id), free = !!el.closest("[data-free]");
  const strip = addGloss(el, { id, w: el.textContent, o: el.dataset.o === "1" });
  if (!free) {
    markStudy(l, key); saveStore();
    const sec = el.closest(".half");
    if (sec) { const hk = sec.dataset.h; (state.looked[hk] || (state.looked[hk] = new Set())).add(id); delete state.rv[id]; if (state.read.has(hk)) $("#e-" + hk).innerHTML = hendHTML(hk); }
  }
  select(id, !strip || !narrow());   // 좁은 화면에서는 뜻풀이 줄이 먼저고, 카드는 그 줄을 누르면 열린다
  renderHead();
}

/* ---------- 3. 문제: 공부할 말부터 묻는다. 맞히면 아는 말, 틀리면 공부할 말 ----------
   세 가지로 묻는다. 빈칸에 넣을 말 고르기(같은 자리에 올 수 있는 말 가운데 고른다), 뜻 고르기, 순서 맞추기(말을 이어 문장의 틀을 만든다) */
function rng(seed) { let x = seed % 2147483647 || 7; return () => (x = x * 48271 % 2147483647) / 2147483647; }
function atoms(segs) {   // 문장을 덩이로 쪼갠다. 이름은 한 덩이, 이름 앞의 자리 이름(first baseman, jardinero derecho)도 이름과 한 덩이, 문장부호는 앞뒤 낱말에 붙인다
  const out = []; let pre = "", glue = false;
  for (const s of segs) {
    let last = out[out.length - 1];
    if (!(s.key || s.w)) {
      const t = s.text;
      if (!/\s/.test(t)) { if (last) { last.text += t; glue = true; } else pre += t; continue; }
      if (last) last.text += t.slice(0, t.search(/\s/));
      pre = t.slice(t.search(/\s(?!.*\s)/) + 1); glue = false; continue;
    }
    const text = pre + s.text; pre = "";
    if (last && glue) { last.text += text; last.tail = last.tail && !!s.name; last.pure = last.pure && !!s.name; last.nm = last.nm || !!s.name; last.cls = null; glue = false; continue; }
    if (s.name && last && last.tail) { last.text += " " + text; continue; }
    if (s.name) {
      let t = text, pure = true;
      while (out.length > 1 && (last = out[out.length - 1]).cls && last.cls !== "V" && !/[,;:)]$/.test(last.text)) { t = out.pop().text + " " + t; pure = false; }
      out.push({ text: t, tail: true, pure, nm: true, cls: null });
      continue;
    }
    out.push({ text, tail: false, pure: false, nm: false, cls: s.key ? s.key.slice(-1) : null });
  }
  if (out.length) out[out.length - 1].text = out[out.length - 1].text.replace(/[.!?]+$/, "");
  return out;
}
function orderItems(l, rand) {   // 타자 말고 이름이 하나까지만 나오는 문장을 고른다. 야수가 둘이면 누가 누구에게 던졌는지로 답이 갈려서다
  const c = [];
  for (const p of state.g.plays) {
    if (!p[l]) continue;
    const sen = sentences(tagged(p[l], l))[0];
    if (!sen) continue;
    const at = atoms(sen);
    if (at.length < 4 || at.length > 9 || !at[0].pure || at.filter(a => a.nm).length > 2) continue;
    c.push({ p, at: at.map(a => a.text), key: skeleton(sen).key, x: rand() });
  }
  c.sort((a, b) => a.x - b.x);
  patterns(l);
  const out = [], seen = new Set();
  for (const it of c) {
    if (seen.has(it.key) || seen.has(it.p.type)) continue;
    seen.add(it.key); seen.add(it.p.type);
    let order = it.at.map((_, i) => i);
    for (let t = 0; t < 8 && order.every((v, i) => v === i); t++) order = order.map(i => [rand(), i]).sort((a, b) => a[0] - b[0]).map(x => x[1]);
    out.push({ type: "order", p: it.p, at: it.at, order, picked: [], done: null, n: (state.g.pn[l].get(it.key) || {}).n || 1 });
    if (out.length === 2) break;
  }
  return out;
}
function buildQuiz() {
  const l = state.lang, g = state.g, U = LEX[l].units, rand = rng(g.pk * (l === "es" ? 3 : 1) + store.study[l].size * 31 + store.known[l].size);
  const occ = new Map();
  for (const [k, e] of gameUnits(l)) if (U[k].ko && e.fit.length) occ.set(k, e.fit);
  const rank = { study: 0, new: 1, known: 2 }, pos = k => /(baseman|fielder|shortstop|catcher|pitcher)\|/.test(k);
  // 공부할 말이 먼저. 꾸미는 말은 문맥에 따라 뜻이 달라져서, 공부할 말에 든 것만 묻는다.
  // 그다음은 영어(중급)는 두 글을 통틀어 드문 말부터, 스페인어(입문)는 흔한 말부터. 공부할 말이 아니면 같은 종류가 몰리지 않게 둘까지만, 수비 위치는 하나만 낸다
  const cand = [...occ.keys()].filter(k => U[k].c !== "M" || statusOf(l, k) === "study").map(k => ({ k, r: rank[statusOf(l, k)], f: U[k].f + (U[k].fo || 0), x: rand() }))
    .sort((a, b) => a.r - b.r || (l === "en" ? a.f - b.f : b.f - a.f) || a.x - b.x);
  const keys = [], cap = new Map(); let npos = 0;
  for (const c of cand) {
    if (keys.length === 8) break;
    if (c.r > 0) {
      const u = U[c.k], bucket = u.c + (u.ev[0] ? u.ev[0][0] : "");
      if ((cap.get(bucket) || 0) >= 2 || (pos(c.k) && npos >= 1)) continue;
      cap.set(bucket, (cap.get(bucket) || 0) + 1); if (pos(c.k)) npos++;
    }
    keys.push(c);
  }
  const pool = Object.entries(U).filter(([, v]) => v.ko && v.t <= 2 && v.fm[0]);
  const third = l === "en" ? /s$/ : /[ae]$/, qs = [];
  keys.forEach(({ k }, n) => {
    const list = occ.get(k), o = list[Math.floor(rand() * list.length)], u = U[k], seg = o.segs[o.i];
    const kind = u.ev.length ? KIND[u.ev[0][0]] : null, mine = shortKo(u.ko, seg.obj);
    const cands = pool.filter(([kk, v]) => kk !== k && v.c === u.c && shortKo(v.ko, false) !== mine && !(u.alt || []).includes(kk) && (!kind || !v.ev.length || KIND[v.ev[0][0]] !== kind));
    if (cands.length < 3) return;
    const acr = /^[A-Z0-9]{2,5}$/.test(seg.text);   // NL, RBI 같은 약어는 꼴을 고르게 하면 답이 드러나므로 뜻만 묻는다
    const type = acr || n % 2 ? "meaning" : "form", answer = type === "form" ? seg.text : mine;
    const up = /^[A-ZÀ-Þ][a-zß-ÿ]/.test(seg.text), fit = s => (up ? s.charAt(0).toUpperCase() + s.slice(1) : s);   // 문장 첫머리면 보기도 대문자로
    const formOf = v => fit((third.test(seg.text.split(" ")[0]) && v.fm.find(f => third.test(f.split(" ")[0]))) || v.fm[0]);
    const ds = [];
    for (let t = 0; ds.length < 3 && t < 200; t++) {
      const v = cands[Math.floor(rand() * cands.length)][1], d = type === "form" ? formOf(v) : shortKo(v.ko, false);
      if (d && !ds.includes(d) && d.toLowerCase() !== answer.toLowerCase()) ds.push(d);
    }
    if (ds.length < 3) return;
    qs.push({ key: k, type, o, answer, cue: mine, was: statusOf(l, k), picked: null, opts: [answer, ...ds].map(x => [rand(), x]).sort((a, b) => a[0] - b[0]).map(x => x[1]) });
  });
  const ord = orderItems(l, rand);   // 다섯째와 마지막 문제는 순서 맞추기
  if (ord[0]) qs.splice(Math.min(4, qs.length), 0, ord[0]);
  if (ord[1]) qs.push(ord[1]);
  state.quiz = { lang: l, qs };
}
const qDone = q => (q.type === "order" ? q.done !== null : q.picked !== null);
const qRight = q => (q.type === "order" ? q.done === true : q.picked === q.answer);
function orderHTML(q, n) {
  const l = state.lang, done = q.done !== null, used = new Set(q.picked), p = q.p;
  const chunk = (i, where) => `<button class="chunk${where === "pool" && used.has(i) ? " used" : ""}" lang="${l}" data-oq="${n}" data-oi="${i}" data-ow="${where}"${done || (where === "pool" && used.has(i)) ? " disabled" : ""}>${esc(q.at[i])}</button>`;
  return `<div class="q"><div class="meta">${n + 1}번. ${p.inning}회${p.top ? "초" : "말"} 기록 문장. 순서 맞추기</div>
    <p class="cue">말을 순서대로 눌러 이 타석의 기록 문장을 만드세요. 타자는 <b>${esc(q.at[0])}</b>, 결과는 <b>${esc(evName(p.type, p.event))}</b>입니다.</p>
    <div class="built${done ? (q.done ? " ok" : " no") : ""}">${q.picked.map(i => chunk(i, "built")).join("") || `<span class="ph">누른 말이 여기에 놓입니다. 놓인 말을 다시 누르면 빠집니다.</span>`}</div>
    ${done ? `<div class="fb ${q.done ? "ok" : "no"}"><b>${q.done ? "맞았습니다." : "순서가 다릅니다."}</b> <span lang="${l}">${esc(q.at.join(" "))}.</span>${q.n > 1 ? ` 같은 틀의 문장이 이 경기에 ${q.n}번 나옵니다.` : ""}</div>`
      : `<div class="pool">${q.order.map(i => chunk(i, "pool")).join("")}</div>`}</div>`;
}
function renderQuiz() {
  const l = state.lang;
  if (!state.quiz || state.quiz.lang !== l) buildQuiz();
  const qs = state.quiz.qs, U = LEX[l].units;
  if (!qs.length) { $("#view").innerHTML = `<p class="note">이 경기의 문장으로는 문제를 만들지 못했습니다.</p>`; return; }
  const done = qs.filter(qDone).length, right = qs.filter(qRight).length;
  $("#view").innerHTML = `<p class="lead">이 경기의 문장으로 만든 문제입니다. 공부할 말부터 나옵니다. 낱말 문제는 맞히면 아는 말로, 틀리면 공부할 말로 옮깁니다. 순서 맞추기는 문장의 틀을 익히는 문제입니다.</p>` + qs.map((q, n) => {
    if (q.type === "order") return orderHTML(q, n);
    const u = U[q.key], ans = q.picked !== null;
    const body = q.o.segs.map((x, i) => (i !== q.o.i ? esc(x.text) : !ans && q.type === "form" ? `<span class="blank">?</span>` : `<mark class="tgt">${esc(x.text)}</mark>`)).join("");
    const opts = q.opts.map(o => `<button class="opt${q.type === "meaning" ? " ko" : ""}${ans && o === q.answer ? " right" : ""}${q.picked === o && o !== q.answer ? " wrong" : ""}" data-q="${n}" data-o="${esc(o)}"${ans ? " disabled" : ""}>${esc(o)}</button>`).join("");
    const alts = (u.ev.length && u.ev[0][1] >= 0.5 ? u.alt || [] : []).map(k => (U[k] || {}).fm).filter(Boolean).map(f => f[0]).slice(0, 4);
    const fb = !ans ? "" : `<div class="fb ${q.picked === q.answer ? "ok" : "no"}"><b>${q.picked === q.answer ? "맞았습니다. 아는 말로 옮겼습니다." : `정답은 ${esc(q.answer)}입니다. 공부할 말에 넣었습니다.`}</b> <span lang="${l}">${esc(u.fm[0] || u.u)}</span>: ${esc(fullKo(u.ko))}.${alts.length ? ` 같은 장면에 쓰는 다른 말: <span lang="${l}">${alts.map(esc).join(", ")}</span>.` : ""}
      <button class="lk" data-chip="${esc(l + ":" + q.key)}">쓰임 더 보기</button></div>`;
    return `<div class="q"><div class="meta">${n + 1}번. ${q.o.p.inning}회${q.o.p.top ? "초" : "말"} ${q.o.kind}${q.was === "study" ? ". 공부할 말" : ""}</div><p class="sent" lang="${l}">${body}</p>
      <p class="cue">${q.type === "form" ? `빈칸에 들어갈 말을 고르세요. 뜻: <b>${esc(q.cue)}</b>` : "칠한 말의 뜻을 고르세요."}</p><div class="opts">${opts}</div>${fb}</div>`;
  }).join("") + (done < qs.length ? `<p class="note">${qs.length}문제 가운데 ${done}문제를 풀었습니다.</p>`
    : `<div class="next"><p>${qs.length}문제 가운데 ${right}문제를 맞혔습니다. 이 경기에서 아는 말이 ${gained()}개 늘었고, 공부할 말은 모두 ${store.study[l].size}개입니다. 틀린 말은 다음 경기의 예습에 먼저 나옵니다.</p>
      <div class="row2"><button class="btn" data-tab="recap">기사 읽기</button><button class="btn ghost" data-quiz="again">다른 문제 풀기</button></div></div>`);
}

/* ---------- 4. 기사: 익힌 말이 다른 글에도 나오는 것을 본다 ---------- */
function renderRecap() {
  const l = state.lang, r = state.g.recap[l], o = other(l), r2 = state.both && state.g.recap[o];
  if (!r) { $("#view").innerHTML = `<p class="note">이 경기에는 ${LANG[l]} 기사가 없습니다.</p>`; return; }
  const keys = new Set();
  [r.headline, ...r.ps].forEach(t => tagged(t, l).forEach(s => { if (s.key) keys.add(s.key); }));
  const k = [...keys].filter(x => statusOf(l, x) === "known").length;
  const art = (a, ll) => `<h2 class="sent" lang="${ll}" data-s="${ll}h">${wordsHTML(a.headline, ll)}</h2><div class="gls" data-g="${ll}h">${glsHTML(ll + "h")}</div><div class="by">${esc(a.by)}</div>${a.ps.map((p, i) => sent(p, ll, ll + "p" + i)).join("")}`;
  $("#view").innerHTML = `<div class="recap"><p class="lead">같은 경기를 다룬 기사입니다. 기록 문장과 캡션에서 익힌 말이 여기에도 나오는지 보세요. 이 기사에 나오는 표현 ${keys.size}개 가운데 ${k}개가 아는 말입니다. 모르는 말은 여기서도 누를 수 있습니다.</p>${art(r, l)}${r2 ? `<hr>${art(r2, o)}` : ""}</div>`;
}

/* ---------- 표현 카드: 뜻, 쓰이는 장면, 말의 자리(두 축) ---------- */
function showCard(id, sheet = true) {
  const [l, key] = split(id), u = LEX[l].units[key], o = other(l), el = $("#card");
  if (!u) return;
  state.sel = id;
  const st = statusOf(l, key);
  const chip = (ll, k, extra = "") => { const x = LEX[ll].units[k]; return x ? `<button class="chip" lang="${ll}" data-chip="${esc(ll + ":" + k)}">${esc(x.fm[0] || x.u)}${extra}</button>` : ""; };
  const evs = (u.ev || []).map(([e, p]) => `<div class="barx"><span>${esc(evName(e))}</span><i style="width:${Math.round(p * 100)}%"></i><b>${Math.round(p * 100)}%</b></div>`).join("");
  const sg = x => (x > 0 ? "+" : "") + x;
  const nu = !u.num ? "" : Object.entries(u.num).map(([e, [n, sp, an, di, dsp, dan, ddi]]) =>
    `<p class="nu">이 말로 적힌 ${esc(evName(e))} ${n.toLocaleString()}개의 타구는 평균 ${sp} mph, 발사각 ${an}°, 비거리 ${di} ft입니다. 같은 사건 전체 평균과의 차이는 속도 ${sg(dsp)}, 발사각 ${sg(dan)}°, 비거리 ${sg(ddi)} ft.</p>`).join("");
  const e0 = u.ev[0] && u.ev[0][0];
  const seen = new Set([(u.fm[0] || u.u).toLowerCase()]), once = k => { const x = LEX[l].units[k], t = x && (x.fm[0] || x.u).toLowerCase(); if (!x || seen.has(t)) return false; seen.add(t); return true; };
  const alt = (u.alt || []).filter(once).slice(0, 6).map(k => { const x = LEX[l].units[k]; return chip(l, k, x.num && x.num[e0] ? `<small>${x.num[e0][3]} ft</small>` : ""); });
  const co = (u.co || []).filter(once).slice(0, 6).map(k => chip(l, k));
  const cw = `<b class="cw" lang="${l}">${esc(u.fm[0] || u.u)}</b>`;
  const place = !alt.length && !co.length ? "" : alt.length
    ? `<h3>말의 자리</h3><div class="cross"><div class="up rowc">${alt.slice(0, 3).join("")}</div><div class="lf col">${co.slice(0, 3).join("")}</div>${cw}<div class="rt col">${co.slice(3, 6).join("")}</div><div class="dn rowc">${alt.slice(3, 6).join("")}</div></div>
      <p class="axl"><span>세로: 같은 장면에 바꿔 쓸 말</span><span>가로: 한 문장에 같이 쓰는 말</span></p>`
    : `<h3>말의 자리</h3><div class="cross flat"><div class="lf col">${co.slice(0, 3).join("")}</div>${cw}<div class="rt col">${co.slice(3, 6).join("")}</div></div>
      <p class="axl"><span>가로: 한 문장에 같이 쓰는 말${l === "es" ? ". 바꿔 쓸 말은 스페인어 기록 문장 분석을 마치면 채워집니다" : ""}</span></p>`;
  const xs = !state.both ? "" : [...(u.x || [])].sort((a, b) => b[1] - a[1]).map(([k, p]) => chip(o, k, `<small>${Math.round(p * 100)}%</small>`)).join("");
  el.classList.remove("idle");
  el.classList.toggle("show", sheet || el.classList.contains("show"));
  el.innerHTML = `<button class="close" data-close="1">닫기</button><h2 lang="${l}">${esc(u.u)}</h2>
    <div class="tagline"><span class="pill l">${LANG[l]}</span><span class="pill">${CLS[u.c] || ""}</span>${u.g ? `<span>${esc(LEX.groups[u.g] || "")}</span>` : ""}<span class="pill ${st}">${st === "known" ? "아는 말" : st === "study" ? "공부할 말" : "아직 안 본 말"}</span></div>
    <p class="ko">${u.ko ? esc(fullKo(u.ko)) : `<span class="empty">${esc(hint(u))}</span>`}</p>
    ${baseLine(l, u)}
    <p class="freq">${TIER[u.t]}. 캡션에 ${u.f.toLocaleString()}번${u.fo ? `, 기록 문장에 ${u.fo.toLocaleString()}번` : ""} 나왔습니다.</p>
    ${evs ? `<h3>어떤 장면에 쓰나</h3>${evs}` : ""}${nu ? `<h3>실제 타구로 본 뉘앙스</h3>${nu}` : ""}${place}
    ${xs ? `<h3>${o === "es" ? "스페인어로는" : "영어로는"}</h3><div class="chips">${xs}</div>` : ""}
    <div class="row2 marks"><button class="btn sm${st === "known" ? "" : " ghost"}" data-mark="known" data-id="${esc(id)}">아는 말로</button><button class="btn sm${st === "study" ? "" : " ghost"}" data-mark="study" data-id="${esc(id)}">공부할 말로</button></div>`;
  el.scrollTop = 0;
}
function idleCard() {   // 고른 말이 없을 때는 공부할 말 목록을 보여 준다
  const el = $("#card"), l = state.lang;
  state.sel = null;
  el.classList.add("idle"); el.classList.remove("show");
  if (!l) { el.innerHTML = `<p class="empty">문장에서 모르는 말을 누르면 뜻과 쓰임이 여기에 나옵니다.</p>`; return; }
  const U = LEX[l].units, st = [...store.study[l]].filter(k => U[k]).reverse();
  el.innerHTML = `<h3 class="nb">공부할 말 ${st.length}개</h3>
    ${st.length ? `<div class="chips">${st.slice(0, 60).map(k => `<button class="chip" lang="${l}" data-chip="${esc(l + ":" + k)}">${esc(U[k].fm[0] || U[k].u)}</button>`).join("")}</div>${st.length > 60 ? `<p class="empty">최근 60개만 보입니다.</p>` : ""}`
      : `<p class="empty">문장에서 모르는 말을 누르면 여기에 모입니다. 다음 경기의 예습과 문제에 먼저 나옵니다.</p>`}
    <p class="empty">아는 말은 ${store.known[l].size}개입니다. 공부 기록은 이 브라우저에만 남습니다.</p>`;
}

/* ---------- 맞대결: 캡션에서 뽑은 '누가 누구를 무엇했다'. 자료는 relations.js (이름, 동사, 횟수, 타석 번호) ---------- */
function loadRel() {
  if (window.RELATIONS || state.relLoading || state.relMissing) return;
  state.relLoading = true;
  const s = document.createElement("script");
  s.src = REL_SRC;
  s.onload = () => { state.relLoading = false; if (!window.RELATIONS) state.relMissing = true; if (state.tab === "rel") render(); };
  s.onerror = () => { state.relLoading = false; state.relMissing = true; if (state.tab === "rel") render(); };
  document.head.appendChild(s);
}
function relDefault(R) {   // 보고 있던 경기에 나온 선수가 있으면 그 선수부터
  for (const p of (state.g ? state.g.plays : [])) for (const id of [p.pid, p.bid]) if (id && R.p[id]) return String(id);
  return QUICK.find(id => R.p[id]) || Object.keys(R.p)[0];
}
function relVerb(vi) {   // [보여 줄 꼴, 언어, 사전 열쇠]. 스페인어로 공부할 때는 스페인어 캡션이 쓰는 꼴로 바꾼다
  const [label, shown, key] = window.RELATIONS.verbs[vi];
  if (state.lang === "es") {
    const s = label.endsWith(")") ? "conecta ante" : ES_REL[label];
    if (s) { const w = s.split(" ").find(x => x !== "le"), k = (LEX.es.forms[w] || []).find(x => x.endsWith("|V")); return [s, "es", k || null]; }
  }
  return [label.endsWith(")") ? shown.replace(/ (off|against)$/, " … $1") : shown, "en", key];
}
function relRowHTML(dir, k, x) {
  const R = window.RELATIONS, [oid, vi, n] = x, fam = R.fam[R.verbs[vi][3]] || "", name = R.names[oid] || "?", [shown, vl, key] = relVerb(vi);
  const who = R.p[oid] ? `<button class="pl" data-rel="${esc(oid)}">${esc(name)}</button>` : `<span>${esc(name)}</span>`;
  const verb = key && LEX[vl].units[key] ? unitHTML({ key, text: shown, obj: true }, vl, dir + k) : `<button class="pl" data-e="${dir}${k}">${esc(shown)}</button>`;
  return `<li${state.relEdge === dir + k ? ' class="sel"' : ""}>${dir === "i" ? who + " " + verb : verb + " " + who}<small>${esc(fam)} ${n}번</small></li>`;
}
function renderRel() {
  const v = $("#view"), R = window.RELATIONS;
  if (!R) {
    v.innerHTML = state.relMissing ? `<p class="note">맞대결 자료(relations.js)를 찾지 못했습니다. index.html과 같은 폴더에 두세요.</p>` : `<p class="note">맞대결 자료를 불러오는 중…</p>`;
    loadRel();
    return;
  }
  let miss = "";
  if (state.relId && !R.p[state.relId]) {
    miss = `<div class="err">${esc(R.names[state.relId] || state.relName || "이 선수")}는 다른 선수와 함께 나온 캡션이 적어서 가운데에 세울 수 없습니다. 다른 선수를 골라 보세요.</div>`;
    state.relId = null;
  }
  if (!state.relId) state.relId = relDefault(R);
  const id = String(state.relId), p = R.p[id];
  const opts = state.relOpts || (state.relOpts = Object.keys(R.p).sort((a, b) => (R.p[b].no + R.p[b].ni) - (R.p[a].no + R.p[a].ni)).map(k => `<option value="${esc(R.names[k])}">`).join(""));
  const quick = QUICK.filter(k => R.p[k]).map(k => `<button class="quick" data-rel="${k}">${esc(R.names[k])}</button>`).join("");
  const top = list => { const m = new Map(); list.forEach(([vi, n]) => { const s = relVerb(vi)[0]; m.set(s, (m.get(s) || 0) + n); }); return [...m.entries()].sort((a, b) => b[1] - a[1]).map(([s, n]) => `${esc(s)} ${n}`).join(", "); };
  const side = (dir, cls, list, n, sum, head) => `<div class="col ${cls}"><p class="sidehead"><b>${head} ${n}건</b>${sum ? `<br>${sum}` : ""}</p>${list.length
    ? `<ol class="side ${cls}">${list.map((x, k) => relRowHTML(dir, k, x)).join("")}</ol>` : `<p class="empty">캡션에 나온 장면이 없습니다.</p>`}</div>`;
  v.innerHTML = `<div class="rel" data-free="1">
    <p class="lead">캡션에서 한 선수가 다른 선수에게 한 일을 화살표로 이었습니다. 화살표가 출발하는 쪽이 문장의 주어입니다. 이름을 누르면 그 선수로 옮겨 가고, 동사를 누르면 그 장면을 적은 문장이 아래에 나옵니다. 여기서 누른 말은 공부 기록에 넣지 않습니다.</p>
    ${miss}
    <div class="relpick"><label for="relq">선수</label><input id="relq" list="relnames" placeholder="영문 이름으로 찾기" autocomplete="off"><datalist id="relnames">${opts}</datalist>${quick}</div>
    <div class="ego" id="ego"><svg class="wires" aria-hidden="true"></svg>
      ${side("i", "in", p.ie, p.ni, top(p.i), "이 선수에게 한 일")}
      <div class="me"><strong>${esc(R.names[id])}</strong><small>캡션 ${p.no + p.ni}건${p.ie.length + p.oe.length < p.no + p.ni ? ` 가운데 ${p.ie.length + p.oe.length}건` : ""}</small></div>
      ${side("o", "out", p.oe, p.no, top(p.o), "이 선수가 한 일")}
    </div>
    <div id="relsent"></div></div>`;
  const seek = e => {   // 목록에서 고르면 바로, 직접 쳤으면 입력을 마쳤을 때 옮겨 간다. 그리는 일은 이벤트가 끝난 뒤로 미룬다
    const q = e.target.value.trim().toLowerCase(), k = Object.keys(R.p).find(k => R.names[k].toLowerCase() === q);
    if (k) { if (k !== String(state.relId)) { state.relId = k; state.relEdge = null; setTimeout(render, 0); } }
    else if (q && e.type === "change") { e.target.value = ""; e.target.placeholder = "목록에 있는 이름을 골라 주세요"; }
  };
  $("#relq").addEventListener("input", seek);
  $("#relq").addEventListener("change", seek);
  drawWires();
  if (state.relEdge) showRelSent();
}
function drawWires() {   // 줄의 자리를 재서 곡선을 그린다. 화면이 좁으면 줄 없이 목록으로만 보여 준다
  const ego = $("#ego");
  if (!ego) return;
  ego.classList.toggle("narrow", ego.clientWidth < 640);
  const svg = $(".wires", ego);
  if (ego.classList.contains("narrow")) { svg.innerHTML = ""; return; }
  const box = ego.getBoundingClientRect(), me = $(".me", ego).getBoundingClientRect(), f = x => x.toFixed(1);
  svg.setAttribute("width", box.width); svg.setAttribute("height", box.height);
  const cy = me.top - box.top + me.height / 2, xl = me.left - box.left - 7, xr = me.right - box.left + 7, out = [];
  const fan = (i, n) => Math.max(8 - me.height / 2, Math.min(me.height / 2 - 8, (i - (n - 1) / 2) * 7));
  const ins = $$(".side.in li", ego), outs = $$(".side.out li", ego);
  const wire = (li, d) => out.push(`<path class="wr${li.classList.contains("sel") ? " sel" : ""}" d="${d}" marker-end="url(#${li.classList.contains("sel") ? "arrs" : "arr"})"/>`);
  ins.forEach((li, i) => { const r = li.getBoundingClientRect(), x = r.right - box.left + 6, y = r.top - box.top + 16, ty = cy + fan(i, ins.length);
    wire(li, `M${f(x)},${f(y)} C${f(x + 40)},${f(y)} ${f(xl - 44)},${f(ty)} ${f(xl)},${f(ty)}`); });
  outs.forEach((li, i) => { const r = li.getBoundingClientRect(), x = r.left - box.left - 8, y = r.top - box.top + 16, sy = cy + fan(i, outs.length);
    wire(li, `M${f(xr)},${f(sy)} C${f(xr + 44)},${f(sy)} ${f(x - 40)},${f(y)} ${f(x)},${f(y)}`); });
  const mk = (id, color) => `<marker id="${id}" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="7" markerHeight="7" orient="auto"><path d="M0,0 L8,4 L0,8 z" fill="${color}"/></marker>`;
  svg.innerHTML = `<defs>${mk("arr", "#829088")}${mk("arrs", "#16231c")}</defs>` + out.join("");
}
async function gameBits(pk) {   // 한 경기의 기록 문장(영어, 스페인어), 캡션, 날짜. 한 번 받은 경기는 다시 받지 않는다
  if (state.relCache[pk]) return state.relCache[pk];
  const [en, es, cEn, cEs, sch] = await Promise.all([
    getJSON(`/v1/game/${pk}/playByPlay?fields=${PBF}`),
    getJSON(`/v1/game/${pk}/playByPlay?language=es&fields=${PBF}`).catch(() => ({})),
    getJSON(`/v1/game/${pk}/content`),
    getJSON(`/v1/game/${pk}/content?language=es`).catch(() => ({})),
    getJSON(`/v1/schedule?sportId=1&gamePk=${pk}`).catch(() => ({}))]);
  const plays = d => { const m = {}; (d.allPlays || []).forEach(p => { const a = p.about || {}; m[p.atBatIndex ?? a.atBatIndex] = { text: (p.result || {}).description || "", inning: a.inning, top: a.isTopInning ?? (a.halfInning === "top") }; }); return m; };
  const items = c => (((c.highlights || {}).highlights || {}).items) || [];
  const esItem = {}; items(cEs).forEach(x => { esItem[x.id] = x; });
  const cap = {};
  items(cEn).forEach(x => {
    if (!x.guid) return;
    const y = esItem[x.id] || {}, c = { tEn: (x.title || "").trim(), dEn: (x.description || "").trim(), tEs: (y.title || "").trim(), dEs: (y.description || "").trim() };
    if (c.tEs === c.tEn) c.tEs = ""; if (c.dEs === c.dEn) c.dEs = "";
    cap[x.guid.slice(0, 8)] = c;
  });
  const day = (sch.dates || [])[0] || {}, g = (day.games || [])[0] || {}, team = side => (((g.teams || {})[side] || {}).team || {}).name || "";
  return (state.relCache[pk] = { en: plays(en), es: plays(es), cap, date: day.date || "", away: team("away"), home: team("home") });
}
async function showRelSent() {
  const R = window.RELATIONS, id = String(state.relId), key = state.relEdge;
  const x = key && R.p[id] && R.p[id][key[0] === "i" ? "ie" : "oe"][+key.slice(1)];
  if (!x || !$("#relsent")) return;
  const [oid, vi, n, pk, abi, g8] = x, s = key[0] === "i" ? oid : id, o = key[0] === "i" ? id : oid, vb = R.verbs[vi];
  if (!state.relCache[pk]) $("#relsent").innerHTML = `<p class="note">이 장면을 적은 문장을 받아 오는 중…</p>`;
  try {
    const b = await gameBits(pk);
    if (state.relEdge !== key || String(state.relId) !== id || !$("#relsent")) return;
    addNames(R.names[s]); addNames(R.names[o]); TAGC.clear();
    const c = b.cap[g8] || {}, row = (kind, l, text, tag) => (text ? `<div class="rrow"><span class="kind">${kind}</span><div>${sent(text, l, "x" + l + tag)}</div></div>` : "");
    const one = l => row("기록 문장", l, (b[l][abi] || {}).text, "r") + row("캡션", l, l === "en" ? c.tEn : c.tEs, "t") + ((l === "en" ? c.dEn : c.dEs) && (l === "en" ? c.dEn !== c.tEn : c.dEs !== c.tEs) ? row("", l, l === "en" ? c.dEn : c.dEs, "d") : "");
    ["en", "es"].forEach(l => ["r", "t", "d"].forEach(t => { delete state.gl["x" + l + t]; }));
    const body = one(state.lang) + (state.both ? one(other(state.lang)) : ""), pl = b.en[abi] || {};
    $("#relsent").innerHTML = `<div class="relsent"><h4>${esc(R.names[s])} → ${esc(R.names[o])}</h4>
      <p class="when">${esc(R.fam[vb[3]])}${n > 1 ? `, ${n}번 가운데 가장 최근 장면` : ""}${b.date ? `, ${esc(b.date)}` : ""}${pl.inning ? ` ${pl.inning}회${pl.top ? "초" : "말"}` : ""}${b.away ? `, ${esc(b.away)} 대 ${esc(b.home)}` : ""}.
        기록 문장과 캡션에서 주어가 누구인지 견줘 보세요. 화살표가 출발하는 선수가 캡션의 주어입니다.</p>
      ${body || `<p class="note">이 장면의 문장을 찾지 못했습니다.</p>`}</div>`;
  } catch (e) { if ($("#relsent")) $("#relsent").innerHTML = `<div class="err">문장을 받지 못했습니다 (${esc(e.message || e)}). 인터넷 연결을 확인한 뒤 다시 눌러 보세요.</div>`; }
}

/* ---------- 이벤트 ---------- */
function setLang(l) {
  store.lang = state.lang = l; saveStore();
  state.prep = null; state.quiz = null; state.relOpts = null;
  idleCard(); render();
}
function goTab(tab, scroll) {
  state.tab = tab; render();
  if (scroll) window.scrollTo(0, Math.max(0, $("#tabs").getBoundingClientRect().top + window.scrollY - 4));
}
document.addEventListener("click", e => {
  const t = e.target.closest("[data-setlang],[data-rel],[data-e],[data-more],[data-id],[data-chip],[data-b],[data-ans],[data-done],[data-rv],[data-prep],[data-quiz],[data-q],[data-oq],[data-mark],[data-jump],[data-pk],[data-tab],[data-close]");
  if (!t) return;
  const d = t.dataset;
  if (d.setlang) setLang(d.setlang);
  else if (d.rel) { state.relId = d.rel; state.relName = t.textContent; state.relEdge = null; state.tab = "rel"; render(); }
  else if (d.rv) { const id = d.id, [l, key] = split(id); state.rv[id] = d.rv; if (d.rv === "known") { markKnown(l, key); saveStore(); }
    const sec = t.closest(".half"); if (sec) { $("#e-" + sec.dataset.h).innerHTML = hendHTML(sec.dataset.h); $$(".u", sec).forEach(restyle); } renderHead(); }
  else if (d.mark) { const id = d.id, [l, key] = split(id); (d.mark === "known" ? markKnown : markStudy)(l, key); saveStore(); select(id, true); renderHead(); }
  else if (d.e) { state.relEdge = d.e; if (d.id) showCard(d.id, true); render(); }
  else if (d.more) select(d.more, true);
  else if (d.chip) select(d.chip, true);
  else if (d.id) lookup(t);
  else if (d.b) addGloss(t, { b: d.b, w: t.textContent });
  else if (d.ans) { state.checked.add(+d.ans); const p = state.g.plays.find(x => x.abi === +d.ans); t.outerHTML = `<span class="ansv">${esc(ansText(p))}</span>`; }
  else if (d.done) doneHalf(d.done);
  else if (d.prep) prepAct(d.prep);
  else if (d.quiz) { state.quiz = null; goTab("quiz", true); }
  else if (d.oq !== undefined) { const q = state.quiz.qs[+d.oq], i = +d.oi; if (q.done !== null) return;
    if (d.ow === "pool") { if (!q.picked.includes(i)) q.picked.push(i); } else q.picked = q.picked.filter(x => x !== i);
    if (q.picked.length === q.at.length) q.done = q.picked.map(x => q.at[x]).join(" ") === q.at.join(" ");
    renderQuiz(); }
  else if (d.q !== undefined) { const q = state.quiz.qs[+d.q]; if (q.picked === null) { q.picked = d.o; (q.picked === q.answer ? markKnown : markStudy)(state.lang, q.key); saveStore(); renderHead(); renderQuiz(); } }
  else if (d.jump) { e.preventDefault(); if (state.tab !== "read") goTab("read"); const s = $("#h-" + d.jump); if (s) s.scrollIntoView({ block: "start" }); }
  else if (d.pk) loadGame(+d.pk);
  else if (d.tab) goTab(d.tab, t.classList.contains("btn"));
  else if (d.close) { const old = state.sel; idleCard(); $$(".u").forEach(n => { if (n.dataset.id === old) restyle(n); }); }
});
document.addEventListener("keydown", e => {
  const el = e.target;
  if ((e.key === "Enter" || e.key === " ") && el.matches && el.matches(".u,.b")) { e.preventDefault(); el.click(); return; }
  if (state.tab !== "prep" || e.metaKey || e.ctrlKey || e.altKey || (el.matches && el.matches("button,input,select,textarea,a,[role=button]"))) return;
  if (e.key === " ") { e.preventDefault(); prepAct("show"); } else if (e.key === "1") prepAct("k"); else if (e.key === "2") prepAct("s");
});
window.addEventListener("resize", () => { clearTimeout(state.rz); state.rz = setTimeout(drawWires, 120); });
$("#both").addEventListener("change", e => { store.both = state.both = e.target.checked; saveStore(); render(); if (state.sel) showCard(state.sel, false); });
$("#date").value = state.date;
$("#date").addEventListener("change", e => { if (e.target.value) { state.date = e.target.value; state.pk = null; state.g = null; idleCard(); render(); loadDate(); } });
idleCard();
if (!LEX) $("#msg").innerHTML = `<div class="err">표현 사전 파일(lexicon.js)을 찾지 못했습니다. index.html과 같은 폴더에 두세요.</div>`;
else { render(); loadDate(); }
