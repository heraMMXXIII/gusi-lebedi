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
const telegramState = document.querySelector("[data-telegram-state]");
const telegramStatus = document.querySelector("[data-telegram-status]");

const setTelegramState = (text, state) => {
  telegramState.textContent = text;
  telegramState.dataset.state = state;
};

const setTelegramStatus = (message, type = "success") => {
  telegramStatus.textContent = message;
  telegramStatus.dataset.type = type;
};

const loadTelegramSettings = async () => {
  try {
    const response = await fetch("/api/admin/telegram", { cache: "no-store" });
    if (!response.ok) throw new Error("Не удалось прочитать настройки.");
    const settings = await response.json();

    if (!settings.configured) {
      setTelegramState("Заявки пока никуда не приходят", "missing");
      return;
    }

    telegramForm.elements.chatId.value = settings.chatId;
    setTelegramState(
      settings.fromEnvironment
        ? "Настроено через переменные окружения сервера"
        : `Заявки приходят в чат ${settings.chatId} · токен ${settings.tokenHint}`,
      "ready"
    );
  } catch {
    setTelegramState("Не удалось проверить настройки", "missing");
  }
};

telegramForm?.addEventListener("submit", async (event) => {
  event.preventDefault();
  const button = telegramForm.querySelector(".settings-save");
  const token = telegramForm.elements.token.value.trim();
  const chatId = telegramForm.elements.chatId.value.trim();

  if (!token || !chatId) {
    setTelegramStatus("Заполните оба поля.", "error");
    return;
  }

  button.disabled = true;
  setTelegramStatus("Проверяем в Telegram…");

  try {
    const response = await fetch("/api/admin/telegram", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ token, chatId }),
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(payload.error || "Не удалось сохранить.");

    telegramForm.elements.token.value = "";
    setTelegramStatus(`Готово. Бот @${payload.botName} отправил в чат проверочное сообщение.`);
    await loadTelegramSettings();
  } catch (error) {
    setTelegramStatus(error.message, "error");
  } finally {
    button.disabled = false;
  }
});

document.addEventListener("DOMContentLoaded", () => {
  MEDIA_SLOTS.forEach((slot, index) => createCard(slot, index));
  if (telegramForm) loadTelegramSettings();
});
