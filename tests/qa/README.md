# Mini App jsdom dry-run (Phase 10)

`mini_app_jsdom_dry_run.js` loads `webapp/static/index.html` and its local
`/static/js/*.js` dependencies into a jsdom virtual DOM, mocks
`Telegram.WebApp` and `fetch`, and actually **executes** the page's init
code plus the Phase 9 `inputSheet()`-based dialogs (all 4 field types,
`uiSetSchedule`, `uiAddWorker`) end-to-end — not just a syntax check.

This is real execution testing (catches undefined references, wrong data
shapes, wiring bugs, wrong API payloads) but it is **not** a substitute
for a real browser: jsdom has no CSS layout/paint engine, no real touch
input, and the Telegram bridge is a hand-written mock, not the actual
`telegram-web-app.js` runtime. It does not confirm visual rendering,
native `<input type="date">` picker behavior, or anything WebKit/iOS-
specific. Chrome/Safari/mobile/real-Telegram-WebView QA (Phase 10 proper)
is still required before shipping.

Run: `node mini_app_jsdom_dry_run.js` from this directory (needs
`jsdom` — `npm install jsdom` first; not currently in `package.json`).
