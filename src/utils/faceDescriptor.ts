import jpeg from "jpeg-js";
import type { DetectedFace } from "../detector/types.js";

const DESCRIPTOR_SIZE = 32;
const DESCRIPTOR_LENGTH = DESCRIPTOR_SIZE * DESCRIPTOR_SIZE;

export function buildFaceDescriptor(
  frame: Buffer,
  box: DetectedFace["box"],
): Float32Array | null {
  const decoded = jpeg.decode(frame, { useTArray: true });
  if (!decoded.width || !decoded.height || !decoded.data) {
    return null;
  }
  const data = decoded.data as Uint8Array;

  const crop = getCropBounds(decoded.width, decoded.height, box);
  if (!crop) {
    return null;
  }

  const descriptor = new Float32Array(DESCRIPTOR_LENGTH);
  let cursor = 0;
  let sum = 0;

  for (let y = 0; y < DESCRIPTOR_SIZE; y += 1) {
    const sampleY = crop.y + ((y + 0.5) * crop.height) / DESCRIPTOR_SIZE;
    const sourceY = clamp(Math.floor(sampleY), 0, decoded.height - 1);

    for (let x = 0; x < DESCRIPTOR_SIZE; x += 1) {
      const sampleX = crop.x + ((x + 0.5) * crop.width) / DESCRIPTOR_SIZE;
      const sourceX = clamp(Math.floor(sampleX), 0, decoded.width - 1);
      const offset = (sourceY * decoded.width + sourceX) * 4;
      const r = data[offset] ?? 0;
      const g = data[offset + 1] ?? 0;
      const b = data[offset + 2] ?? 0;
      const luminance = (0.299 * r + 0.587 * g + 0.114 * b) / 255;
      descriptor[cursor] = luminance;
      sum += luminance;
      cursor += 1;
    }
  }

  const mean = sum / descriptor.length;
  let squared = 0;

  for (let index = 0; index < descriptor.length; index += 1) {
    const value = descriptor[index] ?? 0;
    const centered = value - mean;
    descriptor[index] = centered;
    squared += centered * centered;
  }

  const norm = Math.sqrt(squared) || 1;
  for (let index = 0; index < descriptor.length; index += 1) {
    descriptor[index] = (descriptor[index] ?? 0) / norm;
  }

  return descriptor;
}

export function compareDescriptors(
  left: Float32Array,
  right: Float32Array,
): number {
  const length = Math.min(left.length, right.length);
  let score = 0;

  for (let index = 0; index < length; index += 1) {
    score += (left[index] ?? 0) * (right[index] ?? 0);
  }

  return score;
}

function getCropBounds(
  imageWidth: number,
  imageHeight: number,
  box: DetectedFace["box"],
): { x: number; y: number; width: number; height: number } | null {
  const centerX = box.x + box.width / 2;
  const centerY = box.y + box.height / 2;
  const side = Math.max(box.width, box.height) * 1.35;

  if (!Number.isFinite(side) || side <= 0) {
    return null;
  }

  const x = clamp(Math.round(centerX - side / 2), 0, imageWidth - 1);
  const y = clamp(Math.round(centerY - side / 2), 0, imageHeight - 1);
  const width = clamp(Math.round(side), 1, imageWidth - x);
  const height = clamp(Math.round(side), 1, imageHeight - y);

  if (width <= 0 || height <= 0) {
    return null;
  }

  return { x, y, width, height };
}

function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}
