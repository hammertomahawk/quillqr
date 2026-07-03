function createQrCode(container, payload) {
  container.replaceChildren();

  new QRCode(container, {
    text: payload,
    width: 256,
    height: 256,
    colorDark: "#000000",
    colorLight: "#ffffff",
    correctLevel: QRCode.CorrectLevel.M,
  });
}

function getQrCanvas(panel) {
  return panel.querySelector(".qr-code canvas");
}

function downloadPanelQr(panel) {
  const canvas = getQrCanvas(panel);

  if (!canvas) {
    return;
  }

  const quietZone = 48;
  const exportCanvas = document.createElement("canvas");

  exportCanvas.width = canvas.width + quietZone * 2;
  exportCanvas.height = canvas.height + quietZone * 2;

  const context = exportCanvas.getContext("2d");

  context.fillStyle = "#ffffff";
  context.fillRect(
    0,
    0,
    exportCanvas.width,
    exportCanvas.height
  );

  context.drawImage(
    canvas,
    quietZone,
    quietZone
  );

  const name =
    panel.dataset.qrName || "quillqr-document-qr.png";

  const link = document.createElement("a");
  link.href = exportCanvas.toDataURL("image/png");
  link.download = name;
  link.click();
}

function initPageQrCodes() {
  const panels = document.querySelectorAll("[data-qr-payload]");

  for (const panel of panels) {
    const payload = panel.dataset.qrPayload;
    const qrCodeEl = panel.querySelector(".qr-code");
    const downloadButton = panel.querySelector(
      ".download-qr-button"
    );

    if (!payload || !qrCodeEl) {
      continue;
    }

    createQrCode(qrCodeEl, payload);

    if (downloadButton) {
      downloadButton.addEventListener("click", () => {
        downloadPanelQr(panel);
      });
    }
  }
}

initPageQrCodes();