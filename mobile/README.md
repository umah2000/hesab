# NEXTCAM ویزیتور (Android)

Field orders for visitors, with an offline queue — [ADR-0018](../docs/architecture/decisions/0018-visitor-app.md),
install and build: [`docs/install/visitor-app.md`](../docs/install/visitor-app.md).

```bash
flutter pub get
flutter analyze
flutter test --exclude-tags server              # unit + screens
flutter test --tags screens --update-goldens    # re-render the screen images
NEXTCAM_TEST_SERVER=http://127.0.0.1:5000 NEXTCAM_TEST_USER=… NEXTCAM_TEST_PASSWORD=… \
  flutter test --tags server                    # against a running server
flutter build apk --release                     # needs the Android SDK
```
