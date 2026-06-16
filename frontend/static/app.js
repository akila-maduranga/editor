document.addEventListener("DOMContentLoaded", () => {
    // DOM Elements
    const customTagInput = document.getElementById("customTag");
    const encode1080pToggle = document.getElementById("encode1080p");
    const dropZone = document.getElementById("dropZone");
    const fileInput = document.getElementById("fileInput");
    
    // States
    const stateInitial = document.getElementById("stateInitial");
    const stateProcessing = document.getElementById("stateProcessing");
    const stateSuccess = document.getElementById("stateSuccess");
    const stateError = document.getElementById("stateError");
    
    // Status / Messages
    const fileNameLabel = document.getElementById("fileNameLabel");
    const errorMessage = document.getElementById("errorMessage");
    
    // Status Steps
    const stepUpload = document.getElementById("stepUpload");
    const stepRemux = document.getElementById("stepRemux");
    const stepPatch = document.getElementById("stepPatch");
    
    // Buttons
    const downloadBtn = document.getElementById("downloadBtn");
    const resetBtn = document.getElementById("resetBtn");
    const errorResetBtn = document.getElementById("errorResetBtn");

    let currentFile = null;
    let patchedBlobUrl = null;
    let patchedFileName = "";

    // Maximum file size: 500MB
    const MAX_SIZE_MB = 500;
    const MAX_SIZE_BYTES = MAX_SIZE_MB * 1024 * 1024;

    // Prevent default drag behaviors
    ["dragenter", "dragover", "dragleave", "drop"].forEach(eventName => {
        dropZone.addEventListener(eventName, preventDefaults, false);
        document.body.addEventListener(eventName, preventDefaults, false);
    });

    // Toggle highlight on drag enter/leave
    ["dragenter", "dragover"].forEach(eventName => {
        dropZone.addEventListener(eventName, () => dropZone.classList.add("dragover"), false);
    });

    ["dragleave", "drop"].forEach(eventName => {
        dropZone.addEventListener(eventName, () => dropZone.classList.remove("dragover"), false);
    });

    // Handle dropped files
    dropZone.addEventListener("drop", handleDrop, false);

    // Handle clicked input
    fileInput.addEventListener("change", handleFileSelect, false);

    // Handle manual download triggers
    downloadBtn.addEventListener("click", triggerDownload);

    // Reset interface to initial state
    resetBtn.addEventListener("click", resetToInitial);
    errorResetBtn.addEventListener("click", resetToInitial);

    function preventDefaults(e) {
        e.preventDefault();
        e.stopPropagation();
    }

    function handleDrop(e) {
        const dt = e.dataTransfer;
        const files = dt.files;
        if (files.length > 0) {
            processFile(files[0]);
        }
    }

    function handleFileSelect(e) {
        const files = e.target.files;
        if (files.length > 0) {
            processFile(files[0]);
        }
    }

    function processFile(file) {
        // Validation: Format must be MP4
        if (!file.name.toLowerCase().endsWith(".mp4")) {
            showError("Invalid file type. Only MP4 videos (.mp4) are supported.");
            return;
        }

        // Validation: Size must be <= 500MB
        if (file.size > MAX_SIZE_BYTES) {
            showError(`File is too large (${formatBytes(file.size)}). Maximum permitted size is ${MAX_SIZE_MB}MB.`);
            return;
        }

        currentFile = file;
        uploadAndPatch(file);
    }

    function uploadAndPatch(file) {
        // Switch to processing state
        showState(stateProcessing);
        fileNameLabel.textContent = file.name;
        
        // Reset status steps
        updateStep(stepUpload, "active", "Uploading video: 0%");
        updateStep(stepRemux, "pending", "Remuxing container brand to isom...");
        updateStep(stepPatch, "pending", "Injecting tag & patching mdat...");

        const formData = new FormData();
        formData.append("file", file);
        formData.append("custom_tag", customTagInput.value.trim() || "@akila");
        formData.append("encode_1080p", encode1080pToggle.checked);

        const xhr = new XMLHttpRequest();
        xhr.open("POST", "/api/patch", true);

        // Track upload progress
        xhr.upload.addEventListener("progress", (e) => {
            if (e.lengthComputable) {
                const percent = Math.round((e.loaded / e.total) * 100);
                updateStep(stepUpload, "active", `Uploading video: ${percent}%`);
                if (percent === 100) {
                    updateStep(stepUpload, "done", "Uploaded successfully");
                    updateStep(stepRemux, "active", "Remuxing container brand to isom...");
                }
            }
        });

        // Track response loads
        xhr.onload = function() {
            if (xhr.status === 200) {
                updateStep(stepRemux, "done", "Remuxed container brand to isom");
                updateStep(stepPatch, "active", "Injecting tag & patching mdat...");
                
                // Simulate quick completion of the binary patch step
                setTimeout(() => {
                    updateStep(stepPatch, "done", "Patched mdat size successfully");
                    
                    // Retrieve video Blob
                    const blob = xhr.response;
                    
                    // Parse custom filename from headers
                    const disposition = xhr.getResponseHeader("Content-Disposition");
                    patchedFileName = "patched_" + file.name;
                    if (disposition && disposition.indexOf("attachment") !== -1) {
                        const filenameRegex = /filename[^;=\n]*=((['"]).*?\2|[^;\n]*)/;
                        const matches = filenameRegex.exec(disposition);
                        if (matches != null && matches[1]) { 
                            patchedFileName = matches[1].replace(/['"]/g, "");
                        }
                    }

                    // Create blob download url
                    if (patchedBlobUrl) {
                        window.URL.revokeObjectURL(patchedBlobUrl);
                    }
                    patchedBlobUrl = window.URL.createObjectURL(blob);
                    
                    // Transition to success state
                    showState(stateSuccess);
                    
                    // Automatically trigger download
                    triggerDownload();
                }, 600);
            } else {
                // Read error message from JSON response
                try {
                    const reader = new FileReader();
                    reader.onload = function() {
                        try {
                            const errJson = JSON.parse(reader.result);
                            showError(errJson.detail || "Server error occurred during processing.");
                        } catch (e) {
                            showError("Server error occurred during processing.");
                        }
                    };
                    reader.readAsText(xhr.response);
                } catch (e) {
                    showError("An unexpected server response occurred.");
                }
            }
        };

        xhr.onerror = function() {
            showError("Network error: Could not reach the server.");
        };

        // Expect binary response type (Blob)
        xhr.responseType = "blob";
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

    // Helper functions
    function showState(activeState) {
        [stateInitial, stateProcessing, stateSuccess, stateError].forEach(state => {
            if (state === activeState) {
                state.classList.remove("hidden");
            } else {
                state.classList.add("hidden");
            }
        });
    }

    function showError(message) {
        errorMessage.textContent = message;
        showState(stateError);
    }

    function updateStep(stepElement, state, text) {
        // Reset classes
        stepElement.classList.remove("active", "pending", "done");
        
        if (state === "active") {
            stepElement.classList.add("active");
        } else if (state === "done") {
            stepElement.classList.add("done");
        } else {
            stepElement.classList.add("pending");
        }

        if (text) {
            stepElement.querySelector(".step-text").textContent = text;
        }
    }

    function formatBytes(bytes, decimals = 2) {
        if (bytes === 0) return "0 Bytes";
        const k = 1024;
        const dm = decimals < 0 ? 0 : decimals;
        const sizes = ["Bytes", "KB", "MB", "GB"];
        const i = Math.floor(Math.log(bytes) / Math.log(k));
        return parseFloat((bytes / Math.pow(k, i)).toFixed(dm)) + " " + sizes[i];
    }
});
