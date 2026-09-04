import { Tabs } from "expo-router";
import {
  Bot,
  LayoutGrid,
  MessageCircle,
  UsersRound,
} from "lucide-react-native";
import { Platform, StyleSheet } from "react-native";

import { mobileText } from "../../i18n/locale";
import { colors } from "../../theme/tokens";

export default function TabLayout() {
  return (
    <Tabs
      screenOptions={{
        animation: "fade",
        headerShown: false,
        tabBarActiveTintColor: colors.accent,
        tabBarAllowFontScaling: false,
        tabBarInactiveTintColor: colors.faint,
        tabBarLabelStyle: styles.label,
        tabBarStyle: styles.bar,
        tabBarItemStyle: styles.item,
        tabBarHideOnKeyboard: true,
      }}
    >
      <Tabs.Screen
        name="chats"
        options={{
          title: mobileText("会话", "Chats"),
          tabBarIcon: ({ color, size }) => (
            <MessageCircle color={color} size={size} strokeWidth={2} />
          ),
        }}
      />
      <Tabs.Screen
        name="agents"
        options={{
          title: mobileText("智能体", "Agents"),
          tabBarIcon: ({ color, size }) => (
            <Bot color={color} size={size} strokeWidth={2} />
          ),
        }}
      />
      <Tabs.Screen
        name="community"
        options={{
          title: mobileText("社区", "Community"),
          tabBarIcon: ({ color, size }) => (
            <UsersRound color={color} size={size} strokeWidth={2} />
          ),
        }}
      />
      <Tabs.Screen
        name="workbench"
        options={{
          title: mobileText("工作台", "Workbench"),
          tabBarIcon: ({ color, size }) => (
            <LayoutGrid color={color} size={size} strokeWidth={2} />
          ),
        }}
      />
      <Tabs.Screen name="me" options={{ href: null }} />
    </Tabs>
  );
}

const styles = StyleSheet.create({
  bar: {
    height: Platform.OS === "ios" ? 84 : 66,
    paddingTop: 7,
    backgroundColor: colors.tabBar,
    borderTopColor: colors.hairline,
    borderTopWidth: StyleSheet.hairlineWidth,
    shadowColor: colors.black,
    shadowOpacity: 0,
    elevation: 0,
  },
  item: { paddingBottom: Platform.OS === "ios" ? 2 : 8 },
  label: { fontSize: 11, fontWeight: "500" },
});
