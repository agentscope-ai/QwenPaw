package io.agentscope.qwenpaw.oauthloopback

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.Service
import android.content.Intent
import android.content.pm.ServiceInfo
import android.os.Build
import android.os.IBinder

private const val CHANNEL_ID = "platform_oauth"
private const val NOTIFICATION_ID = 0x5150

class OAuthLoopbackKeepAliveService : Service() {
  override fun onCreate() {
    super.onCreate()
    createNotificationChannel()
    val notification = buildNotification()
    if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
      startForeground(
        NOTIFICATION_ID,
        notification,
        ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC,
      )
    } else {
      startForeground(NOTIFICATION_ID, notification)
    }
  }

  override fun onStartCommand(
    intent: Intent?,
    flags: Int,
    startId: Int,
  ): Int = START_NOT_STICKY

  override fun onBind(intent: Intent?): IBinder? = null

  private fun createNotificationChannel() {
    if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) return
    val channel = NotificationChannel(
      CHANNEL_ID,
      "Platform 安全登录",
      NotificationManager.IMPORTANCE_LOW,
    ).apply {
      description = "仅在 Platform OAuth 登录期间保持安全回调可用"
      setShowBadge(false)
    }
    getSystemService(NotificationManager::class.java)
      .createNotificationChannel(channel)
  }

  private fun buildNotification(): Notification {
    val contentIntent = createOAuthReturnPendingIntent(this)
    val builder = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
      Notification.Builder(this, CHANNEL_ID)
    } else {
      Notification.Builder(this)
    }
    return builder
      .setSmallIcon(android.R.drawable.stat_sys_upload)
      .setContentTitle("QwenPaw")
      .setContentText("正在完成 Platform 登录；未自动返回时请点这里")
      .setCategory(Notification.CATEGORY_SERVICE)
      .setOngoing(true)
      .setOnlyAlertOnce(true)
      .setContentIntent(contentIntent)
      .build()
  }
}
