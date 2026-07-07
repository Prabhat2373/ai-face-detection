import type { DetectedFace } from "../detector/types.js";
export declare function buildFaceDescriptor(frame: Buffer, box: DetectedFace["box"]): Float32Array | null;
export declare function compareDescriptors(left: Float32Array, right: Float32Array): number;
