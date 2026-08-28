package io.agentscope.qwenpaw.oauthloopback

import android.app.ActivityOptions
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class QwenPawOAuthLoopbackModuleTest {
  @Test
  fun mapsVerifiedCallbackPathToAppScheme() {
    assertEquals(
      "qwenpaw://platform-auth?code=code&state=state",
      callbackLocation(
        "GET /callback/qwenpaw-mobile?code=code&state=state HTTP/1.1",
      ),
    )
  }

  @Test
  fun preservesVerifiedLoopbackTargetForNativeDelivery() {
    assertEquals(
      "/callback/qwenpaw-mobile?code=code&state=state",
      callbackTarget(
        "GET /callback/qwenpaw-mobile?code=code&state=state HTTP/1.1",
      ),
    )
  }

  @Test
  fun rejectsUnexpectedMethodOrPath() {
    assertNull(
      callbackLocation(
        "POST /callback/qwenpaw-mobile?code=code HTTP/1.1",
      ),
    )
    assertNull(callbackLocation("GET /other?code=code HTTP/1.1"))
  }

  @Test
  fun appliesBackgroundLaunchOptInsOnlyWhenAndroidRequiresThem() {
    assertFalse(supportsOAuthReturnSenderOptIn(24))
    assertFalse(supportsOAuthReturnCreatorOptIn(24))
    assertFalse(supportsOAuthReturnSenderOptIn(33))
    assertFalse(supportsOAuthReturnCreatorOptIn(33))
    assertTrue(supportsOAuthReturnSenderOptIn(34))
    assertFalse(supportsOAuthReturnCreatorOptIn(34))
    assertTrue(supportsOAuthReturnSenderOptIn(35))
    assertTrue(supportsOAuthReturnCreatorOptIn(35))
    assertTrue(supportsOAuthReturnSenderOptIn(36))
    assertTrue(supportsOAuthReturnCreatorOptIn(36))
  }

  @Suppress("DEPRECATION")
  @Test
  fun selectsTheBackgroundLaunchModeForEachAndroidGeneration() {
    assertEquals(
      ActivityOptions.MODE_BACKGROUND_ACTIVITY_START_ALLOWED,
      oauthBackgroundActivityStartMode(34),
    )
    assertEquals(
      ActivityOptions.MODE_BACKGROUND_ACTIVITY_START_ALLOWED,
      oauthBackgroundActivityStartMode(35),
    )
    assertEquals(
      ActivityOptions.MODE_BACKGROUND_ACTIVITY_START_ALLOW_ALWAYS,
      oauthBackgroundActivityStartMode(36),
    )
  }
}
