import { EventEmitter } from "node:events";
type JpegFrameExtractorEvents = {
    frame: [Buffer];
    warning: [Error];
};
export declare interface JpegFrameExtractor {
    on<K extends keyof JpegFrameExtractorEvents>(event: K, listener: (...args: JpegFrameExtractorEvents[K]) => void): this;
    emit<K extends keyof JpegFrameExtractorEvents>(event: K, ...args: JpegFrameExtractorEvents[K]): boolean;
}
export declare class JpegFrameExtractor extends EventEmitter {
    private readonly maxFrameBytes;
    private buffer;
    constructor(maxFrameBytes: number);
    push(chunk: Buffer): void;
    reset(): void;
}
export {};
