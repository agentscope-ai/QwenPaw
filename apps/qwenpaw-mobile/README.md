# QwenPaw Mobile

Native Android and iOS client for QwenPaw, built with Expo and React Native.

## Requirements

- Node.js 22.13 or newer LTS
- Android Studio for Android builds
- Xcode 26.4 or newer for iOS builds

## Run

```bash
npm install --registry=https://registry.npmjs.org
npm run ios
npm run android
```

Use a physical device to test QR pairing. In QwenPaw Console, select
`Pair mobile` in the top bar and scan the displayed code.

## Checks

```bash
npm run typecheck
npm run lint
npm test
npx expo-doctor
```

The mobile app uses Expo SecureStore for credentials. Pairing tickets expire
after two minutes and are accepted only once.
