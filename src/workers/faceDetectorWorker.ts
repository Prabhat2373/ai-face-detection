import { mkdir, writeFile } from "node:fs/promises";
import { join } from "node:path";
import { parentPort, workerData } from "node:worker_threads";
import * as tf from "@tensorflow/tfjs";
import * as blazeface from "@tensorflow-models/blazeface";
import jpeg from "jpeg-js";
import type {
  DetectedFace,
  DetectionSnapshot,
  DetectorWorkerData,
  DetectorWorkerRequest,
  DetectorWorkerResponse,
} from "../detector/types.js";

const data = workerData as DetectorWorkerData;
let model: blazeface.BlazeFaceModel;
let lastDetectionAt = 0;

// async function bootstrap(): Promise<void> {
//   await mkdir(data.snapshotPath, { recursive: true });
//   await tf.ready();
//   console.log("Backend:", tf.getBackend());
//   model = await blazeface.load();
//   parentPort?.postMessage({ type: "ready" } satisfies DetectorWorkerResponse);
// }

async function bootstrap(): Promise<void> {
  try {
    parentPort?.postMessage({
      type: "state",
      value: "bootstrapping",
    } satisfies DetectorWorkerResponse);
    await mkdir(data.snapshotPath, { recursive: true });
    parentPort?.postMessage({
      type: "state",
      value: "loading tfjs backend",
    } satisfies DetectorWorkerResponse);
    await tf.ready();
    parentPort?.postMessage({
      type: "state",
      value: `backend ready: ${tf.getBackend()}`,
    } satisfies DetectorWorkerResponse);
    parentPort?.postMessage({
      type: "state",
      value: "loading blazeface model",
    } satisfies DetectorWorkerResponse);
    model = await blazeface.load();
    parentPort?.postMessage({
      type: "ready",
    } satisfies DetectorWorkerResponse);
  } catch (err) {
    parentPort?.postMessage({
      type: "state",
      value: err instanceof Error ? `${err.name}: ${err.message}` : String(err),
    } satisfies DetectorWorkerResponse);
    throw err;
  }
}

function postError(error: unknown, frameId?: number): void {
  const normalized = error instanceof Error ? error : new Error(String(error));
  parentPort?.postMessage({
    type: "error",
    frameId,
    message: normalized.message,
    stack: normalized.stack,
  } satisfies DetectorWorkerResponse);
}

async function detect(
  request: Extract<DetectorWorkerRequest, { type: "detect" }>,
): Promise<void> {
  const jpeg = Buffer.from(request.jpeg);
  const image = decodeJpegToTensor(jpeg);

  try {
    const predictions = await model.estimateFaces(image, false);
    const faces = predictions
      .map((prediction): DetectedFace => {
        const topLeft = prediction.topLeft as [number, number];
        const bottomRight = prediction.bottomRight as [number, number];
        const probability = prediction.probability as number[] | undefined;
        const confidence = probability?.[0] ?? 0;

        return {
          confidence,
          box: {
            x: topLeft[0],
            y: topLeft[1],
            width: bottomRight[0] - topLeft[0],
            height: bottomRight[1] - topLeft[1],
          },
        };
      })
      .filter((face) => face.confidence >= data.threshold)
      .sort((a, b) => b.confidence - a.confidence);

    let snapshot: DetectionSnapshot | undefined;
    const bestFace = faces[0];
    const now = Date.now();

    if (bestFace && now - lastDetectionAt >= data.cooldownMs) {
      lastDetectionAt = now;
      const timestamp = new Date(request.capturedAt);
      const filename = `face-${timestamp.toISOString().replace(/[:.]/g, "-")}-${request.frameId}.jpg`;
      const path = join(data.snapshotPath, filename);
      await writeFile(path, jpeg);
      snapshot = {
        path,
        timestamp: timestamp.toISOString(),
        confidence: bestFace.confidence,
      };
    }

    parentPort?.postMessage({
      type: "result",
      frameId: request.frameId,
      processedAt: new Date().toISOString(),
      faces,
      snapshot,
    } satisfies DetectorWorkerResponse);
  } finally {
    image.dispose();
  }
}

function decodeJpegToTensor(buffer: Buffer): tf.Tensor3D {
  const decoded = jpeg.decode(buffer, { useTArray: true });
  const rgb = new Uint8Array(decoded.width * decoded.height * 3);

  for (
    let source = 0, target = 0;
    source < decoded.data.length;
    source += 4, target += 3
  ) {
    rgb[target] = decoded.data[source] ?? 0;
    rgb[target + 1] = decoded.data[source + 1] ?? 0;
    rgb[target + 2] = decoded.data[source + 2] ?? 0;
  }

  return tf.tensor3d(rgb, [decoded.height, decoded.width, 3], "int32");
}

parentPort?.on("message", (message: DetectorWorkerRequest) => {
  if (message.type === "shutdown") {
    tf.disposeVariables();
    process.exit(0);
  }

  void detect(message).catch((error) => postError(error, message.frameId));
});

void bootstrap().catch((error) => {
  console.error("BOOTSTRAP ERROR");
  console.error(error);
  postError(error);
  process.exit(1);
});
