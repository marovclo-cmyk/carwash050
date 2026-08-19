/* payment-flow.js — общий поток "Оплатить онлайн" (сумма → провайдер →
   подтверждение).

   PROJECT BRAIN V4 / Stage 23 / PHASE 3 (Checkout/Payment audit).
   Бэкенд не менялся: тот же POST /api/payments и
   POST /api/payments/{id}/mock-confirm, что и раньше (webapp/server.py,
   sessions.create_payment/apply_payment_success). Раньше эта логика была
   почти продублирована в двух местах — booking.html:doPayOnline и
   cars.html:payOnline — и вместо ui-kit.js использовала нативные
   prompt()/confirm()/alert(), единственное такое место в проекте (см.
   CHANGELOG.md → "V4 / Stage 23 — PHASE 3"). Здесь она одна, построена
   на UI.Modal (сумма) + UI.Confirm (тестовое подтверждение, мок-режим) +
   UI.Toast — тех же примитивах, что и весь остальной сайт.

   Подключать после site-common.js и ui-kit.js:
     <script src="/static/js/payment-flow.js"></script>
*/
const PaymentFlow = (() => {
  "use strict";

  function escapeHtml(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
    }[c]));
  }

  // Модалка ввода суммы — на существующих глобальных .modal-bg/.modal/
  // .field/.modal-actions (theme-plata.css), новых CSS-классов не
  // добавлено. Тот же паттерн динамического модала, что и у UI.Confirm
  // (ui-kit.js): создаём элемент на каждый вызов, регистрируем через
  // публичный UI.Modal.register, удаляем из DOM после закрытия.
  function amountDialog({ title, message, defaultAmount }) {
    return new Promise((resolve) => {
      const bg = document.createElement("div");
      bg.className = "modal-bg";
      bg.innerHTML = `
        <div class="modal" style="width:380px">
          <h2>${escapeHtml(title)}</h2>
          ${message ? `<div style="font-size:12.5px;color:var(--muted);margin:-10px 0 4px;line-height:1.4">${escapeHtml(message)}</div>` : ""}
          <div class="field">
            <label>Сумма (₽)</label>
            <input type="number" id="pfAmount" min="1" value="${defaultAmount || ""}">
          </div>
          <div class="err-banner" id="pfAmountErr" style="display:none;margin-top:10px"></div>
          <div class="modal-actions">
            <button type="button" class="btn secondary" id="pfCancel">Отмена</button>
            <button type="button" class="btn accent" id="pfContinue"><i class="ti ti-credit-card"></i>Продолжить</button>
          </div>
        </div>`;
      document.body.appendChild(bg);
      let resolved = false;
      const entry = UI.Modal.register(bg, {
        onClose: () => {
          if (!resolved) { resolved = true; resolve(null); }
          setTimeout(() => bg.remove(), 220);
        },
      });
      function finish(amount) {
        resolved = true;
        resolve(amount);
        entry.close();
      }
      bg.querySelector("#pfCancel").addEventListener("click", () => finish(null));
      bg.querySelector("#pfContinue").addEventListener("click", () => {
        const input = bg.querySelector("#pfAmount");
        const amount = parseInt(input.value, 10);
        const err = bg.querySelector("#pfAmountErr");
        if (!amount || amount <= 0) {
          err.textContent = "Укажите сумму больше нуля";
          err.style.display = "block";
          return;
        }
        finish(amount);
      });
      entry.open();
      const focusTarget = bg.querySelector("#pfAmount");
      requestAnimationFrame(() => focusTarget.focus());
    });
  }

  /**
   * Запустить оплату онлайн: спросить сумму → создать платёж
   * (POST /api/payments) → открыть ссылку провайдера → в мок-режиме
   * предложить тестовое подтверждение.
   *
   * @param {object} opts
   *   branch, purpose ("advance"|"car"), amount по умолчанию,
   *   bookingId / carNum, phone, clientName, description,
   *   mock (bool, обязательно — берётся из уже загруженного /api/config
   *     страницей-вызывающей стороной, чтобы не делать лишний запрос),
   *   title/message — текст модалки суммы,
   *   onSuccess(payment) — вызывается ТОЛЬКО после успешного тестового
   *     подтверждения в мок-режиме (как и в исходном коде — реальная
   *     оплата подтверждается асинхронно через вебхук, не сразу),
   *   onError(message) — по умолчанию UI.Toast.error.
   */
  async function payOnline(opts) {
    const {
      branch, purpose, bookingId = null, carNum = null,
      phone = "", clientName = "", description = "",
      defaultAmount = "", mock = false,
      title = "Оплата онлайн", message = "",
      onSuccess, onError,
    } = opts;
    const reportErr = onError || ((msg) => UI.Toast.error(msg));

    const amount = await amountDialog({ title, message, defaultAmount });
    if (amount == null) return; // отменено пользователем

    let payment;
    try {
      const r = await CW.authFetch("/api/payments", {
        method: "POST",
        body: JSON.stringify({
          branch, purpose, amount,
          booking_id: bookingId, car_num: carNum,
          phone, client_name: clientName, description,
        }),
      });
      payment = r.payment;
    } catch (e) {
      reportErr(e.message);
      return;
    }

    window.open(payment.confirmation_url, "_blank");

    if (mock) {
      const ok = await UI.Confirm.show({
        title: "Ссылка на оплату открыта в новой вкладке",
        message: "Мок-режим — можно сразу подтвердить оплату здесь, не переходя по ссылке.",
        confirmText: "Подтвердить оплату (тест)",
        cancelText: "Просто закрыть",
      });
      if (!ok) return;
      try {
        await CW.authFetch(`/api/payments/${payment.id}/mock-confirm`, { method: "POST" });
        UI.Toast.success("Оплата подтверждена (тест)");
        if (onSuccess) onSuccess(payment);
      } catch (e) {
        reportErr(e.message);
      }
    } else {
      UI.Toast.info("Ссылка на оплату открыта в новой вкладке. Отправьте её клиенту — статус обновится автоматически после оплаты.");
    }
  }

  return { payOnline };
})();
