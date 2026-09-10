const { withAndroidManifest } = require("@expo/config-plugins");

function withQwenPawAndroidNetworking(config) {
  return withAndroidManifest(config, (androidConfig) => {
    const application = androidConfig.modResults.manifest.application?.[0];
    if (application) {
      application.$["android:usesCleartextTraffic"] = "true";
    }
    return androidConfig;
  });
}

module.exports = withQwenPawAndroidNetworking;
