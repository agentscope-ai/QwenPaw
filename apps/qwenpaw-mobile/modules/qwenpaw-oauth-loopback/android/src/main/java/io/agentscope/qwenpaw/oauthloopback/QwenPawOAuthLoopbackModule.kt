package io.agentscope.qwenpaw.oauthloopback

import android.app.ActivityOptions
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.net.Uri
import android.os.Build
import android.os.Bundle
import androidx.annotation.ChecksSdkIntAtLeast
import androidx.core.content.ContextCompat
import expo.modules.kotlin.Promise
import expo.modules.kotlin.modules.Module
import expo.modules.kotlin.modules.ModuleDefinition
import java.io.BufferedInputStream
import java.io.IOException
import java.net.InetAddress
import java.net.InetSocketAddress
import java.net.ServerSocket
import java.net.Socket
import java.net.SocketException
import java.nio.charset.StandardCharsets
import java.util.concurrent.ExecutorService
import java.util.concurrent.Executors

private const val CALLBACK_PATH = "/callback/qwenpaw-mobile"
private const val CALLBACK_SCHEME = "qwenpaw://platform-auth"
private const val LOOPBACK_HOST = "127.0.0.1"
private const val MAX_REQUEST_LINE_BYTES = 8_192
private const val RETURN_REQUEST_CODE = 0x5151
private const val SOCKET_TIMEOUT_MILLIS = 5_000

internal fun supportsOAuthReturnCreatorOptIn(sdkInt: Int): Boolean =
  sdkInt >= Build.VERSION_CODES.VANILLA_ICE_CREAM

internal fun supportsOAuthReturnSenderOptIn(sdkInt: Int): Boolean =
  sdkInt >= Build.VERSION_CODES.UPSIDE_DOWN_CAKE

@ChecksSdkIntAtLeast(api = Build.VERSION_CODES.VANILLA_ICE_CREAM)
private fun requiresOAuthReturnCreatorOptIn(): Boolean =
  supportsOAuthReturnCreatorOptIn(Build.VERSION.SDK_INT)

@ChecksSdkIntAtLeast(api = Build.VERSION_CODES.UPSIDE_DOWN_CAKE)
private fun requiresOAuthReturnSenderOptIn(): Boolean =
  supportsOAuthReturnSenderOptIn(Build.VERSION.SDK_INT)

@Suppress("DEPRECATION")
internal fun oauthBackgroundActivityStartMode(sdkInt: Int): Int =
  if (sdkInt >= 36) {
    ActivityOptions.MODE_BACKGROUND_ACTIVITY_START_ALLOW_ALWAYS
  } else {
    ActivityOptions.MODE_BACKGROUND_ACTIVITY_START_ALLOWED
  }

internal fun createOAuthReturnPendingIntent(
  context: Context,
): PendingIntent? {
  val intent = context.packageManager
    .getLaunchIntentForPackage(context.packageName)
    ?: return null
  intent.addFlags(
    Intent.FLAG_ACTIVITY_CLEAR_TOP or Intent.FLAG_ACTIVITY_SINGLE_TOP,
  )
  return PendingIntent.getActivity(
    context,
    RETURN_REQUEST_CODE,
    intent,
    PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT,
    oauthReturnCreatorActivityOptions(),
  )
}

@Suppress("DEPRECATION")
internal fun oauthReturnCreatorActivityOptions(): Bundle? {
  if (!requiresOAuthReturnCreatorOptIn()) return null
  return ActivityOptions.makeBasic().apply {
    setPendingIntentCreatorBackgroundActivityStartMode(
      oauthBackgroundActivityStartMode(Build.VERSION.SDK_INT),
    )
  }.toBundle()
}

@Suppress("DEPRECATION")
internal fun oauthReturnSenderActivityOptions(): Bundle? {
  if (!requiresOAuthReturnSenderOptIn()) return null
  return ActivityOptions.makeBasic().apply {
    setPendingIntentBackgroundActivityStartMode(
      oauthBackgroundActivityStartMode(Build.VERSION.SDK_INT),
    )
  }.toBundle()
}

