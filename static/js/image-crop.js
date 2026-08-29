(() => {
  const dialog = document.getElementById("image-crop-dialog");
  const title = document.getElementById("image-crop-title");
  const viewport = document.getElementById("image-crop-viewport");
  const canvas = document.getElementById("image-crop-canvas");
  const zoomInput = document.getElementById("image-crop-zoom");
  const sizeInput = document.getElementById("image-crop-size");
  const sizeLabel = document.getElementById("image-crop-size-label");
  const cancelButton = document.getElementById("image-crop-cancel");
  const applyButton = document.getElementById("image-crop-apply");

  if (!dialog || !viewport || !canvas) {
    return;
  }

  const pointers = new Map();
  let source = null;
  let activeInput = null;
  let applyingFile = false;
  let aspect = 1;
  let viewW = 280;
  let viewH = 280;
  let zoom = 1;
  let minZoom = 1;
  let maxZoom = 4;
  let offsetX = 0;
  let offsetY = 0;
  let pinchStartDistance = 0;
  let pinchStartZoom = 1;

  function parseAspect(value) {
    const parts = String(value || "1:1").split(":");
    const width = Number(parts[0]);
    const height = Number(parts[1]);
    if (!width || !height) {
      return 1;
    }
    return width / height;
  }

  function outputSize(maxEdge) {
    if (aspect >= 1) {
      return { width: maxEdge, height: Math.max(1, Math.round(maxEdge / aspect)) };
    }
    return { width: Math.max(1, Math.round(maxEdge * aspect)), height: maxEdge };
  }

  function fitViewport() {
    const maxW = Math.min(320, window.innerWidth - 72);
    const maxH = Math.min(320, window.innerHeight - 300);
    let width = maxW;
    let height = width / aspect;
    if (height > maxH) {
      height = maxH;
      width = height * aspect;
    }
    viewW = Math.max(160, Math.round(width));
    viewH = Math.max(160, Math.round(height));
    viewport.style.width = `${viewW}px`;
    viewport.style.height = `${viewH}px`;
  }

  function displaySize() {
    return {
      width: source.width * zoom,
      height: source.height * zoom,
    };
  }

  function clampOffset() {
    const size = displaySize();
    offsetX = Math.min(0, Math.max(viewW - size.width, offsetX));
    offsetY = Math.min(0, Math.max(viewH - size.height, offsetY));
  }

  function setZoom(nextZoom, originX = viewW / 2, originY = viewH / 2) {
    const oldZoom = zoom;
    zoom = Math.min(maxZoom, Math.max(minZoom, nextZoom));
    const sourceX = (originX - offsetX) / oldZoom;
    const sourceY = (originY - offsetY) / oldZoom;
    offsetX = originX - sourceX * zoom;
    offsetY = originY - sourceY * zoom;
    clampOffset();
    zoomInput.value = String(zoom);
    render();
  }

  function render() {
    if (!source) {
      return;
    }
    const dpr = window.devicePixelRatio || 1;
    canvas.width = Math.round(viewW * dpr);
    canvas.height = Math.round(viewH * dpr);
    canvas.style.width = `${viewW}px`;
    canvas.style.height = `${viewH}px`;
    const ctx = canvas.getContext("2d");
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.fillStyle = "#111";
    ctx.fillRect(0, 0, viewW, viewH);
    const size = displaySize();
    ctx.imageSmoothingEnabled = true;
    ctx.imageSmoothingQuality = "high";
    ctx.drawImage(source, offsetX, offsetY, size.width, size.height);
    updateSizeLabel();
  }

  function updateSizeLabel() {
    const size = outputSize(Number(sizeInput.value));
    sizeLabel.textContent = `${size.width} × ${size.height} px`;
  }

  async function loadSource(file) {
    if (typeof createImageBitmap === "function") {
      try {
        return await createImageBitmap(file, { imageOrientation: "from-image" });
      } catch (_error) {
        // Fall back to Image when the browser cannot decode the file this way.
      }
    }
    return new Promise((resolve, reject) => {
      const url = URL.createObjectURL(file);
      const image = new Image();
      image.onload = () => {
        URL.revokeObjectURL(url);
        resolve(image);
      };
      image.onerror = () => {
        URL.revokeObjectURL(url);
        reject(new Error("Could not read that image."));
      };
      image.src = url;
    });
  }

  function resetPointers() {
    pointers.clear();
    pinchStartDistance = 0;
  }

  const cropQueue = [];
  let queueBusy = false;

  function photoPicker(input) {
    return input ? input.closest("[data-photo-picker]") : null;
  }

  function pickedFiles(input) {
    if (!input._pickedFiles) {
      input._pickedFiles = [];
    }
    return input._pickedFiles;
  }

  function maxPhotos(input) {
    return Number(photoPicker(input)?.dataset.max || 6);
  }

  function keptExistingCount(input) {
    const picker = photoPicker(input);
    if (!picker) {
      return 0;
    }
    return picker.querySelectorAll(".photo-thumb[data-existing-id]:not(.is-removed)").length;
  }

  function remainingSlots(input) {
    const queued = cropQueue.filter((item) => item.input === input).length;
    return Math.max(
      0,
      maxPhotos(input) - keptExistingCount(input) - pickedFiles(input).length - queued
    );
  }

  function syncPickedInput(input) {
    const transfer = new DataTransfer();
    pickedFiles(input).forEach((file) => transfer.items.add(file));
    const wasApplying = applyingFile;
    applyingFile = true;
    input.files = transfer.files;
    applyingFile = wasApplying;
  }

  function renderNewThumbs(input) {
    const list = photoPicker(input)?.querySelector("[data-photo-thumbs]");
    if (!list) {
      return;
    }
    list.querySelectorAll(".photo-thumb.is-new").forEach((node) => node.remove());
    const removeLabel = photoPicker(input)?.dataset.removeLabel || "Remove";
    pickedFiles(input).forEach((file, index) => {
      const item = document.createElement("li");
      item.className = "photo-thumb is-new";
      const image = document.createElement("img");
      image.alt = "";
      image.src = URL.createObjectURL(file);
      const button = document.createElement("button");
      button.type = "button";
      button.className = "photo-thumb-remove";
      button.setAttribute("aria-label", removeLabel);
      button.textContent = "×";
      button.addEventListener("click", () => {
        pickedFiles(input).splice(index, 1);
        applyingFile = true;
        syncPickedInput(input);
        input.dispatchEvent(new Event("change", { bubbles: true }));
        applyingFile = false;
        renderNewThumbs(input);
      });
      item.append(image, button);
      list.append(item);
    });
  }

  function processQueue() {
    if (dialog.open || queueBusy) {
      return;
    }
    const next = cropQueue.shift();
    if (!next) {
      return;
    }
    queueBusy = true;
    openDialog(next.input, next.file);
  }

  function closeDialog(clearInput) {
    resetPointers();
    if (source && typeof source.close === "function") {
      source.close();
    }
    source = null;
    dialog.close();
    if (clearInput && activeInput && !activeInput.multiple) {
      activeInput.value = "";
      activeInput.dispatchEvent(new Event("change", { bubbles: true }));
    }
    activeInput = null;
    queueBusy = false;
    processQueue();
  }

  async function openDialog(input, file) {
    try {
      source = await loadSource(file);
    } catch (_error) {
      window.alert("Could not read that image. Try a JPG, PNG, or WEBP file.");
      if (!input.multiple) {
        input.value = "";
        input.dispatchEvent(new Event("change", { bubbles: true }));
      }
      queueBusy = false;
      processQueue();
      return;
    }

    activeInput = input;
    aspect = parseAspect(input.dataset.cropAspect);
    title.textContent = input.dataset.cropTitle || "Crop photo";
    viewport.classList.toggle("is-circle", input.dataset.cropShape === "circle");
    sizeInput.min = input.dataset.cropMin || "400";
    sizeInput.max = input.dataset.cropMax || "1200";
    sizeInput.value = input.dataset.cropSize || sizeInput.max;
    fitViewport();
    minZoom = Math.max(viewW / source.width, viewH / source.height);
    maxZoom = minZoom * 4;
    zoom = minZoom;
    zoomInput.min = String(minZoom);
    zoomInput.max = String(maxZoom);
    zoomInput.step = String((maxZoom - minZoom) / 100);
    zoomInput.value = String(zoom);
    offsetX = (viewW - source.width * zoom) / 2;
    offsetY = (viewH - source.height * zoom) / 2;
    clampOffset();
    render();
    if (typeof dialog.showModal === "function") {
      dialog.showModal();
    }
  }

  function applyPreview(input, file) {
    const preview = input.dataset.cropPreview
      ? document.querySelector(input.dataset.cropPreview)
      : null;
    if (!preview) {
      return;
    }
    if (input._cropPreviewUrl) {
      URL.revokeObjectURL(input._cropPreviewUrl);
    }
    input._cropPreviewUrl = URL.createObjectURL(file);
    preview.src = input._cropPreviewUrl;
    preview.hidden = false;
    const fallback = input.dataset.cropFallback
      ? document.querySelector(input.dataset.cropFallback)
      : null;
    if (fallback) {
      fallback.hidden = true;
    }
  }

  async function applyCrop() {
    if (!source || !activeInput) {
      return;
    }
    const size = outputSize(Number(sizeInput.value));
    const exportCanvas = document.createElement("canvas");
    exportCanvas.width = size.width;
    exportCanvas.height = size.height;
    const ctx = exportCanvas.getContext("2d");
    ctx.imageSmoothingEnabled = true;
    ctx.imageSmoothingQuality = "high";
    const sourceX = -offsetX / zoom;
    const sourceY = -offsetY / zoom;
    const sourceW = viewW / zoom;
    const sourceH = viewH / zoom;
    ctx.drawImage(source, sourceX, sourceY, sourceW, sourceH, 0, 0, size.width, size.height);
    const blob = await new Promise((resolve) => {
      exportCanvas.toBlob(resolve, "image/jpeg", 0.9);
    });
    if (!blob) {
      window.alert("Could not crop that photo. Try another image.");
      return;
    }
    const cropped = new File([blob], `product-photo-${Date.now()}.jpg`, { type: "image/jpeg" });
    if (activeInput.multiple) {
      pickedFiles(activeInput).push(cropped);
      applyingFile = true;
      syncPickedInput(activeInput);
      activeInput.dispatchEvent(new Event("change", { bubbles: true }));
      applyingFile = false;
      renderNewThumbs(activeInput);
      applyPreview(activeInput, cropped);
      closeDialog(false);
      return;
    }
    const transfer = new DataTransfer();
    transfer.items.add(cropped);
    applyingFile = true;
    activeInput.files = transfer.files;
    applyPreview(activeInput, cropped);
    activeInput.dispatchEvent(new Event("change", { bubbles: true }));
    applyingFile = false;
    closeDialog(false);
  }

  document.querySelectorAll("input[data-image-crop]").forEach((input) => {
    input.addEventListener("change", () => {
      if (applyingFile) {
        return;
      }
      if (!input.files || !input.files.length) {
        return;
      }
      if (input.multiple) {
        const incoming = [...input.files];
        const room = remainingSlots(input);
        const take = incoming.slice(0, room);
        if (!take.length) {
          window.alert(photoPicker(input)?.dataset.maxMessage || "You can add up to 6 photos.");
          syncPickedInput(input);
          return;
        }
        if (incoming.length > take.length) {
          window.alert(photoPicker(input)?.dataset.maxMessage || "You can add up to 6 photos.");
        }
        take.forEach((file) => cropQueue.push({ input, file }));
        applyingFile = true;
        syncPickedInput(input);
        applyingFile = false;
        processQueue();
        return;
      }
      const file = input.files[0];
      if (!file) {
        return;
      }
      openDialog(input, file);
    });
  });

  zoomInput.addEventListener("input", () => {
    setZoom(Number(zoomInput.value));
  });
  sizeInput.addEventListener("input", updateSizeLabel);

  viewport.addEventListener("pointerdown", (event) => {
    viewport.setPointerCapture(event.pointerId);
    pointers.set(event.pointerId, { x: event.clientX, y: event.clientY });
    if (pointers.size === 2) {
      const points = [...pointers.values()];
      pinchStartDistance = Math.hypot(points[0].x - points[1].x, points[0].y - points[1].y);
      pinchStartZoom = zoom;
    }
  });

  viewport.addEventListener("pointermove", (event) => {
    if (!pointers.has(event.pointerId)) {
      return;
    }
    const previous = pointers.get(event.pointerId);
    pointers.set(event.pointerId, { x: event.clientX, y: event.clientY });
    if (pointers.size === 2 && pinchStartDistance) {
      const points = [...pointers.values()];
      const distance = Math.hypot(points[0].x - points[1].x, points[0].y - points[1].y);
      setZoom(pinchStartZoom * (distance / pinchStartDistance));
      return;
    }
    offsetX += event.clientX - previous.x;
    offsetY += event.clientY - previous.y;
    clampOffset();
    render();
  });

  function endPointer(event) {
    pointers.delete(event.pointerId);
    if (pointers.size < 2) {
      pinchStartDistance = 0;
    }
  }

  viewport.addEventListener("pointerup", endPointer);
  viewport.addEventListener("pointercancel", endPointer);

  viewport.addEventListener(
    "wheel",
    (event) => {
      if (!source) {
        return;
      }
      event.preventDefault();
      const rect = viewport.getBoundingClientRect();
      const factor = event.deltaY < 0 ? 1.08 : 0.92;
      setZoom(zoom * factor, event.clientX - rect.left, event.clientY - rect.top);
    },
    { passive: false }
  );

  cancelButton?.addEventListener("click", () => closeDialog(true));
  applyButton?.addEventListener("click", () => {
    applyCrop().catch(() => {
      window.alert("Could not crop that photo. Try another image.");
    });
  });
  dialog.addEventListener("cancel", (event) => {
    event.preventDefault();
    closeDialog(true);
  });
})();
