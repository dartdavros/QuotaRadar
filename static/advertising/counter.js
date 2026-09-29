"use strict";

document.addEventListener("DOMContentLoaded", () => {
    const message = document.getElementById("id_message");
    const label = document.getElementById("id_link_label");
    const help = document.getElementById("id_message_helptext");
    if (!message || !label || !help) return;

    const update = () => {
        // JavaScript string length counts UTF-16 units, matching the server.
        const length = `Рекомендация: ${message.value.trim()} ${label.value.trim()}`.length;
        help.textContent = `Рекламный блок: ${length} / 200 единиц UTF-16, включая «Рекомендация: » и текст ссылки.`;
        message.setCustomValidity(length > 200 ? "Рекламный блок превышает 200 единиц UTF-16." : "");
    };
    message.addEventListener("input", update);
    label.addEventListener("input", update);
    update();
});