internal fun callbackLocation(requestLine: String): String? {
  val target = callbackTarget(requestLine) ?: return null
  val queryIndex = target.indexOf('?')
  return if (queryIndex >= 0) {
    "$CALLBACK_SCHEME?${target.substring(queryIndex + 1)}"
  } else {
    CALLBACK_SCHEME
  }
}

internal fun callbackTarget(requestLine: String): String? {
  val parts = requestLine.split(' ', limit = 3)
  if (parts.size != 3 || parts[0] != "GET") return null

  val target = parts[1]
  val queryIndex = target.indexOf('?')
  val path = if (queryIndex >= 0) target.substring(0, queryIndex) else target
  if (path != CALLBACK_PATH) return null
  return target
}

class QwenPawOAuthLoopbackModule : Module() {
  private val listenerLock = Any()
  private val executor: ExecutorService = Executors.newSingleThreadExecutor {
    Thread(it, "qwenpaw-oauth-loopback").apply { isDaemon = true }
  }
  private var listener: ServerSocket? = null
  private var callbackPromise: Promise? = null
  private var pendingCallbackUrl: String? = null
  private var returnPendingIntent: PendingIntent? = null

  override fun definition() = ModuleDefinition {
    Name("QwenPawOAuthLoopback")

    AsyncFunction("startAsync") {
      start()
    }

    AsyncFunction("stopAsync") {
      stop()
    }

    AsyncFunction("waitForCallbackAsync") { promise: Promise ->
      waitForCallback(promise)
    }

    OnDestroy {
      stop()
      executor.shutdownNow()
    }
  }

  private fun start(): Int {
    stop()
    val socket = ServerSocket().apply {
      reuseAddress = true
      bind(
        InetSocketAddress(InetAddress.getByName(LOOPBACK_HOST), 0),
        1,
      )
    }
    val pendingIntent = appContext.reactContext?.let(
      ::createOAuthReturnPendingIntent,
    )
    synchronized(listenerLock) {
      listener = socket
      returnPendingIntent = pendingIntent
    }
    startKeepAliveService()
    executor.execute { acceptConnections(socket) }
    return socket.localPort
  }

  private fun stop() {
    val (socket, promise, pendingIntent) = synchronized(listenerLock) {
      val current = listener
      listener = null
      pendingCallbackUrl = null
      val pending = callbackPromise
      callbackPromise = null
      val returnIntent = returnPendingIntent
      returnPendingIntent = null
      Triple(current, pending, returnIntent)
    }
    socket?.close()
    promise?.resolve(null)
    pendingIntent?.cancel()
    stopKeepAliveService()
  }

  private fun waitForCallback(promise: Promise) {
    var callback: String? = null
    var error: String? = null
    synchronized(listenerLock) {
      when {
        listener == null -> error = "OAuth loopback listener is not running"
        callbackPromise != null -> error = "OAuth callback wait is already active"
        pendingCallbackUrl != null -> {
          callback = pendingCallbackUrl
          pendingCallbackUrl = null
        }
        else -> callbackPromise = promise
      }
    }
    when {
      error != null -> promise.reject("ERR_OAUTH_LOOPBACK_STATE", error, null)
      callback != null -> promise.resolve(callback)
    }
  }

  private fun acceptConnections(socket: ServerSocket) {
    try {
      while (!socket.isClosed) {
        val shouldStop = try {
          socket.accept().use { connection ->
            handleConnection(connection)
          }
        } catch (error: SocketException) {
          if (socket.isClosed) break
          throw error
        } catch (_: IOException) {
          false
        }
        if (shouldStop) {
          socket.close()
        }
      }
    } finally {
      socket.close()
      synchronized(listenerLock) {
        if (listener === socket) listener = null
      }
    }
  }

