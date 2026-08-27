const MEDIA_SLOTS = [
  {
    id: "hero-object",
    label: "Главный экран",
    title: "Большая вращающаяся керамика",
    description: "Лучше всего работает квадратное фото предмета, снятого строго сверху.",
    defaultSrc: "assets/hero-cat-plate.jpg",
  },
  {
    id: "program-clay",
    label: "Программа · 01",
    title: "Лепка",
    description: "Работа из глины или готовая кото-тарелка.",
    defaultSrc: "assets/real-cat-plate.jpg",
  },
  {
    id: "program-face",
    label: "Программа · 02",
    title: "Аквагрим",
    description: "Живой кадр с праздника или портрет с аквагримом.",
    defaultSrc: "assets/real-kids.jpg",
  },
  {
    id: "program-paint",
    label: "Программа · 03",
    title: "Роспись",
    description: "Яркая керамическая работа крупным планом.",
    defaultSrc: "assets/real-flower-plate.jpg",
  },
  {
    id: "program-photo",
    label: "Программа · 04",
    title: "Фотосессия",
    description: "Готовая работа или эмоциональный кадр финала.",
    defaultSrc: "assets/real-bunny-cup.jpg",
  },
  {
    id: "process-main",
    label: "Как проходит",
    title: "Главная фотография процесса",
    description: "Вертикальный кадр с руками, материалами и мастерской.",
    defaultSrc: "assets/workshop-hands.jpg",
  },
  {
    id: "result-one",
    label: "Галерея · 01",
    title: "Эмоции участников",
    description: "Вертикальная фотография детей с готовой работой.",
    defaultSrc: "assets/real-kids.jpg",
  },
  {
    id: "result-two",
    label: "Галерея · 02",
    title: "Яркая работа",
    description: "Керамика крупным планом, желательно на спокойном фоне.",
    defaultSrc: "assets/real-flower-plate.jpg",
  },
  {
    id: "result-three",
    label: "Галерея · 03",
    title: "Авторская тарелка",
    description: "Ещё одна непохожая работа участника.",
    defaultSrc: "assets/real-meadow-plate.jpg",
  },
];

const MAX_FILE_SIZE = 12 * 1024 * 1024;
const mediaGrid = document.querySelector("[data-media-grid]");
const cardTemplate = document.querySelector("#media-card-template");
const logoutButton = document.querySelector(".logout-button");

logoutButton.addEventListener("click", async () => {
  logoutButton.disabled = true;
  try {
    await fetch("/api/admin/logout", { method: "POST" });
  } finally {
    window.location.replace("/login.html");
  }
});

const setPreview = (card, source, isCustom) => {
  const image = card.querySelector(".media-preview img");
  const oldUrl = image.dataset.objectUrl;
  if (oldUrl) URL.revokeObjectURL(oldUrl);

  if (source instanceof Blob) {
    const url = URL.createObjectURL(source);
    image.src = url;
    image.dataset.objectUrl = url;
  } else {
    image.src = source;
    delete image.dataset.objectUrl;
  }

  card.classList.toggle("has-custom-image", isCustom);
  card.querySelector(".reset-button").disabled = !isCustom;
};

const setStatus = (card, message, type = "success") => {
  const status = card.querySelector(".card-status");
  status.textContent = message;
  status.dataset.type = type;
};

const saveFile = async (slot, card, file) => {
  if (!file.type.startsWith("image/")) {
    setStatus(card, "Выберите изображение в формате JPG, PNG или WebP.", "error");
    return;
  }

  if (file.size > MAX_FILE_SIZE) {
    setStatus(card, "Файл больше 12 МБ. Сожмите изображение и попробуйте снова.", "error");
    return;
  }

  try {
    await window.GusiMedia.setImage(slot.id, file);
    setPreview(card, file, true);
    setStatus(card, "Сохранено. Изображение уже обновилось на открытом сайте.");
    window.GusiMedia.notify(slot.id);
  } catch {
    setStatus(card, "Не удалось сохранить изображение. Проверьте подключение к серверу.", "error");
  }
};

