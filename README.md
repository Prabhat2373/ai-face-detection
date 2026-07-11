# RTSP Face Detection

Production-ready Node.js 22 + TypeScript service that consumes an RTSP CCTV stream with FFmpeg, processes frames in memory, and uses a Python face-embedding service for detection and identity matching when you want the strongest accuracy.

## Features

- Express REST API
- FFmpeg RTSP ingestion through `stdout`, with no continuous frame writes
- In-memory MJPEG frame processing
- Worker-thread fallback detection for the Node path
- Python InsightFace backend for stronger detection and matching
- Backend face registry for known-face registration and matching
- Attendance CSV export with first and last appearance timestamps
- Snapshot saved only on detection
- 10-second duplicate detection cooldown
- Detection timestamp and confidence logging
- Graceful shutdown
- Docker and Docker Compose support

## Requirements

- Node.js 22+
- FFmpeg available on `PATH`
- For the Python backend: Python 3.11+ with the `insightface` model downloads available at runtime

## Configuration

Copy `.env.example` to `.env` and update values:

```bash
SNAPSHOT_PATH=./snapshots
DETECTION_THRESHOLD=0.75
MATCH_THRESHOLD=0.45
STREAM_FRAME_RATE=10
FRAME_RATE=2
PORT=3000
LOG_LEVEL=info
```

Required variables:

- `SNAPSHOT_PATH`: Directory where detection snapshots are saved. Defaults to `./snapshots`.
- `DETECTION_THRESHOLD`: Minimum face confidence from `0` to `1`. Defaults to `0.75`.
- `MATCH_THRESHOLD`: Minimum descriptor similarity for a known-face match. Defaults to `0.45`.
- `STREAM_FRAME_RATE`: FPS used for the browser preview stream. Defaults to `10`.
- `FRAME_RATE`: Detection sampling rate in FPS. Defaults to `2`.
- `RECOGNITION_BACKEND`: Set to `python` for the stronger Python recognition path. Defaults to `node`.
- `PYTHON_RECOGNIZER_URL`: URL of the Python recognizer service. Defaults to `http://localhost:5055`.
- `PYTHON_DETECTION_THRESHOLD`: Detection confidence threshold used by InsightFace. Defaults to `0.5`.
- `PYTHON_MATCH_THRESHOLD`: Match threshold used by InsightFace embeddings. Defaults to `0.45`.
- `PYTHON_DB_PATH`: SQLite database path used by the Python service. Defaults to `./data/app.db`.
- `SYNC_ENABLED`: Enables background sync attempts from the edge agent. Defaults to `false`.
- `SYNC_ENDPOINT_URL`: VPS endpoint that receives batched edge events.
- `SYNC_INTERVAL_MS`: Retry interval for the sync loop. Defaults to `5000`.
- `AGENT_VERSION`: Current edge agent version string.
- `AUTO_UPDATE_URL`: Optional version-check endpoint for the updater.
- `AUTO_UPDATE_INTERVAL_MS`: Update polling interval in milliseconds. Defaults to `60000`.

## Install

```bash
npm install
npm run build
npm start
```

For development:

```bash
npm run dev
```

For the Python recognizer:

```bash
cd python_recognizer
pip install -r requirements.txt
uvicorn app:app --host 0.0.0.0 --port 5055
```

## API

### `GET /health`

Returns service health.

```json
{
  "ok": true,
  "uptime": 12.3
}
```

### `GET /status`

Returns stream and detector status.

### `POST /start`

Starts RTSP ingestion and face detection.

### `POST /stop`

Stops RTSP ingestion and face detection.

### `GET /faces`

Lists registered known faces.

### `POST /faces/register`

Registers the face currently visible in the stream for the provided label.

### `POST /faces/clear`

Removes all registered faces.

### `GET /attendance`

Returns the current attendance rows from SQLite.

## Python backend

The Python service uses InsightFace to do the actual face detection and embedding-based matching. Cameras, faces, and attendance all live in SQLite so the system keeps working offline.

When `RECOGNITION_BACKEND=python`, Node sends sampled camera frames to the Python service, which returns face boxes, identities, and snapshots.
Camera definitions are managed through the Python service's `/cameras` endpoints and are stored in the SQLite database, so new cameras can be added, disabled, or updated without redeploying the app.

### Database reset utility

You can clear the whole SQLite database or specific tables with the helper script:

```bash
python3 scripts/db_admin.py --all
python3 scripts/db_admin.py --table cameras
python3 scripts/db_admin.py --tables cameras,attendance_records
python3 scripts/db_admin.py --drop-file
```

From npm:

```bash
npm run db:clear -- --table cameras
npm run db:wipe
```

## Packaging

See [packaging/README.md](/Users/prabhattambe/Documents/face_detection/packaging/README.md) for the Windows and macOS service scaffolding.

## Docker

```bash
docker compose up --build
```

Snapshots are persisted to `./snapshots` on the host.

## Notes

- Frames are streamed from FFmpeg as MJPEG over a pipe and are not continuously saved to disk.
- The browser preview stream runs faster than the detector so the video feels smoother.
- Detection runs in `worker_threads`.
- If detection is slower than the camera feed, new frames are dropped while the worker is busy to prevent memory buildup.
- A detected face starts a 10-second cooldown before another snapshot can be saved.
