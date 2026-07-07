import type { NextFunction, Request, Response } from "express";
export declare function asyncHandler(handler: (req: Request, res: Response, next: NextFunction) => Promise<void>): (req: Request, res: Response, next: NextFunction) => void;