const createCard = async (slot, index) => {
  const card = cardTemplate.content.firstElementChild.cloneNode(true);
  card.dataset.slot = slot.id;
  card.querySelector(".slot-kicker").textContent = slot.label;
  card.querySelector("h3").textContent = slot.title;
  card.querySelector(".slot-description").textContent = slot.description;
  card.querySelector(".media-preview img").alt = slot.title;
  card.style.setProperty("--card-delay", `${index * 45}ms`);

  const input = card.querySelector("input[type='file']");
  input.addEventListener("change", () => {
    const [file] = input.files;
    if (file) saveFile(slot, card, file);
    input.value = "";
  });

  const preview = card.querySelector(".media-preview");
  ["dragenter", "dragover"].forEach((eventName) => {
    preview.addEventListener(eventName, (event) => {
      event.preventDefault();
      card.classList.add("is-dragging");
    });
  });

  ["dragleave", "drop"].forEach((eventName) => {
    preview.addEventListener(eventName, (event) => {
      event.preventDefault();
      card.classList.remove("is-dragging");
    });
  });

  preview.addEventListener("drop", (event) => {
    const [file] = event.dataTransfer.files;
    if (file) saveFile(slot, card, file);
  });

  card.querySelector(".reset-button").addEventListener("click", async () => {
    try {
      await window.GusiMedia.removeImage(slot.id);
      setPreview(card, slot.defaultSrc, false);
      setStatus(card, "Возвращено исходное изображение.");
      window.GusiMedia.notify(slot.id);
    } catch {
      setStatus(card, "Не удалось вернуть исходное изображение.", "error");
    }
  });

  mediaGrid.append(card);

  try {
    const record = await window.GusiMedia.getImage(slot.id);
    setPreview(card, record?.blob || slot.defaultSrc, Boolean(record?.blob));
  } catch {
    setPreview(card, slot.defaultSrc, false);
    setStatus(card, "Хранилище изображений временно недоступно.", "error");
  }
};

const telegramForm = document.querySelector("[data-telegram-form]");
const emailForm = document.querySelector("[data-email-form]");
const bookingsList = document.querySelector("[data-bookings-list]");
const bookingsCount = document.querySelector("[data-bookings-count]");

const setChannelState = (element, text, state) => {
  element.textContent = text;
  element.dataset.state = state;
};

const setChannelStatus = (element, message, type = "success") => {
  element.textContent = message;
  element.dataset.type = type;
};

/** Общий обработчик для обеих форм настройки: сохранить, проверить, обновить состояние. */
const wireChannelForm = ({ form, endpoint, statusNode, collect, onSaved }) => {
  if (!form) return;
  const button = form.querySelector(".settings-save");

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const body = collect();
    if (Object.values(body).some((value) => !value)) {
      setChannelStatus(statusNode, "Заполните все поля.", "error");
      return;
    }

    button.disabled = true;
    setChannelStatus(statusNode, "Проверяем…");

    try {
      const response = await fetch(endpoint, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(payload.error || "Не удалось сохранить.");
      onSaved(payload);
    } catch (error) {
      setChannelStatus(statusNode, error.message, "error");
    } finally {
      button.disabled = false;
    }
  });
};

const telegramState = document.querySelector("[data-telegram-state]");
const telegramStatus = document.querySelector("[data-telegram-status]");
const emailState = document.querySelector("[data-email-state]");
const emailStatus = document.querySelector("[data-email-status]");

const loadTelegramSettings = async () => {
  try {
    const response = await fetch("/api/admin/telegram", { cache: "no-store" });
    if (!response.ok) throw new Error();
    const settings = await response.json();

    if (!settings.configured) {
      setChannelState(telegramState, "не настроен", "missing");
      return;
    }
    telegramForm.elements.chatId.value = settings.chatId;
    setChannelState(
      telegramState,
      settings.fromEnvironment ? "настроен на сервере" : `чат ${settings.chatId} · ${settings.tokenHint}`,
      "ready"
    );
  } catch {
    setChannelState(telegramState, "не удалось проверить", "missing");
  }
};

const loadEmailSettings = async () => {
  try {
    const response = await fetch("/api/admin/email", { cache: "no-store" });
    if (!response.ok) throw new Error();
    const settings = await response.json();

    if (!settings.configured) {
      setChannelState(emailState, "не настроена", "missing");
      return;
    }
    emailForm.elements.sender.value = settings.sender;
    emailForm.elements.recipient.value = settings.recipient;
    setChannelState(
      emailState,
      settings.fromEnvironment ? "настроена на сервере" : `на ${settings.recipient}`,
      "ready"
    );
  } catch {
    setChannelState(emailState, "не удалось проверить", "missing");
  }
};

