export function asyncHandler(handler) {
    return (req, res, next) => {
        void handler(req, res, next).catch(next);
    };
}
//# sourceMappingURL=asyncHandler.js.map