import { EventEmitter } from "node:events";
export class JpegFrameExtractor extends EventEmitter {
    maxFrameBytes;
    buffer = Buffer.alloc(0);
    constructor(maxFrameBytes) {
        super();
        this.maxFrameBytes = maxFrameBytes;
    }
    push(chunk) {
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
    reset() {
        this.buffer = Buffer.alloc(0);
    }
}
//# sourceMappingURL=jpegFrameExtractor.js.map