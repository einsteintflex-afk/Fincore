import type { CapacitorConfig } from "@capacitor/cli";

// Android and iOS apps: the same React build (dist/) in a native shell. They talk to the central FinCore
// server over HTTPS (address set on the sign-in screen or baked in with VITE_SERVER_URL at build time).
// No provider credentials or balances are ever stored in the app.
const config: CapacitorConfig = {
  appId: "com.fincore.app",
  appName: "FinCore",
  webDir: "dist",
  android: { allowMixedContent: false, webContentsDebuggingEnabled: false },
  ios: { contentInset: "automatic", limitsNavigationsToAppBoundDomains: false },
  plugins: { SplashScreen: { launchShowDuration: 800, backgroundColor: "#0b1f17" } },
};

export default config;
