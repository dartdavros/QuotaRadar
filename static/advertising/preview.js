"use strict";

document.addEventListener("DOMContentLoaded", () => {
    const body = document.getElementById("id_body");
    const target = document.getElementById("id_target");
    const help = document.getElementById("id_body_helptext");
    if (!body || !target || !help) return;

    const preview = document.createElement("div");
    preview.className = "readonly";
    preview.setAttribute("aria-live", "polite");
    body.closest(".form-row").append(preview);
    const instructions = help.textContent;
    let timer;
    let revision = 0;

    const update = async () => {
        const current = ++revision;
        const form = new FormData();
        form.set("body", body.value);
        form.set("target", target.value);
        form.set("csrfmiddlewaretoken", document.querySelector("[name=csrfmiddlewaretoken]").value);
        try {
            const response = await fetch(body.dataset.previewUrl, {
                method: "POST", body: form, credentials: "same-origin"
            });
            const result = await response.json();
            if (current !== revision) return;
            if (!response.ok) {
                body.setCustomValidity(result.error || "Предпросмотр недоступен.");
                preview.textContent = result.error || "Предпросмотр недоступен.";
                help.textContent = instructions;
                return;
            }
            body.setCustomValidity("");
            help.textContent = `${instructions} ${result.length} / 200.`;
            preview.innerHTML = result.html;
        } catch {
            if (current === revision) preview.textContent = "Предпросмотр недоступен.";
        }
    };
    const schedule = () => {
        clearTimeout(timer);
        timer = setTimeout(update, 250);
    };
    body.addEventListener("input", schedule);
    target.addEventListener("change", schedule);
    update();
});
