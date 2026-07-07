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
- An RTSP camera URL
- For the Python backend: Python 3.11+ with the `insightface` model downloads available at runtime

## Configuration

Copy `.env.example` to `.env` and update values:

```bash
RTSP_URL=rtsp://user:password@camera-host:554/stream1
SNAPSHOT_PATH=./snapshots
DETECTION_THRESHOLD=0.75
MATCH_THRESHOLD=0.45
STREAM_FRAME_RATE=10
FRAME_RATE=2
PORT=3000
LOG_LEVEL=info
```

Required variables:

- `RTSP_URL`: CCTV RTSP stream URL.
- `RTSP_USERNAME` and `RTSP_PASSWORD`: optional credentials if your camera prompts for login in VLC.
- `SNAPSHOT_PATH`: Directory where detection snapshots are saved. Defaults to `./snapshots`.
- `DETECTION_THRESHOLD`: Minimum face confidence from `0` to `1`. Defaults to `0.75`.
- `MATCH_THRESHOLD`: Minimum descriptor similarity for a known-face match. Defaults to `0.45`.
- `STREAM_FRAME_RATE`: FPS used for the browser preview stream. Defaults to `10`.
- `FRAME_RATE`: Detection sampling rate in FPS. Defaults to `2`.
- `RECOGNITION_BACKEND`: Set to `python` for the stronger Python recognition path. Defaults to `node`.
- `PYTHON_RECOGNIZER_URL`: URL of the Python recognizer service. Defaults to `http://localhost:5055`.
- `PYTHON_DETECTION_THRESHOLD`: Detection confidence threshold used by InsightFace. Defaults to `0.5`.
- `PYTHON_MATCH_THRESHOLD`: Match threshold used by InsightFace embeddings. Defaults to `0.45`.

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

Returns the current attendance rows. The same data is also written to `./snapshots/attendance.csv`.

## Python backend

The Python service uses InsightFace to do the actual face detection and embedding-based matching. That is the path to use if you want the most robust recognition for changing light, angle, and partial occlusion.

When `RECOGNITION_BACKEND=python`, Node sends sampled camera frames to the Python service, which returns face boxes, identities, and snapshots.

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
