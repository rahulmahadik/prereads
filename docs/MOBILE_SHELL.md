# Mobile shell (later): load the web app in a WebView

The web app is built to be wrapped as-is. Recommended wrapper: Capacitor (one codebase,
iOS + Android, WebView with native plugins when you need them).

## What the web app already does for the shell

- Responsive from 360px phones to desktop; no horizontal page scroll (only the line scrolls)
- `viewport-fit=cover` + safe-area padding, so notches and home bars are respected
- PWA manifest + icons (`frontend/public/`) — also usable as an installable web app today
- Camera: the Scan button uses `<input type="file" accept="image/*" capture="environment">`,
  which opens the camera in iOS WKWebView and Android WebView (Android needs the
  `WebChromeClient.onShowFileChooser` hook, which Capacitor provides)
- Downloads: WebViews often ignore `a.download`, so the share card also renders inline
  with a "press and hold to save" hint
- Remote API: build with `VITE_API_BASE=https://your-api.example.com npm run build`
  when the shell loads the bundle from the app itself rather than from the server

## Capacitor in 10 minutes (when you get there)

```bash
cd frontend
npm i @capacitor/core @capacitor/cli && npx cap init PreReads sg.prereads.app --web-dir dist
VITE_API_BASE=https://your-api.example.com npm run build
npx cap add ios && npx cap add android && npx cap sync
npx cap open ios   # or android
```

Options:
- Simplest: point the shell at the hosted site — in `capacitor.config.ts` set
  `server: { url: "https://your-app.example.com" }` (and `cleartext: true` only for LAN dev).
- Offline-capable: ship `dist/` inside the app (default) and set `VITE_API_BASE` to the API.

## Permissions to declare

- iOS `Info.plist`: `NSCameraUsageDescription` ("Scan a book cover to find its reading line"),
  `NSPhotoLibraryAddUsageDescription` if you add native save-to-photos.
- Android: `CAMERA` permission; Capacitor handles the file-chooser bridge.

## Not needed yet

Push notifications, native storage, deep links. If you add them later, keep all logic in
the web app and use Capacitor plugins only as thin bridges.
