# -*- coding: utf-8 -*-
"""Lazy LiveKit SIP backend: one accepted participant per room connection."""
from __future__ import annotations

import asyncio
import uuid

from .backend import SIPPlatformError
from .runtime import ResourceClaim, cancel_tasks

_AUDIO_QUEUE_MAX_FRAMES = 150


def _put_latest_audio(queue, frame):
    if queue.full():
        try:
            queue.get_nowait()
        except asyncio.QueueEmpty:
            pass
    queue.put_nowait(frame)


class LiveKitBackend:
    def __init__(
        self,
        livekit_url="",
        livekit_api_key="",
        livekit_api_secret="",
        sip_trunk_id="",
        room_name="sip-inbound",
        output_sample_rate=24000,
    ):
        self._url, self._api_key, self._api_secret = (
            livekit_url,
            livekit_api_key,
            livekit_api_secret,
        )
        self._trunk_id, self._room_name = sip_trunk_id, room_name
        self._output_sample_rate = output_sample_rate
        self._lk_api = (
            self._room
        ) = self._audio_source = self._audio_queue = None
        self._room_epoch = None
        self._ending_epoch = None
        self._accepted = None
        self._running = self._busy = False
        self._claim = None
        self._tasks = set()
        self._readers = {}
        self._streams = {}
        self._task_failure = None
        self.on_incoming_call = (
            self.on_call_ended
        ) = self.on_state_changed = None

    def _spawn(self, coroutine):
        task = asyncio.create_task(coroutine)
        self._tasks.add(task)

        def done(completed):
            if completed.cancelled():
                self._tasks.discard(completed)
            elif completed.exception() is None:
                self._tasks.discard(completed)
            else:
                # Retain failed task evidence and stop admitting new calls.
                first_failure = self._task_failure is None
                self._task_failure = completed.exception()
                self._running = False
                if first_failure:
                    self._spawn(self._state("failed"))

        task.add_done_callback(done)
        return task

    async def _state(self, state):
        if self.on_state_changed:
            await self.on_state_changed(state)

    async def start(self):
        if not self._url or not self._api_key or not self._api_secret:
            raise ValueError("LIVEKIT_CONNECTION_CONFIG_REQUIRED")
        from livekit import api as lk_api

        self._claim = ResourceClaim(self._url, self._room_name)
        self._claim.acquire()
        self._lk_api = lk_api.LiveKitAPI(
            url=self._url.replace("ws://", "http://").replace(
                "wss://",
                "https://",
            ),
            api_key=self._api_key,
            api_secret=self._api_secret,
        )
        self._running = True
        self._spawn(self._connect_with_retry())

    async def _connect_with_retry(self):
        delay = 2
        while self._running:
            await self._state("connecting")
            try:
                await self._connect_and_wait()
                return
            except asyncio.CancelledError:
                raise
            except Exception:
                await self._disconnect_room()
                if not self._running:
                    return
                await asyncio.sleep(delay)
                delay = min(delay * 2, 30)

    def _current_room(self, room, epoch):
        return (
            self._running and self._room is room and self._room_epoch == epoch
        )

    def _matches(self, binding):
        return self._accepted is binding and self._current_room(
            binding["room"],
            binding["epoch"],
        )

    async def _connect_and_wait(self):
        from livekit import api as lk_api, rtc

        token = (
            lk_api.AccessToken(
                api_key=self._api_key,
                api_secret=self._api_secret,
            )
            .with_identity("qwenpaw-sip-agent")
            .with_grants(
                lk_api.VideoGrants(room_join=True, room=self._room_name),
            )
            .to_jwt()
        )
        room = self._room = rtc.Room()
        epoch = self._room_epoch = uuid.uuid4().hex
        self._ending_epoch = None
        source = self._audio_source = rtc.AudioSource(
            sample_rate=self._output_sample_rate,
            num_channels=1,
        )
        track = rtc.LocalAudioTrack.create_audio_track("qwenpaw-tts", source)

        @room.on("participant_connected")
        def participant_connected(participant):
            if self._current_room(room, epoch):
                self._spawn(
                    self._handle_sip_participant(
                        self._room_name,
                        participant,
                        room=room,
                        epoch=epoch,
                    ),
                )

        @room.on("track_subscribed")
        def track_subscribed(remote_track, publication, participant):
            binding = self._accepted
            if (
                binding
                and binding["participant"] is participant
                and self._matches(binding)
                and remote_track.kind == rtc.TrackKind.KIND_AUDIO
            ):
                self._start_reader(binding, remote_track)

        @room.on("participant_disconnected")
        def participant_disconnected(participant):
            binding = self._accepted
            if (
                binding
                and binding["participant"] is participant
                and self._matches(binding)
            ):
                self._schedule_end(binding, room, epoch)

        @room.on("disconnected")
        def disconnected(*args):
            if not self._current_room(room, epoch):
                return
            self._schedule_end(self._accepted, room, epoch)

        await room.connect(self._url, token)
        if not self._current_room(room, epoch):
            raise RuntimeError("SIP_ROOM_RETIRED")
        await room.local_participant.publish_track(track)
        await self._state("connected")
        for participant in room.remote_participants.values():
            await self._handle_sip_participant(
                self._room_name,
                participant,
                room=room,
                epoch=epoch,
            )

    def _schedule_end(self, binding, room, epoch):
        if not self._current_room(room, epoch) or self._ending_epoch == epoch:
            return
        self._ending_epoch = epoch
        self._accepted = None
        self._busy = True
        self._spawn(self._room_lost(binding, room, epoch))

    async def _handle_sip_participant(
        self,
        call_id,
        participant,
        *,
        room=None,
        epoch=None,
    ):
        from livekit import rtc

        room = self._room if room is None else room
        epoch = self._room_epoch if epoch is None else epoch
        if not self._current_room(room, epoch) or self._busy:
            return
        if participant.kind not in (
            rtc.ParticipantKind.PARTICIPANT_KIND_SIP,
            rtc.ParticipantKind.PARTICIPANT_KIND_STANDARD,
        ):
            return
        self._busy = True
        binding = self._accepted = {
            "room": room,
            "epoch": epoch,
            "participant": participant,
            "source": self._audio_source,
            "call_id": call_id,
            "queue": asyncio.Queue(maxsize=_AUDIO_QUEUE_MAX_FRAMES),
        }
        self._audio_queue = binding["queue"]
        from_uri = (
            participant.attributes.get("sip.phoneNumber", participant.identity)
            if participant.kind == rtc.ParticipantKind.PARTICIPANT_KIND_SIP
            else participant.identity
        )

        async def write_audio(data):
            if not self._matches(binding):
                raise SIPPlatformError("CALL_CLOSED")
            frame = rtc.AudioFrame(
                data=data,
                sample_rate=self._output_sample_rate,
                num_channels=1,
                samples_per_channel=len(data) // 2,
            )
            # Capture source and room epoch; never use a replacement source.
            await binding["source"].capture_frame(frame)

        try:
            if self.on_incoming_call:
                await self.on_incoming_call(
                    call_id,
                    from_uri,
                    self._room_name,
                    binding["queue"],
                    write_audio,
                )
        except BaseException:
            if self._accepted is binding:
                self._accepted = None
            raise
        if self._matches(binding):
            for publication in participant.track_publications.values():
                remote_track = publication.track
                if (
                    remote_track
                    and remote_track.kind == rtc.TrackKind.KIND_AUDIO
                ):
                    self._start_reader(binding, remote_track)

    def _start_reader(self, binding, track):
        key = (binding["epoch"], id(track))
        if key in self._readers:
            return
        task = self._spawn(
            self._read_audio_track(binding["call_id"], track, binding=binding),
        )
        self._readers[key] = task

        def done(completed):
            if completed.cancelled() or completed.exception() is None:
                self._readers.pop(key, None)

        task.add_done_callback(done)

    async def _read_audio_track(self, call_id, track, *, binding=None):
        from livekit import rtc

        binding = self._accepted if binding is None else binding
        if binding is None or not self._matches(binding):
            return
        stream = rtc.AudioStream(track)
        self._streams[id(stream)] = stream
        try:
            async for event in stream:
                if not self._matches(binding):
                    break
                _put_latest_audio(binding["queue"], bytes(event.frame.data))
        finally:
            await stream.aclose()
            self._streams.pop(id(stream), None)
            if self._matches(binding):
                _put_latest_audio(binding["queue"], None)

    async def play_audio(self, call_id, audio):
        binding = self._accepted
        if binding is None or binding["call_id"] != call_id:
            raise SIPPlatformError("CALL_CLOSED")
        from livekit import rtc

        if not self._matches(binding):
            raise SIPPlatformError("CALL_CLOSED")
        await binding["source"].capture_frame(
            rtc.AudioFrame(
                data=audio,
                sample_rate=self._output_sample_rate,
                num_channels=1,
                samples_per_channel=len(audio) // 2,
            ),
        )

    async def hangup(self, call_id):
        binding = self._accepted
        if binding is not None and binding["call_id"] == call_id:
            self._ending_epoch = binding["epoch"]
            self._accepted = None
            await self._state("connecting")
            await self._delete_and_reconnect(binding["room"], binding["epoch"])

    async def _room_lost(self, binding, room, epoch):
        if self._room is not room or self._room_epoch != epoch:
            return
        if binding is not None and self.on_call_ended:
            await self.on_call_ended(binding["call_id"])
        if self._room is room and self._room_epoch == epoch:
            await self._state("connecting")
            await self._delete_and_reconnect(room, epoch)

    async def _disconnect_room(self):
        self._accepted = None
        room, source = self._room, self._audio_source
        self._room_epoch = None
        failures = []
        try:
            await cancel_tasks(self._readers.values())
        except Exception as exc:
            failures.append(exc)
        for key, stream in tuple(self._streams.items()):
            try:
                await stream.aclose()
            except Exception as exc:
                failures.append(exc)
            else:
                self._streams.pop(key, None)
        if room is not None:
            try:
                await room.disconnect()
            except Exception as exc:
                failures.append(exc)
            else:
                self._room = None
        if source is not None:
            try:
                await source.aclose()
            except Exception as exc:
                failures.append(exc)
            else:
                self._audio_source = None
        if failures:
            raise RuntimeError("SIP_ROOM_STOP_INCOMPLETE") from failures[0]
        self._audio_queue = None
        self._busy = False

    async def _delete_and_reconnect(self, room, epoch):
        if self._room is not room or self._room_epoch != epoch:
            return
        await self._disconnect_room()
        if self._lk_api is not None:
            from livekit import api as lk_api

            await self._lk_api.room.delete_room(
                lk_api.DeleteRoomRequest(room=self._room_name),
            )
        if self._running:
            await asyncio.sleep(1)
            await self._connect_with_retry()

    def quiesce(self):
        self._running = False

    async def stop(self):
        self._running = False
        self._accepted = None
        failures = []
        try:
            await cancel_tasks(self._tasks)
        except Exception as exc:
            failures.append(exc)
        try:
            await self._disconnect_room()
        except Exception as exc:
            failures.append(exc)
        if self._lk_api is not None:
            try:
                await self._lk_api.aclose()
            except Exception as exc:
                failures.append(exc)
            else:
                self._lk_api = None
        if failures:
            raise RuntimeError("SIP_LIVEKIT_STOP_INCOMPLETE") from failures[0]
        if self._claim is not None:
            self._claim.close()
            self._claim = None
