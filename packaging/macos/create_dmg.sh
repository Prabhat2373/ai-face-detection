#!/usr/bin/env bash
#
# create_dmg.sh - Create a DMG from a macOS .app bundle, optionally codesign and notarize.
#
# Usage:
#   ./create_dmg.sh --app path/to/FaceAgent.app --out path/to/FaceAgent.dmg [options]
#
# Features:
#  - Optional code signing via `codesign`
#  - Optional notarization via `xcrun notarytool` (preferred) or `altool` (fallback)
#  - Creation of a compressed DMG via `hdiutil`
#  - Optionally use `create-dmg` for a polished DMG layout if available
#  - Verification step mounts the DMG and checks the app is present
#
# Notes:
#  - Run this script on macOS.
#  - Code signing and notarization require an Apple Developer account and keys/certs.
#  - For automated notarization, using an App Store Connect API key and `notarytool` is recommended.
#
# Examples:
#  - Basic DMG (no signing/notarize):
#      ./create_dmg.sh --app dist/FaceAgent.app --out dist/FaceAgent.dmg
#
#  - Sign and DMG:
#      ./create_dmg.sh --app dist/FaceAgent.app --out dist/FaceAgent.dmg --sign-identity "Developer ID Application: ACME, Inc. (TEAMID)"
#
#  - Sign and Notarize using notarytool:
#      ./create_dmg.sh --app dist/FaceAgent.app --out dist/FaceAgent.dmg \
#          --sign-identity "Developer ID Application: ACME (TEAMID)" \
#          --notarize --apple-id "me@company.com" --apple-password "@keychain:AC_PASSWORD"
#
set -euo pipefail

# Defaults
APP_PATH=""
OUT_DMG=""
SIGN_IDENTITY=""
NOTARIZE=false
APPLE_ID=""
APPLE_PASSWORD=""
VOLUME_NAME="FaceAgent"
BACKGROUND=""
VERBOSE=0
DRY_RUN=false
USE_CREATE_DMG=false

# Helpers ---------------------------------------------------------------------

usage() {
    cat <<EOF
create_dmg.sh - Build a .dmg from a macOS .app, optionally codesign and notarize.

Usage:
  $0 --app <path to .app> --out <path to .dmg> [options]

Required:
  --app <path>         Path to the .app bundle (e.g. dist/FaceAgent.app)
  --out <path>         Path to output DMG (e.g. dist/FaceAgent.dmg)

Options:
  --sign-identity "ID"   Code signing identity (e.g. "Developer ID Application: Name (TEAMID)")
  --notarize             Submit to Apple notarization service (requires --apple-id and --apple-password)
  --apple-id ID          Apple ID (for notarization)
  --apple-password PASS  Apple app-specific password or keychain reference (e.g. @keychain:AC_PASSWORD)
  --volume-name NAME     Volume name shown when DMG is mounted (default: FaceAgent)
  --background FILE      Background image for DMG window (optional; used by create-dmg)
  --use-create-dmg       Use `create-dmg` tool for polished DMG layout if available
  --verbose              Verbose logging
  --dry-run              Show steps but don't execute external commands
  --help                 Show this message

Examples:
  # Basic DMG (no signing/notarize)
  $0 --app dist/FaceAgent.app --out dist/FaceAgent.dmg

  # Sign and DMG
  $0 --app dist/FaceAgent.app --out dist/FaceAgent.dmg --sign-identity "Developer ID Application: ACME, Inc. (TEAMID)"

  # Sign and notarize (notarytool)
  $0 --app dist/FaceAgent.app --out dist/FaceAgent.dmg --sign-identity "Developer ID Application: ..." --notarize --apple-id "me@company.com" --apple-password "@keychain:AC_PASSWORD"
EOF
    exit 1
}

log() {
    if [ "$VERBOSE" -gt 0 ]; then
        echo "[`date '+%Y-%m-%d %H:%M:%S'`] $*"
    else
        echo "$*"
    fi
}

run_cmd() {
    if [ "$DRY_RUN" = true ]; then
        echo "[DRY-RUN] $*"
        return 0
    fi
    eval "$@"
}

# Argument parsing -----------------------------------------------------------

while [ $# -gt 0 ]; do
    case "$1" in
        --app) APP_PATH="$2"; shift 2 ;;
        --out) OUT_DMG="$2"; shift 2 ;;
        --sign-identity) SIGN_IDENTITY="$2"; shift 2 ;;
        --notarize) NOTARIZE=true; shift 1 ;;
        --apple-id) APPLE_ID="$2"; shift 2 ;;
        --apple-password) APPLE_PASSWORD="$2"; shift 2 ;;
        --volume-name) VOLUME_NAME="$2"; shift 2 ;;
        --background) BACKGROUND="$2"; shift 2 ;;
        --use-create-dmg) USE_CREATE_DMG=true; shift 1 ;;
        --verbose) VERBOSE=1; shift 1 ;;
        --dry-run) DRY_RUN=true; shift 1 ;;
        --help) usage ;;
        *) echo "Unknown argument: $1"; usage ;;
    esac
done

if [ -z "$APP_PATH" ] || [ -z "$OUT_DMG" ]; then
    echo "Error: --app and --out are required."
    usage
fi

if [ ! -d "$APP_PATH" ]; then
    echo "Error: app bundle not found at: $APP_PATH"
    exit 2
fi

if [ "$NOTARIZE" = true ]; then
    if [ -z "$APPLE_ID" ] || [ -z "$APPLE_PASSWORD" ]; then
        echo "Error: notarization requested but --apple-id or --apple-password missing."
        exit 3
    fi
fi

