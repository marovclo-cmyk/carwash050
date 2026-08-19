/* ============================================================
   ui-kit.js — глобальная система взаимодействий (Plata)
   PROJECT_BRAIN V3 / PHASE 3 — GLOBAL INTERACTION SYSTEM.

   Одна переиспользуемая реализация на весь проект:
     UI.Modal    — модальные окна (оборачивает существующий .modal-bg)
     UI.Drawer   — выезжающая панель (справа/слева)
     UI.Toast    — тосты (success/error/warning/info), очередь, авто-скрытие
     UI.Confirm  — Promise-диалог подтверждения для опасных действий
     UI.Popover  — привязанная к якорю всплывающая панель
     UI.Dropdown — выпадающий список с клавиатурой
     UI.Tooltip  — подсказка по hover/focus
     UI.BottomSheet — нижний лист (мобильный аналог Drawer)

   Общее поведение всех overlay-компонентов:
     ESC закрывает верхний в стеке; клик вне — если разрешено;
     фокус переносится внутрь при открытии и возвращается назад при
     закрытии; скролл body блокируется, пока открыт хотя бы один
     overlay (с учётом вложенности); z-index выдаётся по стеку —
     конфликтов между несколькими одновременно открытыми overlay нет.
     Modal/Drawer/BottomSheet (Confirm включён — построен на Modal)
     дополнительно закрываются по кнопке "Назад" браузера/устройства
     вместо реального ухода со страницы (см. pushShadowHistory ниже) —
     Phase 4, хвостовой пункт.

   Это НЕ трогает существующую навигацию сайта (мобильный
   drawer/бургер — site-common.js) — она вне периметра этого этапа
   и использует свой собственный, отдельный класс блокировки скролла
   (`body.mobile-nav-locked`), поэтому конфликтов с
   `body.ui-scroll-locked` ниже нет: оба класса независимо
   выставляют `overflow:hidden`, друг другу не мешают.
   ============================================================ */
