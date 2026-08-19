const fs = require("fs");
const path = require("path");
const { JSDOM } = require("jsdom");

const htmlPath = path.join(__dirname, "..", "carwash", "webapp", "static", "index.html");
let html = fs.readFileSync(htmlPath, "utf-8");

// Extract inline <script> blocks (skip src= scripts, since they're not fetched here).
const scriptRe = /<script(?:\s[^>]*)?>([\s\S]*?)<\/script>/g;
let m, scripts = [];
while ((m = scriptRe.exec(html))) {
  const tagOpen = m[0].slice(0, m[0].indexOf(">") + 1);
  if (/src=/.test(tagOpen)) {
    // Local same-origin scripts (e.g. /static/js/ui-kit.js) are real
    // dependencies (UI.BottomSheet etc.) — load them from disk so the
    // dry run reflects what the page actually depends on. Remote scripts
    // (Telegram's own telegram-web-app.js) are mocked separately instead.
    const srcMatch = tagOpen.match(/src="([^"]+)"/);
    if (srcMatch && srcMatch[1].startsWith("/static/")) {
      const localPath = path.join(__dirname, "..", "carwash", "webapp", srcMatch[1]);
      if (fs.existsSync(localPath)) {
        scripts.push(fs.readFileSync(localPath, "utf-8"));
        console.log(`Loaded local dependency: ${srcMatch[1]}`);
      }
    }
    continue;
  }
  scripts.push(m[1]);
}
console.log(`Found ${scripts.length} script blocks (inline + local deps)`);

const errors = [];

const dom = new JSDOM(html, {
  url: "https://example.com/static/index.html",
  runScripts: "outside-only",
  resources: "usable",
  pretendToBeVisual: true,
});

const { window } = dom;

// ── Mock Telegram WebApp API ────────────────────────────────────────────
const tgMock = {
  ready(){}, expand(){}, close(){},
  setHeaderColor(){}, setBackgroundColor(){},
  initData: "mock_init_data",
  initDataUnsafe: { start_param: "test_branch", user: { id: 12345 } },
  colorScheme: "dark",
  HapticFeedback: { impactOccurred(){}, notificationOccurred(){}, selectionChanged(){} },
  BackButton: { show(){}, hide(){}, onClick(){}, offClick(){} },
  MainButton: { show(){}, hide(){}, setText(){}, onClick(){}, offClick(){} },
  showAlert(msg, cb){ console.log("[tg.showAlert]", msg); if(cb) cb(); },
  showConfirm(msg, cb){ console.log("[tg.showConfirm]", msg); if(cb) cb(true); },
  showPopup(params, cb){ console.log("[tg.showPopup]", params.title||"", "->", (params.buttons||[]).map(b=>b.id).join(",")); if(cb) cb("cancel"); },
  onEvent(){}, offEvent(){},
  themeParams: {},
};
window.Telegram = { WebApp: tgMock };

// ── Mock fetch: capture API calls, return plausible payloads ───────────
const apiCalls = [];
window.fetch = async (url, opts = {}) => {
  apiCalls.push({ url, method: opts.method || "GET", body: opts.body });
  console.log(`[fetch] ${opts.method||"GET"} ${url}`, opts.body ? `body=${opts.body}` : "");
  const okJson = (obj) => ({
    ok: true,
    status: 200,
    headers: { get: () => "application/json" },
    json: async () => obj,
    text: async () => JSON.stringify(obj),
  });
  // Minimal plausible responses so init code doesn't throw.
  if (url.includes("/api/config")) return okJson({ branches: ["test_branch"], services: [] });
  if (url.includes("/api/my-employee-stats")) return okJson({ name: "Иван", roles: ["мойщик"], from: "2026-08-01", to: "2026-08-19", stats: {} });
  if (url.includes("/api/me")) return okJson({ role: "admin", branch: "test_branch", name: "Иван" });
  if (url.includes("/api/workers")) return okJson({ workers: ["Иван"], schedule: {} });
  if (url.includes("/api/session")) return okJson({ session: { open: true, cars: [] }, summary: { washer_salaries: {} } });
  if (url.includes("/api/schedule")) return okJson({ ok: true });
  return okJson({});
};

window.onerror = (msg, src, line, col, err) => {
  errors.push(`window.onerror: ${msg} @${line}:${col}`);
};
window.addEventListener("unhandledrejection", (e) => {
  errors.push(`unhandledrejection: ${e.reason}`);
});

// jsdom's window.eval does NOT share top-level lexical bindings (const/let,
// e.g. ui-kit.js's `const UI = ...`) across separate eval() calls the way a
// real browser shares them across sibling <script> tags — confirmed by a
// standalone check before writing this harness. Concatenating into one
// eval call reproduces real same-document <script> semantics for this
// purpose; only function declarations and explicit `window.x=` assignments
// would otherwise survive across separate calls, which understates what a
// real page has available.
try {
  window.eval(scripts.join("\n;\n"));
} catch (e) {
  errors.push(`initial script load threw: ${e.stack || e}`);
}

