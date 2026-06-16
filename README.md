# TikTok Video Metadata Patcher Web Tool

A lightweight, self-hosted web tool designed for deployment on a VPS to bypass TikTok's aggressive compression algorithms by remuxing MP4 files and applying a binary structural patch, mirroring the exact process of the original `patcher.py` script.

---

## How It Works

The tool modifies MP4 containers using two distinct phases:

1. **FFmpeg Remuxing (Lossless)**: 
   * Strips all old container metadata (dates, software identifiers).
   * Sets the container brand to generic ISO Base Media (`isom`).
   * Configures compatible brands to match standard TikTok playback formats (`isomiso2avc1mp41`).
   * Injects customized metadata tags:
     * `comment`: `Patched by @custom_tag - 120fps Optimized`
     * `encoder`: `Lavf60.16.100`
     * `title`: `fixed_by_custom_tag`
   * Shifts the `moov` atom to the front of the file (`faststart`) for instant web playback.

2. **Binary Structural Patching**:
   * Parses the top-level MP4 container atoms to locate the media data (`mdat`) segment.
   * Increments the declared size byte of the `mdat` atom header by exactly **1 byte**.
   * *Result*: TikTok's ingestion engines encounter an invalid trailer and bypass the re-encoding compression process, while standard video player engines ignore the 1-byte overflow and play back the original, high-quality stream directly.

---

## Features

* 💎 **Premium Glassmorphic UI**: Beautiful responsive design in dark mode matching TikTok's cyan-magenta branding.
* 📂 **Drag & Drop Upload**: Streamlined drag-and-drop or file-click explorer interface supporting files up to 500MB (configurable).
* 📈 **Real-time Progress Tracking**: Integrates upload progress percentage with step-by-step visual feedback (Uploading -> Remuxing -> Patching -> Completed).
* ⬇️ **Auto-triggered Downloads**: Once patching finishes, the browser automatically downloads the modified video with the correct filename.
* 🧹 **Auto-Cleanup**: Fully stateless design. Uploaded videos and temporary outputs are processed on-disk and immediately swept/deleted by the FastAPI backend in an asynchronous background thread.

---

## Deployment Guide (VPS)

### Prerequisites
* **Docker** installed on your VPS.
* **Docker Compose** installed.

### Option A: Using Docker Compose (Recommended)

1. Clone or upload the project files to a directory on your VPS (e.g., `/opt/tiktok-patcher`).
2. Run the following command from the project root:
   ```bash
   docker compose up -d --build
   ```
3. The application will build the container, install FFmpeg, and start the service on port `8000`.

### Option B: Using Standalone Docker CLI

Build and run the container manually:
```bash
# Build the image
docker build -t tiktok-patcher .

# Run the container
docker run -d \
  --name tiktok-patcher \
  -p 8000:8000 \
  --restart unless-stopped \
  tiktok-patcher
```

---

## Configuration

You can customize the container's behavior by passing environment variables:

| Environment Variable | Default Value | Description |
|----------------------|---------------|-------------|
| `MAX_UPLOAD_SIZE_MB` | `500`         | The maximum permitted upload file size in megabytes. |
| `TEMP_DIR`           | `/app/temp_processing` | Directory inside the container where files are temporarily held. |

### Example with custom size limit (e.g., 200MB):
In `docker-compose.yml`:
```yaml
environment:
  - MAX_UPLOAD_SIZE_MB=200
```

---

## Nginx Reverse Proxy Setup (Optional)

To serve the app securely under your own domain name (e.g., `patcher.yourdomain.com`) with SSL, use the following Nginx block. 

*Note: You must raise Nginx's upload limit (`client_max_body_size`) to match your app configuration.*

```nginx
server {
    listen 80;
    server_name patcher.yourdomain.com;

    # Match the max upload limit (e.g. 500M)
    client_max_body_size 500M;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        
        # Disable buffering to avoid disk writes on large uploads
        proxy_request_buffering off;
        proxy_buffering off;
    }
}
```
