(function () {
  const API_BASE = "/api/media";
  const DB_NAME = "gusi-lebedi-content";
  const DB_VERSION = 1;
  const STORE_NAME = "images";
  const objectUrls = new WeakMap();

  const openLocalDatabase = () =>
    new Promise((resolve, reject) => {
      const request = indexedDB.open(DB_NAME, DB_VERSION);
      request.onupgradeneeded = () => {
        const database = request.result;
        if (!database.objectStoreNames.contains(STORE_NAME)) {
          database.createObjectStore(STORE_NAME, { keyPath: "slot" });
        }
      };
      request.onsuccess = () => resolve(request.result);
      request.onerror = () => reject(request.error);
    });

  const runLocalTransaction = async (mode, operation) => {
    const database = await openLocalDatabase();
    return new Promise((resolve, reject) => {
      const transaction = database.transaction(STORE_NAME, mode);
      const request = operation(transaction.objectStore(STORE_NAME));
      let result;

      request.onsuccess = () => {
        result = request.result;
      };
      request.onerror = () => reject(request.error);
      transaction.oncomplete = () => {
        database.close();
        resolve(result);
      };
      transaction.onerror = () => reject(transaction.error);
    });
  };

  const localGetImage = (slot) => runLocalTransaction("readonly", (store) => store.get(slot));
  const localSetImage = (slot, file) =>
    runLocalTransaction("readwrite", (store) =>
      store.put({
        slot,
        blob: file,
        name: file.name,
        type: file.type,
        updatedAt: new Date().toISOString(),
      })
    );
  const localRemoveImage = (slot) => runLocalTransaction("readwrite", (store) => store.delete(slot));

  const requestServer = async (slot, options = {}) => {
    const response = await fetch(`${API_BASE}/${encodeURIComponent(slot)}`, {
      cache: "no-store",
      ...options,
    });

    if (response.status === 404 && (!options.method || options.method === "GET")) {
      return null;
    }

    if (!response.ok) {
      let message = "Сервер не смог обработать изображение.";
      try {
        const payload = await response.json();
        if (payload.error) message = payload.error;
      } catch {
        // The status code still provides a useful failure signal.
      }
      const error = new Error(message);
      error.isServerResponse = true;
      throw error;
    }

    return response;
  };

  const getImage = async (slot) => {
    try {
      const response = await requestServer(slot);
      if (!response) return null;
      return {
        slot,
        blob: await response.blob(),
        name: decodeURIComponent(response.headers.get("X-File-Name") || "image"),
        type: response.headers.get("Content-Type") || "application/octet-stream",
        updatedAt: response.headers.get("X-Updated-At"),
        storage: "sqlite",
      };
    } catch (error) {
      if (error.isServerResponse) throw error;
      return localGetImage(slot);
    }
  };

  const setImage = async (slot, file) => {
    try {
      const response = await requestServer(slot, {
        method: "POST",
        headers: {
          "Content-Type": file.type || "application/octet-stream",
          "X-File-Name": encodeURIComponent(file.name || "image"),
        },
        body: file,
      });
      await localRemoveImage(slot).catch(() => undefined);
      return response.json();
    } catch (error) {
      if (error.isServerResponse) throw error;
      await localSetImage(slot, file);
      return { slot, storage: "browser" };
    }
  };

  const removeImage = async (slot) => {
    try {
      const response = await requestServer(slot, { method: "DELETE" });
      await localRemoveImage(slot).catch(() => undefined);
      return response.json();
    } catch (error) {
      if (error.isServerResponse) throw error;
      return localRemoveImage(slot);
    }
  };

  const applySlot = async (element) => {
    const slot = element.dataset.imageSlot;
    if (!slot) return false;

    if (!element.dataset.defaultSrc) {
      element.dataset.defaultSrc = element.getAttribute("src") || "";
    }

    const record = await getImage(slot);
    if (!record?.blob) {
      const previousUrl = objectUrls.get(element);
      if (previousUrl) {
        URL.revokeObjectURL(previousUrl);
        objectUrls.delete(element);
      }
      element.src = element.dataset.defaultSrc;
      delete element.dataset.customImage;
      return false;
    }

    const previousUrl = objectUrls.get(element);
    if (previousUrl) URL.revokeObjectURL(previousUrl);

    const url = URL.createObjectURL(record.blob);
    objectUrls.set(element, url);
    element.src = url;
    element.dataset.customImage = "true";
    return true;
  };

  const applyAll = async (root = document) => {
    const elements = [...root.querySelectorAll("[data-image-slot]")];
    await Promise.all(elements.map((element) => applySlot(element).catch(() => false)));
  };

  const channel = "BroadcastChannel" in window ? new BroadcastChannel("gusi-lebedi-media") : null;
  channel?.addEventListener("message", (event) => {
    if (!event.data?.slot) return;
    document.querySelectorAll(`[data-image-slot="${CSS.escape(event.data.slot)}"]`).forEach((element) => {
      applySlot(element).catch(() => false);
    });
  });

  window.GusiMedia = {
    getImage,
    setImage,
    removeImage,
    applySlot,
    applyAll,
    notify(slot) {
      channel?.postMessage({ slot });
    },
  };

  document.addEventListener("DOMContentLoaded", () => applyAll().catch(() => undefined));
})();
