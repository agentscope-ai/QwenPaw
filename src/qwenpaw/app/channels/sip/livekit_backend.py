# -*- coding: utf-8 -*-
"""LiveKit backend -- production-grade SIP/RTP (event-driven).

Architecture::

    SIP Phone -> LiveKit SIP Server (Go)
              -> LiveKit Room (WebRTC)
              -> This Backend (STT/TTS bridge)

The backend connects to a pre-configured room on startup and waits
for a SIP participant to join via ``participant_connected`` events.
When the call ends (``participant_disconnected``), the room is
explicitly deleted and the backend reconnects to wait for the next
call.

.. note::

    TODO: 当前采用单房间事件监听模式，底层架构已具备并发能力，
    后续可配合 FastAPI Webhook 实现动态房间的并发路由。

Required config::

    sip_mode: "livekit"
    livekit_url: "ws://your-livekit:7880"
    livekit_api_key: "devkey"
    livekit_api_secret: "secret"
    livekit_room_name: "sip-inbound"

Required packages::

    pip install livekit livekit-api
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Optional

from .backend import CallEndedCallback, IncomingCallCallback

logger = logging.getLogger(__name__)


class LiveKitBackend:
    """SipBackend backed by LiveKit SIP Server (event-driven).

    Instead of polling ``list_rooms``, the backend connects to a
    fixed room on startup and reacts to LiveKit room events:

    * ``participant_connected``  → start agent session
    * ``track_subscribed``       → bridge audio to STT
    * ``participant_disconnected`` → cleanup + delete room + reconnect

    TODO: 当前采用单房间事件监听模式，底层架构已具备并发能力，
    后续可配合 FastAPI Webhook 实现动态房间的并发路由。
    """

    def __init__(
        self,
        livekit_url: str = "",
        livekit_api_key: str = "",
        livekit_api_secret: str = "",
        sip_trunk_id: str = "",
        room_name: str = "sip-inbound",
        output_sample_rate: int = 24000,
    ) -> None:
        self._url = livekit_url
        self._api_key = livekit_api_key
        self._api_secret = livekit_api_secret
        self._trunk_id = sip_trunk_id
        self._room_name = room_name
        self._output_sample_rate = output_sample_rate

        self.on_incoming_call: Optional[IncomingCallCallback] = None
        self.on_call_ended: Optional[CallEndedCallback] = None

        self._lk_api: Any = None
        self._room: Any = None
        self._audio_source: Any = None
        self._audio_queue: Optional[asyncio.Queue] = None
        self._running = False
        self._busy = False

    # ----------------------------------------------------------
    # Lifecycle
    # ----------------------------------------------------------

    async def start(self) -> None:
        if not self._url:
            raise ValueError("livekit_url is required")
        if not self._api_key or not self._api_secret:
            raise ValueError(
                "livekit_api_key and livekit_api_secret are required",
            )

        from livekit import api as lk_api

        http_url = self._url.replace(
            "ws://",
            "http://",
        ).replace("wss://", "https://")
        self._lk_api = lk_api.LiveKitAPI(
            url=http_url,
            api_key=self._api_key,
            api_secret=self._api_secret,
        )
        self._running = True
        # Non-blocking: retry connection in background so start() doesn't block
        asyncio.create_task(self._connect_with_retry())
        logger.info(
            "LiveKit backend started (event-driven): %s room=%s",
            self._url,
            self._room_name,
        )

    async def stop(self) -> None:
        self._running = False
        await self._disconnect_room()
        if self._lk_api:
            await self._lk_api.aclose()
            self._lk_api = None
        logger.info("LiveKit backend stopped")

    # ----------------------------------------------------------
    # Audio playback
    # ----------------------------------------------------------

    async def play_audio(
        self,
        call_id: str,
        audio: bytes,
    ) -> None:
        if self._audio_source is None:
            if not getattr(self, "_no_source_warned", False):
                logger.warning(
                    "play_audio: no source for %s",
                    call_id,
                )
                self._no_source_warned = True
            return
        from livekit import rtc

        frame = rtc.AudioFrame(
            data=audio,
            sample_rate=self._output_sample_rate,
            num_channels=1,
            samples_per_channel=len(audio) // 2,
        )
        await self._audio_source.capture_frame(frame)

    # ----------------------------------------------------------
    # Room connection (event-driven)
    # ----------------------------------------------------------

    async def _connect_with_retry(self) -> None:
        """Retry _connect_and_wait with exponential backoff."""
        delay = 2
        while self._running:
            try:
                await self._connect_and_wait()
                return  # connected successfully
            except Exception:
                logger.warning(
                    "Connect failed, retrying in %ds...",
                    delay,
                )
                await asyncio.sleep(delay)
                delay = min(delay * 2, 30)

    async def _connect_and_wait(self) -> None:
        """Connect to the pre-configured room and bind events."""
        from livekit import api as lk_api, rtc

        token = (
            lk_api.AccessToken(
                api_key=self._api_key,
                api_secret=self._api_secret,
            )
            .with_identity("qwenpaw-sip-agent")
            .with_grants(
                lk_api.VideoGrants(
                    room_join=True,
                    room=self._room_name,
                ),
            )
            .to_jwt()
        )

        room = rtc.Room()
        self._room = room
        self._busy = False

        audio_source = rtc.AudioSource(
            sample_rate=self._output_sample_rate,
            num_channels=1,
        )
        track = rtc.LocalAudioTrack.create_audio_track(
            "qwenpaw-tts",
            audio_source,
        )
        self._audio_source = audio_source
        self._no_source_warned = False

        call_id = self._room_name

        # -- Event: SIP participant joins --
        @room.on("participant_connected")
        def on_participant_connected(
            participant: rtc.RemoteParticipant,
        ):
            asyncio.create_task(
                self._handle_sip_participant(
                    call_id,
                    participant,
                ),
            )

        # -- Event: audio track ready --
        @room.on("track_subscribed")
        def on_track_subscribed(
            remote_track: rtc.Track,
            _publication: rtc.RemoteTrackPublication,
            _participant: rtc.RemoteParticipant,
        ):
            if remote_track.kind == rtc.TrackKind.KIND_AUDIO:
                asyncio.create_task(
                    self._read_audio_track(
                        call_id,
                        remote_track,
                    ),
                )

        # -- Event: SIP participant leaves --
        @room.on("participant_disconnected")
        def on_participant_disconnected(
            participant: rtc.RemoteParticipant,
        ):
            if participant.kind in (
                rtc.ParticipantKind.PARTICIPANT_KIND_SIP,
                rtc.ParticipantKind.PARTICIPANT_KIND_STANDARD,
            ):
                asyncio.create_task(
                    self._handle_call_ended(call_id),
                )

        try:
            await room.connect(self._url, token)
            await room.local_participant.publish_track(track)
            logger.info(
                "Connected to room: %s, waiting for SIP participant...",
                self._room_name,
            )
            # Check participants already in the room
            for p in room.remote_participants.values():
                await self._handle_sip_participant(call_id, p)
        except Exception:
            logger.exception(
                "Failed to connect to room %s",
                self._room_name,
            )
            self._room = None
            self._audio_source = None
            raise

    async def _disconnect_room(self) -> None:
        """Disconnect from the current room."""
        self._audio_queue = None
        self._audio_source = None
        room = self._room
        self._room = None
        if room:
            try:
                await room.disconnect()
            except Exception:
                pass

    async def _delete_and_reconnect(self) -> None:
        """Delete the room and reconnect to wait for next call."""
        await self._disconnect_room()

        # Explicitly delete the room to prevent stale rooms
        if self._lk_api:
            try:
                from livekit import api as lk_api

                await self._lk_api.room.delete_room(
                    lk_api.DeleteRoomRequest(
                        room=self._room_name,
                    ),
                )
                logger.info(
                    "Deleted room: %s",
                    self._room_name,
                )
            except Exception:
                logger.debug(
                    "Failed to delete room %s",
                    self._room_name,
                    exc_info=True,
                )

        if self._running:
            # Small delay before reconnecting
            await asyncio.sleep(1)
            asyncio.create_task(self._connect_with_retry())

    # ----------------------------------------------------------
    # Participant handling
    # ----------------------------------------------------------

    async def _handle_sip_participant(
        self,
        call_id: str,
        participant: Any,
    ) -> None:
        """Handle a SIP or WebRTC participant joining the room."""
        from livekit import rtc

        if self._busy:
            logger.warning(
                "Agent busy, ignoring participant: %s",
                participant.identity,
            )
            return
        if participant.kind not in (
            rtc.ParticipantKind.PARTICIPANT_KIND_SIP,
            rtc.ParticipantKind.PARTICIPANT_KIND_STANDARD,
        ):
            return

        self._busy = True
        is_sip = participant.kind == rtc.ParticipantKind.PARTICIPANT_KIND_SIP
        from_uri = (
            participant.attributes.get(
                "sip.phoneNumber",
                participant.identity,
            )
            if is_sip
            else participant.identity
        )
        logger.info(
            "%s participant in %s: %s",
            "SIP" if is_sip else "WebRTC",
            self._room_name,
            from_uri,
        )
        await self._notify_incoming(
            call_id,
            from_uri,
        )

        # Subscribe to existing audio tracks
        for pub in participant.track_publications.values():
            trk = pub.track
            if trk and trk.kind == rtc.TrackKind.KIND_AUDIO:
                asyncio.create_task(
                    self._read_audio_track(call_id, trk),
                )

    async def _handle_call_ended(self, call_id: str) -> None:
        """Clean up when a SIP participant leaves."""
        self._busy = False
        if self.on_call_ended:
            await self.on_call_ended(call_id)
        logger.info(
            "SIP call ended in room %s",
            self._room_name,
        )
        await self._delete_and_reconnect()

    # ----------------------------------------------------------
    # Audio bridge
    # ----------------------------------------------------------

    async def _read_audio_track(
        self,
        call_id: str,
        track: Any,
    ) -> None:
        """Read audio from a SIP participant's track."""
        from livekit import rtc

        if self._audio_queue is None:
            return

        stream = rtc.AudioStream(track)
        count = 0
        try:
            async for event in stream:
                frame = event.frame
                count += 1
                if count == 1:
                    logger.info(
                        "LiveKit frame #1 %s: rate=%s ch=%s len=%d",
                        call_id,
                        getattr(frame, "sample_rate", "?"),
                        getattr(frame, "num_channels", "?"),
                        len(bytes(frame.data)),
                    )
                self._audio_queue.put_nowait(bytes(frame.data))
        except Exception:
            logger.debug(
                "Audio read ended: %s",
                call_id,
                exc_info=True,
            )
        finally:
            if self._audio_queue:
                self._audio_queue.put_nowait(None)

    async def _notify_incoming(
        self,
        call_id: str,
        from_uri: str,
    ) -> None:
        """Notify SIPChannel of a new incoming call."""
        audio_queue: asyncio.Queue = asyncio.Queue()
        self._audio_queue = audio_queue

        async def write_audio(data: bytes) -> None:
            await self.play_audio(call_id, data)

        if self.on_incoming_call:
            await self.on_incoming_call(
                call_id,
                from_uri,
                self._room_name,
                audio_queue,
                write_audio,
            )