const UI = (() => {
  "use strict";

  /* ---------------- Overlay stack (общий для всех типов) ---------------- */
  const stack = [];
  const BASE_Z = 1000;
  let scrollLockCount = 0;

  function lockScroll() {
    if (scrollLockCount === 0) {
      const barW = window.innerWidth - document.documentElement.clientWidth;
      document.body.classList.add("ui-scroll-locked");
      if (barW > 0) document.body.style.paddingRight = barW + "px";
    }
    scrollLockCount++;
  }
  function unlockScroll() {
    scrollLockCount = Math.max(0, scrollLockCount - 1);
    if (scrollLockCount === 0) {
      document.body.classList.remove("ui-scroll-locked");
      document.body.style.paddingRight = "";
    }
  }
  function pushOverlay(item) {
    item.z = BASE_Z + stack.length * 2;
    stack.push(item);
    return item.z;
  }
  function popOverlay(item) {
    const i = stack.indexOf(item);
    if (i !== -1) stack.splice(i, 1);
  }
  function topOverlay() {
    return stack[stack.length - 1] || null;
  }

  /* ---------------- Browser-history-aware overlays (Phase 4 tail item) ----
     Pressing the browser/hardware Back button while a Modal/Drawer/
     BottomSheet (Confirm included — it's built on Modal) is open closes
     it instead of navigating away from the page. Popover/Dropdown/Tooltip
     are deliberately excluded: Tooltip never joins the overlay stack, and
     Popover/Dropdown have no real call site anywhere in the app yet (see
     MODULE_REGISTRY.md) — nothing to verify this against, add it if/when
     one gets a real caller.

     Mechanism: opening pushes one throwaway "shadow" history entry (same
     URL, just a back-stop marker). Back button pops it -> popstate fires
     -> the top overlay closes instead of the page actually navigating.
     Closing any other way (ESC, X, outside click, Save, programmatic
     close) consumes that same shadow entry via history.back() so it never
     piles up in the back stack across repeated opens/closes. */
  let popstateHooked = false;
  function hookPopstateOnce() {
    if (popstateHooked) return;
    popstateHooked = true;
    window.addEventListener("popstate", () => {
      const top = topOverlay();
      if (!top || top.closeOnBack === false || !top.entryRef) return;
      top.entryRef._closingFromPopstate = true;
      top.close();
      top.entryRef._closingFromPopstate = false;
    });
  }
  function pushShadowHistory(entry) {
    if (entry.opts.closeOnBack === false) return;
    hookPopstateOnce();
    history.pushState({ __uiOverlayShadow: true }, "", location.href);
    entry._historyPushed = true;
  }
  function popShadowHistory(entry) {
    if (!entry._historyPushed) return;
    entry._historyPushed = false;
    if (!entry._closingFromPopstate) history.back();
  }

  const prefersReducedMotion =
    window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  function getFocusable(container) {
    return Array.from(
      container.querySelectorAll(
        'a[href],button:not([disabled]),textarea:not([disabled]),input:not([disabled]),select:not([disabled]),[tabindex]:not([tabindex="-1"])'
      )
    ).filter((el) => el.offsetParent !== null);
  }
  function trapFocus(container, e) {
    if (e.key !== "Tab") return;
    const f = getFocusable(container);
    if (!f.length) return;
    const first = f[0], last = f[f.length - 1];
    if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
    else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
  }
  function escapeHtml(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
    }[c]));
  }

  document.addEventListener("keydown", (e) => {
    if (e.key !== "Escape") return;
    const top = topOverlay();
    if (top && top.closeOnEsc !== false) {
      e.preventDefault();
      top.close();
    }
  });

  /* ============================================================
     Modal — оборачивает существующий элемент `.modal-bg` (разметка
     остаётся как есть на страницах: контент модалки — забота модуля,
     а не этого файла). Даёт бесплатно: ESC, клик вне, фокус,
     scroll-lock, единый z-index.
     ============================================================ */
  const modalRegistry = {};

  function registerModal(id, opts = {}) {
    const el = typeof id === "string" ? document.getElementById(id) : id;
    if (!el) return null;
    const key = el.id || id;
    if (modalRegistry[key]) return modalRegistry[key];

    const entry = {
      id: key, el, opts,
      closeOnEsc: opts.closeOnEsc !== false,
      closeOnOutside: opts.closeOnOutside !== false,
      lastFocused: null,
      _stackItem: null,
      _historyPushed: false,
      _closingFromPopstate: false,
      open() { openModal(entry); },
      close() { closeModal(entry); },
    };
    // fallback-цель фокуса, если внутри вообще нет фокусируемых
    // элементов (иначе .focus() на обычном div молча ничего не делает)
    if (!el.hasAttribute("tabindex")) el.setAttribute("tabindex", "-1");
    el.addEventListener("mousedown", (e) => {
      if (e.target === el && entry.closeOnOutside) entry.close();
    });
    el.addEventListener("keydown", (e) => trapFocus(el, e));
    modalRegistry[key] = entry;
    return entry;
  }

  function openModal(entry) {
    if (entry.el.classList.contains("open")) return;
    entry.lastFocused = document.activeElement;
    entry.el.classList.add("open");
    entry._stackItem = {
      type: "modal", close: () => entry.close(), closeOnEsc: entry.closeOnEsc,
      closeOnBack: entry.opts.closeOnBack, entryRef: entry,
    };
    entry.el.style.zIndex = pushOverlay(entry._stackItem);
    lockScroll();
    pushShadowHistory(entry);
    const focusFirst = () => {
      const f = getFocusable(entry.el);
      (f[0] || entry.el).focus?.();
    };
    if (prefersReducedMotion) focusFirst();
    else requestAnimationFrame(focusFirst);
    if (entry.opts.onOpen) entry.opts.onOpen();
  }
  function closeModal(entry) {
    if (!entry.el.classList.contains("open")) return;
    entry.el.classList.remove("open");
    if (entry._stackItem) { popOverlay(entry._stackItem); entry._stackItem = null; }
    unlockScroll();
    popShadowHistory(entry);
    if (entry.lastFocused && entry.lastFocused.focus) entry.lastFocused.focus();
    if (entry.opts.onClose) entry.opts.onClose();
  }

  const Modal = {
    register(id, opts) { return registerModal(id, opts); },
    open(id, opts) {
      const entry = modalRegistry[id] || registerModal(id, opts || {});
      if (entry) entry.open();
      return entry;
    },
    close(id) { const e = modalRegistry[id]; if (e) e.close(); },
    isOpen(id) { const e = modalRegistry[id]; return !!(e && e.el.classList.contains("open")); },
  };

  /* ============================================================
     Drawer — выезжающая панель. Два режима:
     - create(id, opts)  — строит панель+подложку с нуля;
     - wrap(el, opts)    — превращает уже существующий блок (например,
       инлайн-панель редактирования) в drawer: переносит его в
       подложку в конце <body>, ничего не пересоздавая внутри (все
       id/обработчики на полях формы остаются рабочими).
     ============================================================ */
  const drawerRegistry = {};

  function buildDrawerChrome(side, title) {
    const bg = document.createElement("div");
    bg.className = "ui-drawer-bg";
    const panel = document.createElement("div");
    panel.className = `ui-drawer ui-drawer-${side === "left" ? "left" : "right"}`;
    panel.setAttribute("role", "dialog");
    panel.setAttribute("aria-modal", "true");
    // fallback-цель фокуса, если внутри нет фокусируемых элементов
    panel.setAttribute("tabindex", "-1");
    const header = document.createElement("div");
    header.className = "ui-drawer-header";
    header.innerHTML = `<div class="ui-drawer-title">${escapeHtml(title || "")}</div>
      <button type="button" class="ui-drawer-close" aria-label="Закрыть"><i class="ti ti-x"></i></button>`;
    const body = document.createElement("div");
    body.className = "ui-drawer-body";
    panel.appendChild(header);
    panel.appendChild(body);
    bg.appendChild(panel);
    return { bg, panel, header, body };
  }

  function makeDrawerEntry(id, bg, panel, opts) {
    const entry = {
      id, el: bg, panel, opts,
      closeOnEsc: opts.closeOnEsc !== false,
      closeOnOutside: opts.closeOnOutside !== false,
      lastFocused: null,
      _stackItem: null,
      _historyPushed: false,
      _closingFromPopstate: false,
      open() { openDrawer(entry); },
      close() { closeDrawer(entry); },
    };
    bg.addEventListener("mousedown", (e) => {
      if (e.target === bg && entry.closeOnOutside) entry.close();
    });
    panel.addEventListener("keydown", (e) => trapFocus(panel, e));
    drawerRegistry[id] = entry;
    return entry;
  }

  function openDrawer(entry) {
    if (entry.el.classList.contains("open")) return;
    entry.lastFocused = document.activeElement;
    entry.el.classList.add("open");
    entry._stackItem = {
      type: "drawer", close: () => entry.close(), closeOnEsc: entry.closeOnEsc,
      closeOnBack: entry.opts.closeOnBack, entryRef: entry,
    };
    entry.el.style.zIndex = pushOverlay(entry._stackItem);
    entry.panel.style.zIndex = entry.el.style.zIndex;
    lockScroll();
    pushShadowHistory(entry);
    const focusFirst = () => {
      const f = getFocusable(entry.panel);
      (f[0] || entry.panel).focus?.();
    };
    if (prefersReducedMotion) focusFirst();
    else requestAnimationFrame(focusFirst);
    if (entry.opts.onOpen) entry.opts.onOpen();
  }
  function closeDrawer(entry) {
    if (!entry.el.classList.contains("open")) return;
    entry.el.classList.remove("open");
    if (entry._stackItem) { popOverlay(entry._stackItem); entry._stackItem = null; }
    unlockScroll();
    popShadowHistory(entry);
    if (entry.lastFocused && entry.lastFocused.focus) entry.lastFocused.focus();
    if (entry.opts.onClose) entry.opts.onClose();
  }

  const Drawer = {
    /** Строит новую панель. opts.side: 'right'|'left'. opts.bodyEl — уже
     *  готовый DOM-узел содержимого (переносится внутрь .ui-drawer-body). */
    create(id, opts = {}) {
      if (drawerRegistry[id]) return drawerRegistry[id];
      const { bg, panel, body } = buildDrawerChrome(opts.side, opts.title);
      if (opts.bodyEl) body.appendChild(opts.bodyEl);
      else if (opts.bodyHTML) body.innerHTML = opts.bodyHTML;
      document.body.appendChild(bg);
      const entry = makeDrawerEntry(id, bg, panel, opts);
      panel.querySelector(".ui-drawer-close").addEventListener("click", () => entry.close());
      return entry;
    },
    /** Превращает уже существующий элемент (например, инлайн-панель
     *  редактирования) в drawer, не трогая его внутреннюю разметку —
     *  только переносит его в подложку в конце <body>. */
    wrap(el, opts = {}) {
      const id = el.id || `ui-drawer-${Math.random().toString(36).slice(2)}`;
      if (drawerRegistry[id]) return drawerRegistry[id];
      const { bg, panel, body } = buildDrawerChrome(opts.side, opts.title);
      el.style.display = ""; // снимаем ручной display:none/block, если был
      body.appendChild(el);
      document.body.appendChild(bg);
      const entry = makeDrawerEntry(id, bg, panel, opts);
      panel.querySelector(".ui-drawer-close").addEventListener("click", () => {
        if (opts.onCloseClick) opts.onCloseClick();
        entry.close();
      });
      return entry;
    },
    open(id) { const e = drawerRegistry[id]; if (e) e.open(); },
    close(id) { const e = drawerRegistry[id]; if (e) e.close(); },
    isOpen(id) { const e = drawerRegistry[id]; return !!(e && e.el.classList.contains("open")); },
  };

  /* ============================================================
     Toast — единая очередь тостов на всё приложение.
     ============================================================ */
  const ICONS = {
    success: "ti-circle-check", error: "ti-alert-circle",
    warning: "ti-alert-triangle", warn: "ti-alert-triangle",
    info: "ti-info-circle",
  };
  let toastWrap = null;
  function ensureToastWrap() {
    if (!toastWrap) {
      toastWrap = document.createElement("div");
      toastWrap.className = "ui-toast-wrap";
      document.body.appendChild(toastWrap);
    }
    return toastWrap;
  }
  const Toast = {
    show(text, type = "success", opts = {}) {
      const wrap = ensureToastWrap();
      const el = document.createElement("div");
      el.className = `ui-toast ${type === "warn" ? "warning" : type}`;
      const icon = ICONS[type] || ICONS.info;
      el.innerHTML = `<i class="ti ${icon}"></i><span class="ui-toast-text"></span>
        <button type="button" class="ui-toast-close" aria-label="Закрыть"><i class="ti ti-x"></i></button>`;
      el.querySelector(".ui-toast-text").textContent = text;
      wrap.appendChild(el);
      requestAnimationFrame(() => el.classList.add("show"));
      const duration = opts.duration != null ? opts.duration : 3000;
      let timer = null;
      function dismiss() {
        el.classList.remove("show");
        setTimeout(() => el.remove(), 220);
      }
      if (duration > 0) timer = setTimeout(dismiss, duration);
      el.querySelector(".ui-toast-close").addEventListener("click", () => { clearTimeout(timer); dismiss(); });
      return { dismiss };
    },
    success(text, opts) { return this.show(text, "success", opts); },
    error(text, opts) { return this.show(text, "error", opts); },
    warning(text, opts) { return this.show(text, "warning", opts); },
    info(text, opts) { return this.show(text, "info", opts); },
  };

  /* ============================================================
     Confirm — Promise-диалог для опасных/необратимых действий.
     UI.Confirm.show({title, message, confirmText, cancelText, danger})
       .then(ok => { if (ok) { ... } })
     ============================================================ */
  const Confirm = {
    show(opts = {}) {
      const {
        title = "Подтвердите действие", message = "",
        confirmText = "Подтвердить", cancelText = "Отмена", danger = false,
      } = opts;
      return new Promise((resolve) => {
        let result = false;
        let resolved = false;
        const bg = document.createElement("div");
        bg.className = "modal-bg ui-confirm-bg";
        bg.innerHTML = `
          <div class="ui-confirm">
            <div class="ui-confirm-title">${escapeHtml(title)}</div>
            ${message ? `<div class="ui-confirm-msg">${escapeHtml(message)}</div>` : ""}
            <div class="ui-confirm-actions">
              <button type="button" class="btn secondary" data-act="cancel">${escapeHtml(cancelText)}</button>
              <button type="button" class="btn ${danger ? "danger" : ""}" data-act="ok">${escapeHtml(confirmText)}</button>
            </div>
          </div>`;
        document.body.appendChild(bg);
        const entry = registerModal(bg, {
          closeOnOutside: true,
          onClose: () => {
            if (!resolved) { resolved = true; resolve(result); }
            setTimeout(() => bg.remove(), 220);
          },
        });
        bg.querySelector('[data-act="cancel"]').addEventListener("click", () => { result = false; entry.close(); });
        bg.querySelector('[data-act="ok"]').addEventListener("click", () => { result = true; entry.close(); });
        entry.open();
      });
    },
  };

  /* ============================================================
     Popover — панель, привязанная к якорному элементу.
     ============================================================ */
  const Popover = {
    open(anchorEl, contentHTMLorEl, opts = {}) {
      Popover.closeAll();
      const pop = document.createElement("div");
      pop.className = "ui-popover";
      if (typeof contentHTMLorEl === "string") pop.innerHTML = contentHTMLorEl;
      else pop.appendChild(contentHTMLorEl);
      document.body.appendChild(pop);
      const r = anchorEl.getBoundingClientRect();
      const scrollY = window.scrollY, scrollX = window.scrollX;
      pop.style.position = "absolute";
      pop.style.zIndex = pushOverlay({ type: "popover", close: () => Popover.closeAll(), closeOnEsc: true });
      // сперва меряем, затем позиционируем (с fallback, если не влезает снизу)
      const pr = pop.getBoundingClientRect();
      let top = r.bottom + scrollY + 8;
      if (r.bottom + pr.height > window.innerHeight && r.top > pr.height) {
        top = r.top + scrollY - pr.height - 8; // сверху, если снизу не влезает
      }
      let left = (opts.align === "right") ? r.right + scrollX - pr.width : r.left + scrollX;
      left = Math.max(8, Math.min(left, window.innerWidth + scrollX - pr.width - 8));
      pop.style.top = `${top}px`;
      pop.style.left = `${left}px`;
      requestAnimationFrame(() => pop.classList.add("open"));
      function onOutside(e) {
        if (!pop.contains(e.target) && e.target !== anchorEl && !anchorEl.contains(e.target)) Popover.closeAll();
      }
      setTimeout(() => document.addEventListener("mousedown", onOutside), 0);
      Popover._active = { pop, onOutside, stackItem: topOverlay() };
      return pop;
    },
    closeAll() {
      if (!Popover._active) return;
      const { pop, onOutside, stackItem } = Popover._active;
      document.removeEventListener("mousedown", onOutside);
      pop.classList.remove("open");
      if (stackItem) popOverlay(stackItem);
      setTimeout(() => pop.remove(), 160);
      Popover._active = null;
    },
    _active: null,
  };

  /* ============================================================
     Dropdown — простой выпадающий список с клавиатурой.
     items: [{value,label,disabled}]. onSelect(value).
     ============================================================ */
  const Dropdown = {
    open(anchorEl, items, opts = {}) {
      const html = document.createElement("div");
      html.className = "ui-dropdown";
      html.setAttribute("role", "listbox");
      items.forEach((it, i) => {
        const row = document.createElement("div");
        row.className = "ui-dropdown-item" + (it.disabled ? " disabled" : "") + (it.selected ? " selected" : "");
        row.setAttribute("role", "option");
        row.tabIndex = it.disabled ? -1 : 0;
        row.textContent = it.label;
        if (!it.disabled) {
          row.addEventListener("click", () => { Popover.closeAll(); if (opts.onSelect) opts.onSelect(it.value); });
          row.addEventListener("keydown", (e) => {
            if (e.key === "Enter" || e.key === " ") { e.preventDefault(); row.click(); }
            if (e.key === "ArrowDown") { e.preventDefault(); (row.nextElementSibling || html.firstElementChild)?.focus(); }
            if (e.key === "ArrowUp") { e.preventDefault(); (row.previousElementSibling || html.lastElementChild)?.focus(); }
          });
        }
        html.appendChild(row);
      });
      const pop = Popover.open(anchorEl, html, opts);
      const first = pop.querySelector(".ui-dropdown-item:not(.disabled)");
      if (first) first.focus();
      return pop;
    },
  };

  /* ============================================================
     Tooltip — простая подсказка по hover/focus (без стека/scroll-lock —
     она не модальная).
     ============================================================ */
  const Tooltip = {
    attach(el, text, opts = {}) {
      let tip = null;
      function show() {
        tip = document.createElement("div");
        tip.className = "ui-tooltip";
        tip.textContent = typeof text === "function" ? text() : text;
        document.body.appendChild(tip);
        const r = el.getBoundingClientRect();
        const tr = tip.getBoundingClientRect();
        const pos = opts.position || "top";
        let top = pos === "top" ? r.top - tr.height - 8 : r.bottom + 8;
        let left = r.left + r.width / 2 - tr.width / 2;
        left = Math.max(6, Math.min(left, window.innerWidth - tr.width - 6));
        tip.style.top = `${top + window.scrollY}px`;
        tip.style.left = `${left + window.scrollX}px`;
        requestAnimationFrame(() => tip.classList.add("show"));
      }
      function hide() {
        if (!tip) return;
        tip.remove();
        tip = null;
      }
      el.addEventListener("mouseenter", show);
      el.addEventListener("mouseleave", hide);
      el.addEventListener("focus", show);
      el.addEventListener("blur", hide);
      return { hide };
    },
  };

  /* ============================================================
     BottomSheet — нижний лист (мобильный аналог Drawer, тот же
     механизм стека/фокуса/скролл-лока, другая CSS-анимация/позиция).
     ============================================================ */
  const sheetRegistry = {};
  const BottomSheet = {
    create(id, opts = {}) {
      if (sheetRegistry[id]) return sheetRegistry[id];
      const bg = document.createElement("div");
      bg.className = "ui-sheet-bg";
      const panel = document.createElement("div");
      panel.className = "ui-sheet";
      panel.setAttribute("role", "dialog");
      panel.setAttribute("aria-modal", "true");
      panel.setAttribute("tabindex", "-1"); // fallback-цель фокуса
      panel.innerHTML = `<div class="ui-sheet-handle"></div>`;
      const body = document.createElement("div");
      body.className = "ui-sheet-body";
      if (opts.bodyEl) body.appendChild(opts.bodyEl);
      else if (opts.bodyHTML) body.innerHTML = opts.bodyHTML;
      panel.appendChild(body);
      bg.appendChild(panel);
      document.body.appendChild(bg);
      const entry = makeDrawerEntry(id, bg, panel, opts); // тот же движок, что у Drawer
      sheetRegistry[id] = entry;
      bg.addEventListener("mousedown", (e) => { if (e.target === bg && entry.closeOnOutside) entry.close(); });
      return entry;
    },
    open(id) { const e = sheetRegistry[id]; if (e) e.open(); },
    close(id) { const e = sheetRegistry[id]; if (e) e.close(); },
  };

  return { Modal, Drawer, Toast, Confirm, Popover, Dropdown, Tooltip, BottomSheet };
})();
