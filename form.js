const bookingForm = document.querySelector("[data-booking-form]");

if (bookingForm) {
  const FALLBACK_URL = "https://vk.ru/goncharnaya72";
  const status = bookingForm.querySelector("[data-form-status]");
  const submitButton = bookingForm.querySelector(".booking-submit");
  const submitLabel = bookingForm.querySelector("[data-submit-label]");
  const dateInput = bookingForm.querySelector("#booking-date");
  const phoneInput = bookingForm.querySelector("#booking-phone");
  const openedAt = Date.now();

  dateInput.min = new Date().toISOString().slice(0, 10);

  const setStatus = (message, kind) => {
    status.textContent = message;
    status.classList.toggle("is-error", kind === "error");
    status.classList.toggle("is-success", kind === "success");
  };

  const setFieldError = (field, hasError) => {
    field.classList.toggle("has-error", hasError);
    field.setAttribute("aria-invalid", hasError ? "true" : "false");
  };

  const digitsOf = (value) => value.replace(/\D/g, "");

  const validate = () => {
    const problems = [];
    const fields = bookingForm.querySelectorAll("input, select, textarea");
    fields.forEach((field) => setFieldError(field, false));

    const check = (field, isValid, label) => {
      if (isValid) return;
      setFieldError(field, true);
      problems.push(label);
    };

    const { name, format, guests, consent } = bookingForm.elements;
    check(name, name.value.trim().length >= 2, "имя");
    check(phoneInput, digitsOf(phoneInput.value).length >= 10, "телефон");
    check(format, Boolean(format.value), "формат");
    check(dateInput, Boolean(dateInput.value), "дату");
    check(guests, Number(guests.value) >= 1, "количество человек");
    check(consent, consent.checked, "согласие на обработку данных");

    return problems;
  };

  const collect = () => ({
    name: bookingForm.elements.name.value.trim(),
    phone: phoneInput.value.trim(),
    format: bookingForm.elements.format.value,
    date: dateInput.value,
    guests: bookingForm.elements.guests.value.trim(),
    comment: bookingForm.elements.comment.value.trim(),
  });

  const send = async (data) => {
    const response = await fetch("/api/booking", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data),
    });

    const payload = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(payload.error || `Сервер ответил ${response.status}`);
    return payload;
  };

  const showFallback = () => {
    const link = document.createElement("a");
    link.href = FALLBACK_URL;
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    link.className = "text-button status-link";
    link.textContent = "Написать в VK ↗";
    status.append(" ", link);
  };

  bookingForm.addEventListener("submit", async (event) => {
    event.preventDefault();

    // Ловушка для ботов: живой человек это поле не видит и заполнить не может.
    if (bookingForm.elements.company.value || Date.now() - openedAt < 2000) {
      setStatus("Заявка отправлена. Спасибо!", "success");
      return;
    }

    const problems = validate();
    if (problems.length) {
      setStatus(`Заполните, пожалуйста: ${problems.join(", ")}.`, "error");
      bookingForm.querySelector(".has-error")?.focus();
      return;
    }

    submitButton.disabled = true;
    submitLabel.textContent = "Отправляем…";
    setStatus("");

    try {
      await send(collect());
      bookingForm.classList.add("is-sent");
      submitLabel.textContent = "Заявка отправлена";
      setStatus("Спасибо! Заявка у нас — свяжемся с вами в ближайшее время.", "success");
      bookingForm.reset();
    } catch (error) {
      console.error("Не удалось отправить заявку:", error);
      submitButton.disabled = false;
      submitLabel.textContent = "Отправить заявку";
      setStatus("Не получилось отправить. Напишите нам, пожалуйста, в VK — ответим там.", "error");
      showFallback();
    }
  });

  bookingForm.querySelectorAll("input, select, textarea").forEach((field) => {
    ["input", "change"].forEach((eventName) =>
      field.addEventListener(eventName, () => setFieldError(field, false))
    );
  });
}
