import pino from "pino";
import { env } from "../config/env.js";
const logLevel = String(env.LOG_LEVEL || "info").trim() || "info";
export const logger = pino({
    level: logLevel,
    base: undefined,
    timestamp: pino.stdTimeFunctions.isoTime,
});
//# sourceMappingURL=logger.js.map