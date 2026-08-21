#!/bin/bash
set -euo pipefail

APP_NAME="Pari"
EXECUTABLE="OpenLocalPhraserV2"
BUNDLE_ID="com.tejas.openlocalphraser"
APP_VERSION="0.3.0"
ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
FRONTEND_DIST="$ROOT_DIR/dist"
PACKAGING_DIR="$ROOT_DIR/.mac-build"
BUILD_DIR="$PACKAGING_DIR/build"
STAGING_DIR="$PACKAGING_DIR/staging"
ARTIFACT_DIR="$ROOT_DIR/release"
DMG_OUTPUT="$ARTIFACT_DIR/$APP_NAME.dmg"
APP_OUTPUT="$ARTIFACT_DIR/$APP_NAME.app"

APP_DIR="$APP_OUTPUT"
CONTENTS_DIR="$APP_DIR/Contents"
MACOS_DIR="$CONTENTS_DIR/MacOS"
RESOURCES_DIR="$CONTENTS_DIR/Resources"
WEB_DIR="$RESOURCES_DIR/web"
NATIVE_RUNTIME_DIR="$ROOT_DIR/native-runtime"

echo "==> Installing frontend dependencies"
cd "$ROOT_DIR"
npm ci

echo "==> Building frontend"
npm run build

echo "==> Patching dist for file:// compatibility"
sed -i '' 's/<script type="module" crossorigin src/<script type="module" src/g' "$FRONTEND_DIST/index.html"

echo "==> Preparing app bundle"
rm -rf "$PACKAGING_DIR"
mkdir -p "$ARTIFACT_DIR"
rm -rf "$APP_OUTPUT" "$DMG_OUTPUT"
mkdir -p "$BUILD_DIR" "$MACOS_DIR" "$WEB_DIR"

echo "==> Compiling Swift wrapper"
/usr/bin/swiftc -O \
  -framework AppKit -framework Foundation -framework Network -framework WebKit \
  "$ROOT_DIR/Sources/OpenLocalPhraser/main.swift" \
  "$ROOT_DIR/Sources/OpenLocalPhraser/AgentStyleBackend.swift" \
  -o "$BUILD_DIR/$EXECUTABLE"

echo "==> Copying web bundle"
cp -R "$FRONTEND_DIST/." "$WEB_DIR/"

echo "==> Copying native paraphrase worker (model connects after install)"
mkdir -p "$RESOURCES_DIR/native-runtime"
cp "$NATIVE_RUNTIME_DIR/paraphrase_worker.py" "$RESOURCES_DIR/native-runtime/"

echo "==> Generating Pari app icon"
ICONSET_DIR="$BUILD_DIR/Pari.iconset"
/usr/bin/swift "$ROOT_DIR/scripts/generate-app-icon.swift" "$ICONSET_DIR"
/usr/bin/iconutil -c icns -o "$RESOURCES_DIR/Pari.icns" "$ICONSET_DIR"

echo "==> Writing Info.plist"
cat > "$CONTENTS_DIR/Info.plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
 "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleExecutable</key>
    <string>$EXECUTABLE</string>
    <key>CFBundleIdentifier</key>
    <string>$BUNDLE_ID</string>
    <key>CFBundleName</key>
    <string>$APP_NAME</string>
    <key>CFBundleDisplayName</key>
    <string>$APP_NAME</string>
    <key>CFBundleIconFile</key>
    <string>Pari.icns</string>
    <key>CFBundleVersion</key>
    <string>$APP_VERSION</string>
    <key>CFBundleShortVersionString</key>
    <string>$APP_VERSION</string>
    <key>CFBundlePackageType</key>
    <string>APPL</string>
    <key>LSMinimumSystemVersion</key>
    <string>13.0</string>
    <key>NSHighResolutionCapable</key>
    <true/>
    <key>NSPrincipalClass</key>
    <string>NSApplication</string>
</dict>
</plist>
EOF

cp "$BUILD_DIR/$EXECUTABLE" "$MACOS_DIR/"

echo "==> Ad-hoc signing"
codesign --force --deep --sign - "$APP_OUTPUT"

echo "==> Creating DMG"
DMG_STAGING="$PACKAGING_DIR/dmg-staging"
rm -rf "$DMG_STAGING"
mkdir -p "$DMG_STAGING"
cp -cR "$APP_OUTPUT" "$DMG_STAGING/" 2>/dev/null || cp -R "$APP_OUTPUT" "$DMG_STAGING/"
ln -s /Applications "$DMG_STAGING/Applications"
rm -f "$DMG_OUTPUT"

hdiutil create \
  -volname "$APP_NAME" \
  -srcfolder "$DMG_STAGING" \
  -ov -format UDZO \
  -imagekey zlib-level=9 \
  "$DMG_OUTPUT"

echo "==> Done: $DMG_OUTPUT"
echo "==> App bundle: $APP_OUTPUT"

rm -rf "$PACKAGING_DIR"