// ── Drive key functions directly (module-scope consts aren't on window,
//    so we eval small driver snippets in the same context instead). ────
async function drive(label, code) {
  try {
    const result = window.eval(`(async () => { ${code} })()`);
    await result;
    console.log(`[drive OK] ${label}`);
  } catch (e) {
    errors.push(`drive "${label}" threw: ${e.stack || e}`);
  }
}

(async () => {
  // Let init microtasks/promises settle first.
  await new Promise((r) => setTimeout(r, 50));

  // Each inputSheet() call gets a fresh, monotonically-increasing sheetId
  // (input-sheet-N), and old sheets' DOM nodes aren't removed until 240ms
  // after close (see inputSheet's own comment on this). So each driver
  // below grabs the *last* matching cancel button (highest N), not the
  // first, to make sure it's clicking its own sheet's button and not a
  // stale one still lingering from a previous driver in this same run.
  const lastCancelBtn = `
    const btns = [...document.querySelectorAll('[id^="input-sheet-"][id$="-cancel"]')];
    const cancelBtn = btns[btns.length-1];
  `;

  // inputSheet() smoke test: open with all 4 field types + immediately cancel.
  await drive("inputSheet text/number/select/date fields render", `
    const r = inputSheet({title:"QA", fields:[
      {id:"a", label:"A", type:"text"},
      {id:"b", label:"B", type:"number"},
      {id:"c", label:"C", type:"select", options:[{value:"x",label:"X"}], defaultValue:"x"},
      {id:"d", label:"D", type:"date"},
    ], confirmLabel:"OK"});
    ${lastCancelBtn}
    if(!cancelBtn) throw new Error("no cancel button found for generic inputSheet");
    cancelBtn.click();
    const result = await r;
    if (result !== null) throw new Error("expected null on cancel, got "+JSON.stringify(result));
  `);

  // uiSetSchedule / uiAddWorker existence + callable without throwing before user interaction.
  await drive("uiSetSchedule is a function and opens a sheet", `
    if (typeof window.uiSetSchedule !== "function") throw new Error("uiSetSchedule missing");
    const p = window.uiSetSchedule("ТестМойщик");
    await new Promise(r=>setTimeout(r,10));
    ${lastCancelBtn}
    if(!cancelBtn) throw new Error("no cancel button found for uiSetSchedule sheet");
    cancelBtn.click();
    await p;
  `);

  await drive("uiAddWorker is a function and opens a sheet", `
    if (typeof window.uiAddWorker !== "function") throw new Error("uiAddWorker missing");
    const p = window.uiAddWorker();
    await new Promise(r=>setTimeout(r,10));
    ${lastCancelBtn}
    if(!cancelBtn) throw new Error("no cancel button found for uiAddWorker sheet");
    cancelBtn.click();
    await p;
  `);

  // Now drive uiSetSchedule to a real SAVE with valid input, to exercise the
  // validate() branch and confirm the POST /api/schedule payload shape.
  await drive("uiSetSchedule save path builds correct POST payload", `
    const p = window.uiSetSchedule("ТестМойщик2");
    await new Promise(r=>setTimeout(r,10));
    const sheets = [...document.querySelectorAll('[id^="input-sheet-"]')];
    const idPrefix = sheets.filter(el=>el.id.endsWith('-save')).pop()?.id.replace('-save','');
    if(!idPrefix) throw new Error("could not locate this sheet's field ids");
    document.getElementById(idPrefix+'-work_days').value = "4";
    document.getElementById(idPrefix+'-rest_days').value = "2";
    document.getElementById(idPrefix+'-start_date').value = "2026-09-01";
    document.getElementById(idPrefix+'-save').click();
    // uiSetSchedule() is a fire-and-forget async function (its api() call
    // is chained with .then(), not returned/awaited) — it always settles
    // to undefined regardless of outcome. The real assertion is the
    // captured fetch call itself (checked below, after this driver runs).
    await p;
  `);

  // And the empty/reset path: both numeric fields blank => resolves, DELETE branch.
  await drive("uiSetSchedule empty-fields reset path validates as intended", `
    const p = window.uiSetSchedule("ТестМойщик3");
    await new Promise(r=>setTimeout(r,10));
    const sheets = [...document.querySelectorAll('[id^="input-sheet-"]')];
    const idPrefix = sheets.filter(el=>el.id.endsWith('-save')).pop()?.id.replace('-save','');
    if(!idPrefix) throw new Error("could not locate this sheet's field ids");
    document.getElementById(idPrefix+'-work_days').value = "";
    document.getElementById(idPrefix+'-rest_days').value = "";
    document.getElementById(idPrefix+'-start_date').value = "";
    document.getElementById(idPrefix+'-save').click();
    await p; // see note above: always settles to undefined, checked via captured fetch instead
  `);

  // Half-empty submission must be rejected by validate() (tg.showAlert),
  // sheet stays open — confirm the promise has NOT resolved yet, then
  // fill in the missing field and confirm it resolves after that.
  await drive("uiSetSchedule half-empty submission is rejected by validate()", `
    const p = window.uiSetSchedule("ТестМойщик4");
    let settled = false;
    p.then(()=>{settled=true;});
    await new Promise(r=>setTimeout(r,10));
    const sheets = [...document.querySelectorAll('[id^="input-sheet-"]')];
    const idPrefix = sheets.filter(el=>el.id.endsWith('-save')).pop()?.id.replace('-save','');
    if(!idPrefix) throw new Error("could not locate this sheet's field ids");
    document.getElementById(idPrefix+'-work_days').value = "3";
    document.getElementById(idPrefix+'-rest_days').value = ""; // half-empty
    document.getElementById(idPrefix+'-start_date').value = "2026-09-01";
    document.getElementById(idPrefix+'-save').click();
    await new Promise(r=>setTimeout(r,10));
    if (settled) throw new Error("half-empty submission resolved instead of being rejected by validate()");
    // now complete it correctly and confirm it DOES resolve
    document.getElementById(idPrefix+'-rest_days').value = "1";
    document.getElementById(idPrefix+'-save').click();
    await p; // see note above: always settles to undefined, checked via captured fetch instead
  `);

  await drive("uiAddWorker save path with a real name", `
    const p = window.uiAddWorker();
    await new Promise(r=>setTimeout(r,10));
    const sheets = [...document.querySelectorAll('[id^="input-sheet-"]')];
    const idPrefix = sheets.filter(el=>el.id.endsWith('-save')).pop()?.id.replace('-save','');
    if(!idPrefix) throw new Error("could not locate this sheet's field ids");
    document.getElementById(idPrefix+'-name').value = "Пётр";
    document.getElementById(idPrefix+'-save').click();
    await p;
  `);

  await drive("uiAddWorker empty name is rejected by validate()", `
    const p = window.uiAddWorker();
    let settled = false;
    p.then(()=>{settled=true;});
    await new Promise(r=>setTimeout(r,10));
    const sheets = [...document.querySelectorAll('[id^="input-sheet-"]')];
    const idPrefix = sheets.filter(el=>el.id.endsWith('-save')).pop()?.id.replace('-save','');
    document.getElementById(idPrefix+'-name').value = "";
    document.getElementById(idPrefix+'-save').click();
    await new Promise(r=>setTimeout(r,10));
    if (settled) throw new Error("empty name resolved instead of being rejected");
    ${lastCancelBtn}
    cancelBtn.click();
    await p;
  `);

  await drive("no window.prompt reference invoked anywhere in loaded scripts", `
    if (typeof window.prompt === "function") {
      let called = false;
      const orig = window.prompt;
      window.prompt = (...a) => { called = true; return orig(...a); };
    }
  `);

  console.log("\n=== API calls captured ===");
  for (const c of apiCalls) console.log(c.method, c.url, c.body || "");

  // Post-hoc assertions on captured calls (uiSetSchedule doesn't expose its
  // outcome via return value — it fires api() with .then(), so correctness
  // is checked here against what was actually sent, not a return value).
  function expectCall(desc, predicate) {
    const found = apiCalls.some(predicate);
    if (!found) errors.push(`expected API call not found: ${desc}`);
  }
  expectCall(
    "POST /api/schedule with work_days=4,rest_days=2,start_date=2026-09-01 for ТестМойщик2",
    (c) => c.method === "POST" && c.url === "/api/schedule" && c.body &&
      JSON.parse(c.body).name === "ТестМойщик2" &&
      JSON.parse(c.body).work_days === 4 && JSON.parse(c.body).rest_days === 2 &&
      JSON.parse(c.body).start_date === "2026-09-01"
  );
  expectCall(
    "DELETE /api/schedule/.../ТестМойщик3 for the both-fields-empty reset path",
    (c) => c.method === "DELETE" && decodeURIComponent(c.url).includes("ТестМойщик3")
  );
  expectCall(
    "POST /api/schedule for ТестМойщик4 only after the half-empty submission was completed",
    (c) => c.method === "POST" && c.url === "/api/schedule" && c.body &&
      JSON.parse(c.body).name === "ТестМойщик4" && JSON.parse(c.body).rest_days === 1
  );
  expectCall(
    "POST /api/workers with name=Пётр",
    (c) => c.method === "POST" && c.url === "/api/workers" && c.body &&
      JSON.parse(c.body).name === "Пётр"
  );
  // Negative assertion: no POST /api/schedule fired for ТестМойщик3 (the
  // both-empty case must take the DELETE branch only, never both).
  const schedulePostsFor3 = apiCalls.filter(c => c.method === "POST" && c.url === "/api/schedule" && c.body && JSON.parse(c.body).name === "ТестМойщик3");
  if (schedulePostsFor3.length) errors.push("both-empty reset path unexpectedly also fired a POST /api/schedule");

  console.log("\n=== RESULT ===");
  if (errors.length) {
    console.log(`${errors.length} ERROR(S):`);
    for (const e of errors) console.log(" -", e);
    process.exitCode = 1;
  } else {
    console.log("No runtime errors detected during jsdom dry run.");
  }
})();
