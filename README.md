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
- For the Python backend: Python 3.11+ with the bundled custom ONNX recognizer; no model download is required

## Configuration

Copy `.env.example` to `.env` and update values:

```bash
SNAPSHOT_PATH=./snapshots
DETECTION_THRESHOLD=0.75
MATCH_THRESHOLD=0.70
MATCH_MARGIN=0.10
STREAM_FRAME_RATE=10
FRAME_RATE=2
PORT=3000
LOG_LEVEL=info
```

Required variables:

- `SNAPSHOT_PATH`: Directory where detection snapshots are saved. Defaults to `./snapshots`.
- `DETECTION_THRESHOLD`: Minimum face confidence from `0` to `1`. Defaults to `0.75`.
- `MATCH_THRESHOLD`: Minimum descriptor similarity for a known-face match. Defaults to `0.70`.
- `MATCH_MARGIN`: Required score gap between the best and second-best employee. Defaults to `0.10`; ambiguous faces remain unknown.
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
- `SNAPSHOT_RETENTION_COUNT`: Maximum number of JPEG snapshots retained by the backend. Defaults to `5000`.
- `MIN_FACE_SIZE`: Minimum detected face width and height used for recognition. Defaults to `24` pixels. Lower values can detect more distant faces, but recognition becomes less reliable when the face has too few source pixels.
- `BACKUP_ENABLED`: Enables automatic SQLite backups. Defaults to `true`.
- `BACKUP_INTERVAL_SECONDS`: Time between automatic backups. Defaults to `86400` seconds.
- `BACKUP_RETENTION_COUNT`: Number of recent database backups to keep. Defaults to `7`.
- `BACKUP_PATH`: Optional backup directory. Defaults to the application data `backups` directory.
- `INFERENCE_WORKERS`: Number of central face-inference workers. Defaults to `1`; increase only when CPU capacity has been measured.
- `INFERENCE_QUEUE_SIZE`: Maximum queued inference frames. Defaults to `2`; stale work is dropped to prevent latency buildup.
- `MAX_INFERENCE_FRAME_AGE_MS`: Maximum age of a queued frame before it is discarded. Defaults to `1500`.
- `ALARM_UNKNOWN_CONFIRMATION_FRAMES`: Consecutive high-quality unknown observations required before an alarm. Defaults to `5` and cannot be lower than `3`.

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

### Training the custom recognizer

Training requires a public dataset arranged as `dataset/<identity>/<image>`.
Use `scripts/train_public_face_model.py` in a training-only environment:

```bash
python -m pip install -r training-requirements.txt
python scripts/train_public_face_model.py --dataset /path/to/identity-folder-dataset --epochs 25
python scripts/verify_offline_runtime.py
```

The script uses buffalo_l only to generate teacher embeddings during training; it is not included in the client runtime. Re-register local employees after exporting the model.

Public face datasets such as CelebA and many VGGFace/CASIA derivatives are commonly restricted to non-commercial research use. Obtain a license for any dataset used to train a commercial product, and do not redistribute restricted training images or weights without permission.


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
npm run db:backup
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