# Make absolute paths
APP_PATH="$(cd "$(dirname "$APP_PATH")" && pwd)/$(basename "$APP_PATH")"
OUT_DMG="$(cd "$(dirname "$OUT_DMG")" && pwd)/$(basename "$OUT_DMG")"

# Create temporary workspace
TMPDIR="$(mktemp -d "/tmp/faceagent_dmg.XXXXXX")"
trap 'rm -rf "$TMPDIR"' EXIT

STAGING_DIR="$TMPDIR/staging"
mkdir -p "$STAGING_DIR"

# Signing --------------------------------------------------------------------

if [ -n "$SIGN_IDENTITY" ]; then
    log "Codesigning $APP_PATH with identity: $SIGN_IDENTITY"
    # Use hardened runtime and runtime options where appropriate
    CMD="codesign --timestamp --options runtime --deep --force --verbose --sign \"$SIGN_IDENTITY\" \"$APP_PATH\""
    run_cmd "$CMD"

    # Verify signature
    CMD="codesign --verify --deep --strict --verbose=2 \"$APP_PATH\""
    if ! run_cmd "$CMD"; then
        echo "Warning: codesign verification failed (see output). Continuing..."
    fi
else
    log "Skipping codesign (no identity provided)."
fi

# Notarization ----------------------------------------------------------------
# Prefer notarytool when available; otherwise fallback to altool.
NOTARY_TOOL="$(command -v xcrun >/dev/null 2>&1 && xcrun notarytool --help >/dev/null 2>&1 && echo "notarytool" || true || true)"

if [ "$NOTARIZE" = true ]; then
    log "Preparing app for notarization (this may take several minutes)..."

    ZIP_PATH="$TMPDIR/$(basename "$APP_PATH").zip"
    log "Zipping app to $ZIP_PATH"
    run_cmd "ditto -c -k --sequesterRsrc --keepParent \"$APP_PATH\" \"$ZIP_PATH\""

    if command -v xcrun >/dev/null 2>&1 && xcrun notarytool --help >/dev/null 2>&1; then
        # Use notarytool
        log "Submitting to Apple notarization service via xcrun notarytool..."
        # Note: notarytool supports API key-based authentication or Apple ID
        # For this script we assume Apple ID and password (app-specific) are provided.
        CMD="xcrun notarytool submit \"$ZIP_PATH\" --apple-id \"$APPLE_ID\" --password \"$APPLE_PASSWORD\" --wait"
        run_cmd "$CMD"
        log "Stapling notarization ticket to the app..."
        run_cmd "xcrun stapler staple \"$APP_PATH\""
    else
        # Fallback to altool (deprecated)
        log "xcrun notarytool not available; falling back to altool (deprecated)."
        CMD="xcrun altool --notarize-app -f \"$ZIP_PATH\" --primary-bundle-id \"com.faceagent.app\" -u \"$APPLE_ID\" -p \"$APPLE_PASSWORD\""
        run_cmd "$CMD"
        log "Note: altool submission may require polling for completion. This script does not implement full polling for altool."
        # Attempt to staple (may fail if notarization not complete)
        run_cmd "xcrun stapler staple \"$APP_PATH\" || true"
    fi
else
    log "Notarization not requested; skipping."
fi

# Prepare DMG contents -------------------------------------------------------
log "Preparing staging folder for DMG..."
cp -R "$APP_PATH" "$STAGING_DIR/"

# Optionally add a symlink to /Applications for convenient drag-and-drop install
ln -s /Applications "$STAGING_DIR/Applications" || true

# If create-dmg is requested and available, use it for a polished DMG
if [ "$USE_CREATE_DMG" = true ] && command -v create-dmg >/dev/null 2>&1; then
    log "create-dmg is available and requested; using it to build a polished DMG."

    CREATE_DMG_CMD=(create-dmg
        --volname "$VOLUME_NAME"
        --window-size 660 400
        --icon-size 120
        --icon "$(basename "$APP_PATH")" 140 200
        --app-drop-link
        "$STAGING_DIR"
        "$OUT_DMG"
    )

    # Optionally include a background if provided
    if [ -n "$BACKGROUND" ] && [ -f "$BACKGROUND" ]; then
        CREATE_DMG_CMD+=(--background "$BACKGROUND")
    fi

    run_cmd "${CREATE_DMG_CMD[@]}"
    log "DMG created at: $OUT_DMG"
    exit 0
fi

# Basic DMG creation with hdiutil
log "Creating compressed DMG using hdiutil..."
run_cmd "hdiutil create -volname \"$VOLUME_NAME\" -srcfolder \"$STAGING_DIR\" -ov -format UDZO \"$OUT_DMG\""
log "DMG created: $OUT_DMG"

# Verification: mount DMG and ensure app is present
if [ "$DRY_RUN" = false ]; then
    log "Verifying DMG by mounting..."
    MOUNT_OUTPUT="$(hdiutil attach -nobrowse -noverify -noautoopen "$OUT_DMG")"
    if [ $? -ne 0 ]; then
        log "WARNING: failed to attach DMG for verification."
    else
        # Extract mount point from output (last column)
        MOUNT_POINT="$(echo "$MOUNT_OUTPUT" | awk '{print $3}' | head -n 1)"
        if [ -d "$MOUNT_POINT/$(basename "$APP_PATH")" ]; then
            log "Verification OK: app present in DMG."
        else
            log "Warning: app not found in mounted DMG at $MOUNT_POINT"
        fi
        run_cmd "hdiutil detach \"$MOUNT_POINT\" -quiet || true"
    fi
fi

log "DMG creation workflow complete."

exit 0
