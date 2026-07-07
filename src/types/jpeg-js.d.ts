declare module "jpeg-js" {
  export type DecodeOptions = {
    colorTransform?: boolean;
    useTArray?: boolean;
    formatAsRGBA?: boolean;
    tolerantDecoding?: boolean;
    maxMemoryUsageInMB?: number;
    maxResolutionInMP?: number;
  };

  export type RawImageData = {
    width: number;
    height: number;
    data: Uint8Array | Buffer;
  };

  export function decode(buffer: Buffer | Uint8Array, options?: DecodeOptions): RawImageData;

  const jpeg: {
    decode: typeof decode;
  };

  export default jpeg;
}