  private fun handleConnection(connection: Socket): Boolean {
    connection.soTimeout = SOCKET_TIMEOUT_MILLIS
    val requestLine = readRequestLine(connection)
    val target = requestLine?.let(::callbackTarget)
    if (target == null) {
      tryRespond(connection, "404 Not Found", "Not found")
      return false
    }
    val callbackUrl = "http://$LOOPBACK_HOST:${connection.localPort}$target"
    val appCallbackUrl = callbackLocation(requestLine)
    deliverCallback(callbackUrl)
    returnToApp(appCallbackUrl)
    tryRespond(
      connection,
      "302 Found",
      "Returning to QwenPaw",
      appCallbackUrl,
    )
    return true
  }

  private fun deliverCallback(callbackUrl: String) {
    val promise = synchronized(listenerLock) {
      val pending = callbackPromise
      callbackPromise = null
      if (pending == null) pendingCallbackUrl = callbackUrl
      pending
    }
    promise?.resolve(callbackUrl)
  }

  private fun returnToApp(callbackUrl: String?) {
    val context = appContext.reactContext ?: return
    val pendingIntent = synchronized(listenerLock) { returnPendingIntent }
    if (pendingIntent != null) {
      try {
        pendingIntent.send(
          context,
          0,
          null,
          null,
          null,
          null,
          oauthReturnSenderActivityOptions(),
        )
        return
      } catch (_: PendingIntent.CanceledException) {
        // Fall through to direct launch for older Android implementations.
      }
    }
    val intent = context.packageManager
      .getLaunchIntentForPackage(context.packageName)
      ?: return
    intent.action = Intent.ACTION_VIEW
    intent.data = Uri.parse(callbackUrl ?: CALLBACK_SCHEME)
    intent.addFlags(
      Intent.FLAG_ACTIVITY_NEW_TASK or
        Intent.FLAG_ACTIVITY_CLEAR_TOP or
        Intent.FLAG_ACTIVITY_SINGLE_TOP,
    )
    context.startActivity(intent)
  }

  private fun startKeepAliveService() {
    val context = appContext.reactContext ?: return
    ContextCompat.startForegroundService(
      context,
      Intent(context, OAuthLoopbackKeepAliveService::class.java),
    )
  }

  private fun stopKeepAliveService() {
    val context = appContext.reactContext ?: return
    context.stopService(
      Intent(context, OAuthLoopbackKeepAliveService::class.java),
    )
  }

  private fun tryRespond(
    connection: Socket,
    status: String,
    body: String,
    location: String? = null,
  ) {
    try {
      respond(connection, status, body, location)
    } catch (_: IOException) {
      // The browser may close the loopback socket as soon as it has the
      // redirect. The verified callback must still be delivered to the app.
    }
  }

  private fun readRequestLine(connection: Socket): String? {
    val input = BufferedInputStream(connection.getInputStream())
    val bytes = ArrayList<Byte>()
    while (bytes.size < MAX_REQUEST_LINE_BYTES) {
      val next = input.read()
      if (next == -1 || next == '\n'.code) break
      if (next != '\r'.code) bytes.add(next.toByte())
    }
    if (bytes.isEmpty() || bytes.size == MAX_REQUEST_LINE_BYTES) return null
    return bytes.toByteArray().toString(StandardCharsets.US_ASCII)
  }

  private fun respond(
    connection: Socket,
    status: String,
    body: String,
    location: String? = null,
  ) {
    val bodyBytes = body.toByteArray(StandardCharsets.UTF_8)
    val headers = mutableListOf(
      "HTTP/1.1 $status",
      "Content-Type: text/plain; charset=utf-8",
      "Cache-Control: no-store",
      "Content-Length: ${bodyBytes.size}",
      "Connection: close",
    )
    if (location != null) headers.add("Location: $location")
    val output = connection.getOutputStream()
    output.write((headers + listOf("", "")).joinToString("\r\n")
      .toByteArray(StandardCharsets.US_ASCII))
    output.write(bodyBytes)
    output.flush()
  }
}