wireChannelForm({
  form: telegramForm,
  endpoint: "/api/admin/telegram",
  statusNode: telegramStatus,
  collect: () => ({
    token: telegramForm.elements.token.value.trim(),
    chatId: telegramForm.elements.chatId.value.trim(),
  }),
  onSaved: async (payload) => {
    telegramForm.elements.token.value = "";
    setChannelStatus(telegramStatus, `Готово. Бот @${payload.botName} прислал в чат проверочное сообщение.`);
    await loadTelegramSettings();
  },
});

wireChannelForm({
  form: emailForm,
  endpoint: "/api/admin/email",
  statusNode: emailStatus,
  collect: () => ({
    apiKey: emailForm.elements.apiKey.value.trim(),
    sender: emailForm.elements.sender.value.trim(),
    recipient: emailForm.elements.recipient.value.trim(),
  }),
  onSaved: async (payload) => {
    emailForm.elements.apiKey.value = "";
    setChannelStatus(emailStatus, `Готово. На ${payload.recipient} ушло проверочное письмо.`);
    await loadEmailSettings();
  },
});

const CHANNEL_NAMES = { telegram: "Telegram", email: "Почта" };

// В базе дата лежит как 2026-09-12 — показываем её по-человечески.
const formatEventDate = (value) => {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value || "");
  return match ? `${match[3]}.${match[2]}.${match[1]}` : value;
};

const renderBooking = (booking) => {
  const card = document.createElement("article");
  card.className = "booking-card";

  const when = new Date(booking.created_at);
  const whenText = Number.isNaN(when.valueOf())
    ? booking.created_at
    : when.toLocaleString("ru-RU", { day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit" });

  const parts = [
    `<p class="booking-when">${whenText}</p>`,
    `<h3></h3>`,
    `<p class="booking-phone"><a href="tel:${booking.phone.replace(/[^\d+]/g, "")}"></a></p>`,
    `<div class="booking-facts"><span class="fact-format"></span><span class="fact-when"></span></div>`,
  ];
  if (booking.comment) parts.push(`<p class="booking-comment"></p>`);
  parts.push(`<div class="booking-delivery"></div>`);
  card.innerHTML = parts.join("");

  // Текст заявки пришёл от постороннего человека — вставляем только как текст.
  card.querySelector("h3").textContent = booking.name;
  card.querySelector(".booking-phone a").textContent = booking.phone;
  card.querySelector(".fact-format").textContent = booking.format;
  card.querySelector(".fact-when").textContent = `${formatEventDate(booking.event_date)} · ${booking.guests} чел.`;
  if (booking.comment) card.querySelector(".booking-comment").textContent = booking.comment;

  const delivery = booking.delivery || {};
  const deliveryNode = card.querySelector(".booking-delivery");
  Object.entries(delivery).forEach(([channel, outcome]) => {
    const tag = document.createElement("span");
    tag.className = "delivery-tag";
    tag.dataset.ok = String(outcome === "ok");
    tag.textContent = `${CHANNEL_NAMES[channel] || channel}: ${outcome === "ok" ? "доставлено" : "сбой"}`;
    tag.title = outcome;
    deliveryNode.append(tag);
  });
  if (Object.values(delivery).some((outcome) => outcome !== "ok")) {
    card.classList.add("has-failure");
  }

  return card;
};

const loadBookings = async () => {
  if (!bookingsList) return;
  try {
    const response = await fetch("/api/admin/bookings", { cache: "no-store" });
    if (!response.ok) throw new Error();
    const bookings = await response.json();

    bookingsList.replaceChildren();
    if (!bookings.length) {
      const empty = document.createElement("p");
      empty.className = "bookings-empty";
      empty.textContent = "Заявок пока нет. Как только кто-то заполнит форму, она появится здесь.";
      bookingsList.append(empty);
      bookingsCount.textContent = "";
      return;
    }

    bookings.forEach((booking) => bookingsList.append(renderBooking(booking)));
    bookingsCount.textContent = `Показаны последние ${bookings.length}`;
  } catch {
    bookingsList.replaceChildren();
    const failed = document.createElement("p");
    failed.className = "bookings-empty";
    failed.textContent = "Не удалось загрузить заявки.";
    bookingsList.append(failed);
  }
};

document.addEventListener("DOMContentLoaded", () => {
  MEDIA_SLOTS.forEach((slot, index) => createCard(slot, index));
  loadTelegramSettings();
  loadEmailSettings();
  loadBookings();
});
