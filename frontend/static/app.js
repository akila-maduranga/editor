document.addEventListener("DOMContentLoaded", () => {
    // DOM Elements
    const dropZone = document.getElementById("dropZone");
    const fileInput = document.getElementById("fileInput");

    // States
    const stateInitial = document.getElementById("stateInitial");
    const stateProcessing = document.getElementById("stateProcessing");
    const stateSuccess = document.getElementById("stateSuccess");
    const stateError = document.getElementById("stateError");

    // Status
    const fileNameLabel = document.getElementById("fileNameLabel");
    const errorMessage = document.getElementById("errorMessage");

    // Status Steps
    const stepUpload = document.getElementById("stepUpload");
    const stepRemux = document.getElementById("stepRemux");
    const stepPatch = document.getElementById("stepPatch");
    const stepDone = document.getElementById("stepDone");

    // Buttons
    const downloadBtn = document.getElementById("downloadBtn");
    const resetBtn = document.getElementById("resetBtn");
    const errorResetBtn = document.getElementById("errorResetBtn");

    let currentFile = null;
    let patchedBlobUrl = null;
    let patchedFileName = "";

    const MAX_SIZE_MB = 500;
    const MAX_SIZE_BYTES = MAX_SIZE_MB * 1024 * 1024;

    const PLACEHOLDER_STEPS = [
        "Uploading file to enhancement engine...",
        "Running AI quality analysis pass...",
        "Optimizing container structure for streaming...",
        "Applying final polish & encoding metadata...",
    ];

    ["dragenter", "dragover", "dragleave", "drop"].forEach(eventName => {
        dropZone.addEventListener(eventName, preventDefaults, false);
        document.body.addEventListener(eventName, preventDefaults, false);
    });

    ["dragenter", "dragover"].forEach(eventName => {
        dropZone.addEventListener(eventName, () => dropZone.classList.add("dragover"), false);
    });
    ["dragleave", "drop"].forEach(eventName => {
        dropZone.addEventListener(eventName, () => dropZone.classList.remove("dragover"), false);
    });

    dropZone.addEventListener("drop", handleDrop, false);
    fileInput.addEventListener("change", handleFileSelect, false);
    downloadBtn.addEventListener("click", triggerDownload);
    resetBtn.addEventListener("click", resetToInitial);
    errorResetBtn.addEventListener("click", resetToInitial);

    function preventDefaults(e) {
        e.preventDefault();
        e.stopPropagation();
    }

    function handleDrop(e) {
        const files = e.dataTransfer.files;
        if (files.length > 0) processFile(files[0]);
    }

    function handleFileSelect(e) {
        const files = e.target.files;
        if (files.length > 0) processFile(files[0]);
    }

    function processFile(file) {
        if (!file.name.toLowerCase().endsWith(".mp4")) {
            showError("Unsupported format. Please upload an MP4 video.");
            return;
        }
        if (file.size > MAX_SIZE_BYTES) {
            showError(`File too large (${formatBytes(file.size)}). Maximum is ${MAX_SIZE_MB}MB.`);
            return;
        }
        currentFile = file;
        uploadAndPatch(file);
    }

    function uploadAndPatch(file) {
        showState(stateProcessing);
        fileNameLabel.textContent = file.name;

        resetSteps();
        updateStep(stepUpload, "active", "Uploading file to enhancement engine...");

        const formData = new FormData();
        formData.append("file", file);

        const xhr = new XMLHttpRequest();
        xhr.open("POST", "/api/patch", true);

        xhr.upload.addEventListener("progress", (e) => {
            if (e.lengthComputable) {
                const pct = Math.round((e.loaded / e.total) * 100);
                updateStep(stepUpload, "active", `Uploading file to enhancement engine... ${pct}%`);
                if (pct === 100) {
                    updateStep(stepUpload, "done", "File uploaded successfully");
                    updateStep(stepRemux, "active", "Running AI quality analysis pass...");
                }
            }
        });

        xhr.onload = function () {
            if (xhr.status === 200) {
                updateStep(stepRemux, "done", "AI quality analysis complete");
                updateStep(stepPatch, "active", "Optimizing container structure for streaming...");

                setTimeout(() => {
                    updateStep(stepPatch, "done", "Container structure optimized");
                    updateStep(stepDone, "active", "Applying final polish & encoding metadata...");

                    setTimeout(() => {
                        updateStep(stepDone, "done", "All enhancements applied successfully");

                        const responseData = xhr.response;
                        if (!responseData || responseData.byteLength === 0) {
                            showError("Server returned an empty response.");
                            return;
                        }

                        const blob = new Blob([responseData], { type: "video/mp4" });

                        const disposition = xhr.getResponseHeader("Content-Disposition");
                        patchedFileName = "enhanced_" + file.name;
                        if (disposition && disposition.indexOf("attachment") !== -1) {
                            const m = disposition.match(/filename[^;=\n]*=((['"]).*?\2|[^;\n]*)/);
                            if (m && m[1]) patchedFileName = m[1].replace(/['"]/g, "");
                        }

                        if (patchedBlobUrl) window.URL.revokeObjectURL(patchedBlobUrl);
                        patchedBlobUrl = window.URL.createObjectURL(blob);

                        showState(stateSuccess);
                        triggerDownload();
                    }, 500);
                }, 500);
            } else if (xhr.status === 0) {
                showError("Network error: Could not reach the server.");
            } else {
                try {
                    const errText = xhr.response?.byteLength ? new TextDecoder("utf-8").decode(xhr.response) : "";
                    const errJson = JSON.parse(errText);
                    showError(errJson.detail || "Server error occurred.");
                } catch (e) {
                    showError("Server error (" + xhr.status + ")");
                }
            }
        };

        xhr.onerror = () => showError("Network error: Could not reach the server.");
        xhr.ontimeout = () => showError("Request timed out. The server is taking too long.");

        xhr.responseType = "arraybuffer";
        xhr.timeout = 300000;
        xhr.send(formData);
    }

    function triggerDownload() {
        if (!patchedBlobUrl) return;
        const a = document.createElement("a");
        a.href = patchedBlobUrl;
        a.download = patchedFileName;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
    }

    function resetToInitial() {
        currentFile = null;
        fileInput.value = "";
        if (patchedBlobUrl) {
            window.URL.revokeObjectURL(patchedBlobUrl);
            patchedBlobUrl = null;
        }
        patchedFileName = "";
        showState(stateInitial);
    }

    function showState(activeState) {
        [stateInitial, stateProcessing, stateSuccess, stateError].forEach(s => {
            s.classList.toggle("hidden", s !== activeState);
        });
    }

    function showError(msg) {
        errorMessage.textContent = msg;
        showState(stateError);
    }

    function resetSteps() {
        [stepUpload, stepRemux, stepPatch, stepDone].forEach(el => {
            el.classList.remove("active", "done", "pending");
            el.classList.add("pending");
        });
    }

    function updateStep(el, state, text) {
        el.classList.remove("active", "pending", "done");
        el.classList.add(state);
        if (text) el.querySelector(".step-text").textContent = text;
    }

    function formatBytes(bytes, decimals = 2) {
        if (bytes === 0) return "0 Bytes";
        const k = 1024;
        const sizes = ["Bytes", "KB", "MB", "GB"];
        const i = Math.floor(Math.log(bytes) / Math.log(k));
        return parseFloat((bytes / Math.pow(k, i)).toFixed(decimals)) + " " + sizes[i];
    }
});
