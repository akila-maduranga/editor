import os
import uuid
import logging
from fastapi import FastAPI, UploadFile, File, Form, HTTPException, BackgroundTasks, Request, status
from starlette.background import BackgroundTask
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from backend.patcher import patch_video

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger("tiktok_patcher")

app = FastAPI(
    title="TikTok Video Metadata Patcher",
    description="A web tool to patch MP4 metadata and bypass TikTok's compression."
)

# Enable CORS for local development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Settings from Environment Variables
MAX_UPLOAD_SIZE_MB = int(os.getenv("MAX_UPLOAD_SIZE_MB", "500"))
MAX_FILE_SIZE = MAX_UPLOAD_SIZE_MB * 1024 * 1024  # default 500MB in bytes
TEMP_DIR = os.getenv("TEMP_DIR", os.path.join(os.getcwd(), "temp_processing"))

# Ensure temp directory exists
os.makedirs(TEMP_DIR, exist_ok=True)

def cleanup_files(*paths):
    """Safely removes files after response is completed."""
    for path in paths:
        if path and os.path.exists(path):
            try:
                os.remove(path)
                logger.info(f"🗑️ Cleaned up temporary file: {path}")
            except Exception as e:
                logger.warning(f"⚠️ Error cleaning up file {path}: {e}")

@app.get("/", response_class=HTMLResponse)
async def get_index():
    """Serves the main application page."""
    index_path = os.path.join(os.getcwd(), "frontend", "static", "index.html")
    if not os.path.exists(index_path):
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, 
            detail="Frontend index.html not found on server."
        )
    with open(index_path, "r", encoding="utf-8") as f:
        return f.read()

@app.post("/api/patch")
async def api_patch_video(
    request: Request,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    custom_tag: str = Form("@akila"),
    encode_1080p: bool = Form(False)
):
    """
    Uploads a video, runs the patcher script, and returns the patched output.
    Cleans up temp files asynchronously after sending the response.
    """
    # 1. Validate content length header (fast check)
    content_length = request.headers.get("content-length")
    if content_length and int(content_length) > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File too large. Maximum permitted size is {MAX_UPLOAD_SIZE_MB}MB."
        )

    # Validate file format (must be mp4)
    filename = file.filename or "video.mp4"
    if not filename.lower().endswith(".mp4"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid file format. Only MP4 (.mp4) videos are supported."
        )

    # 2. Save upload in chunks to enforce actual size limit on-the-fly and save memory
    job_id = str(uuid.uuid4())
    input_path = os.path.join(TEMP_DIR, f"input_{job_id}.mp4")
    output_path = os.path.join(TEMP_DIR, f"patched_{job_id}.mp4")
    
    total_written = 0
    try:
        with open(input_path, "wb") as buffer:
            while True:
                # Read in 1MB chunks
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                total_written += len(chunk)
                if total_written > MAX_FILE_SIZE:
                    buffer.close()
                    cleanup_files(input_path)
                    raise HTTPException(
                        status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                        detail=f"File too large. Maximum permitted size is {MAX_UPLOAD_SIZE_MB}MB."
                    )
                buffer.write(chunk)
    except Exception as e:
        cleanup_files(input_path)
        if isinstance(e, HTTPException):
            raise e
        logger.error(f"Error saving uploaded file: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to upload file: {str(e)}"
        )

    # 3. Apply the patch
    logger.info(f"⚡ Starting metadata patch for '{filename}' with tag '{custom_tag}' (Size: {total_written} bytes)")
    success, message = patch_video(input_path, output_path, custom_tag, encode_1080p)

    if not success:
        # Clean up input and return error
        cleanup_files(input_path, output_path)
        logger.error(f"Patching failed for '{filename}': {message}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Patching failed: {message}"
        )

    # 4. Schedule background cleanup of input file only (output cleaned after response)
    background_tasks.add_task(cleanup_files, input_path)

    # 5. Build friendly output filename
    base_name, ext = os.path.splitext(filename)
    download_filename = f"{base_name}_patched{ext}"

    logger.info(f"🎉 Patching complete. Sending file: {download_filename}")
    return FileResponse(
        path=output_path,
        filename=download_filename,
        media_type="video/mp4",
        background=BackgroundTask(cleanup_files, output_path)
    )

# Serve static files (styles, script, icons)
app.mount("/static", StaticFiles(directory=os.path.join("frontend", "static")), name="static")
