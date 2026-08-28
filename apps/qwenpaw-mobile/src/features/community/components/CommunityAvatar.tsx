import { memo, useEffect, useState } from "react";
import { Image, StyleSheet, Text, View } from "react-native";

import { qwenPawBrandAssets } from "../../../theme/brandAssets";
import { colors } from "../../../theme/tokens";
import { communityInitials } from "../model";

export const CommunityAvatar = memo(function CommunityAvatar({
  name,
  size = 42,
  uri,
  verified = false,
}: {
  name: string;
  size?: number;
  uri?: string | null;
  verified?: boolean;
}) {
  const [failed, setFailed] = useState(false);

  useEffect(() => setFailed(false), [uri]);

  const shape = {
    width: size,
    height: size,
    borderRadius: Math.round(size * 0.3),
  };
  if (uri && !failed) {
    return (
      <Image
        onError={() => setFailed(true)}
        source={{ uri }}
        style={[styles.image, shape]}
      />
    );
  }
  if (verified) {
    return (
      <Image
        accessibilityLabel="QwenPaw 官方头像"
        resizeMode="contain"
        source={qwenPawBrandAssets.head}
        style={[styles.image, shape]}
      />
    );
  }
  return (
    <View style={[styles.avatar, shape]}>
      <Text style={[styles.initials, { fontSize: Math.max(11, size * 0.29) }]}>
        {communityInitials(name)}
      </Text>
    </View>
  );
});

const styles = StyleSheet.create({
  image: { flexShrink: 0, backgroundColor: colors.accentSoft },
  avatar: {
    flexShrink: 0,
    alignItems: "center",
    justifyContent: "center",
    backgroundColor: colors.accent,
  },
  initials: { color: colors.white, fontWeight: "700" },
});
