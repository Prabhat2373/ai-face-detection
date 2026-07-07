import { EventEmitter } from "node:events";

type JpegFrameExtractorEvents = {
  frame: [Buffer];
  warning: [Error];
};

export declare interface JpegFrameExtractor {
  on<K extends keyof JpegFrameExtractorEvents>(
    event: K,
    listener: (...args: JpegFrameExtractorEvents[K]) => void,
  ): this;
  emit<K extends keyof JpegFrameExtractorEvents>(
    event: K,
    ...args: JpegFrameExtractorEvents[K]
  ): boolean;
}

export class JpegFrameExtractor extends EventEmitter {
  private buffer = Buffer.alloc(0);

  public constructor(private readonly maxFrameBytes: number) {
    super();
  }

  public push(chunk: Buffer): void {
    this.buffer = Buffer.concat([this.buffer, chunk]);

    while (this.buffer.length > 0) {
      const start = this.buffer.indexOf(Buffer.from([0xff, 0xd8]));
      if (start === -1) {
        this.buffer = Buffer.alloc(0);
        return;
      }

      if (start > 0) {
        this.buffer = this.buffer.subarray(start);
      }

      const end = this.buffer.indexOf(Buffer.from([0xff, 0xd9]), 2);
      if (end === -1) {
        if (this.buffer.length > this.maxFrameBytes) {
          this.buffer = Buffer.alloc(0);
          this.emit("warning", new Error("Dropped oversized incomplete JPEG frame"));
        }
        return;
      }

      const frame = this.buffer.subarray(0, end + 2);
      this.buffer = this.buffer.subarray(end + 2);
      this.emit("frame", Buffer.from(frame));
    }
  }

  public reset(): void {
    this.buffer = Buffer.alloc(0);
  }
}
