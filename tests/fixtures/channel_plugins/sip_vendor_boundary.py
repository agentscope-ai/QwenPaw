"""Controlled native SDK surface shared by direct and child tests."""
from types import ModuleType, SimpleNamespace as NS
import threading


class Vendor:
    def __init__(self):
        (
            self.phones,
            self.asrs,
            self.synths,
            self.rooms,
            self.sources,
            self.apis,
        ) = ([], [], [], [], [], [])
        self.fail_stop = False
        self.fail_write = False
        self.fail_tts = False
        self.tts_release = None

    def modules(self):
        owner = self

        class Phone:
            def __init__(self, *args, **kwargs):
                self.args, self.kwargs = args, kwargs
                self.calls, self.threads = [], []
                owner.phones.append(self)

            def start(self):
                pass

            def stop(self):
                if owner.fail_stop:
                    raise OSError("native stop refused")
                for call in self.calls:
                    call.hangup()

            def incoming(
                self, call_id="call-1", sender="sip:alice@example.test"
            ):
                call = Call(call_id, sender)
                self.calls.append(call)
                thread = threading.Thread(
                    target=self.kwargs["callCallback"], args=(call,)
                )
                self.threads.append(thread)
                thread.start()
                return call

        class Call:
            def __init__(self, call_id, sender):
                self.request = NS(
                    headers={
                        "Call-ID": call_id,
                        "From": sender,
                        "To": "sip:bot@example.test",
                    }
                )
                self.state, self.writes, self.hangups = "ringing", [], 0

            def answer(self):
                self.state = "answered"

            def read_audio(self, **kwargs):
                return b""

            def write_audio(self, data):
                self.writes.append(bytes(data))
                if owner.fail_write:
                    raise OSError("ambiguous native write")

            def hangup(self):
                self.hangups += 1
                self.state = "ended"

        class ASR:
            def __init__(self, **kwargs):
                self.kwargs, self.audio, self.closed = kwargs, [], False
                owner.asrs.append(self)

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                self.closed = True

            async def send_audio(self, chunk):
                self.audio.append(chunk)

            async def finish(self):
                pass

            def sentence(self, text):
                self.kwargs["on_sentence_end"](text)

            def partial(self, text):
                self.kwargs["on_partial"](text)

        class Synth:
            def __init__(self, **kwargs):
                self.kwargs = kwargs
                self.text = None
                owner.synths.append(self)

            def call(self, text):
                self.text = text
                if owner.tts_release:
                    owner.tts_release.wait()
                callback = self.kwargs["callback"]
                if owner.fail_tts:
                    callback.on_error("native TTS refused")
                else:
                    size = 320 if self.kwargs["format"] == 8000 else 960
                    callback.on_data(b"\0" * size)
                    callback.on_complete()

        class Room:
            def __init__(self):
                self.handlers, self.remote_participants = {}, {}
                self.local_participant = NS(publish_track=self.publish)
                self.disconnected = False
                owner.rooms.append(self)

            def on(self, event):
                def register(handler):
                    self.handlers[event] = handler
                    return handler

                return register

            async def connect(self, *args):
                pass

            async def publish(self, track):
                pass

            async def disconnect(self):
                if owner.fail_stop:
                    raise OSError("native room stop refused")
                self.disconnected = True

            def participant(self, identity="caller", kind=1):
                p = NS(
                    identity=identity,
                    kind=kind,
                    attributes={"sip.phoneNumber": identity},
                    track_publications={},
                )
                self.handlers["participant_connected"](p)
                return p

        class Source:
            def __init__(self, **kwargs):
                self.kwargs, self.frames, self.closed = kwargs, [], False
                owner.sources.append(self)

            async def capture_frame(self, frame):
                self.frames.append(frame)
                if owner.fail_write:
                    raise OSError("ambiguous native write")

            async def aclose(self):
                self.closed = True

        class API:
            def __init__(self, **kwargs):
                self.closed, self.deleted = False, []
                self.room = NS(delete_room=self.delete)
                owner.apis.append(self)

            async def delete(self, request):
                self.deleted.append(request)

            async def aclose(self):
                self.closed = True

        class Token:
            def __init__(self, **kwargs):
                pass

            def with_identity(self, identity):
                return self

            def with_grants(self, grants):
                return self

            def to_jwt(self):
                return "vendor-token"

        def module(name, **attrs):
            value = ModuleType(name)
            value.__dict__.update(attrs)
            return value

        voip = module(
            "pyVoIP.VoIP",
            VoIPPhone=Phone,
            CallState=NS(ANSWERED="answered"),
            InvalidStateError=type("InvalidStateError", (Exception,), {}),
        )
        realtime = module("dashscope_realtime", DashScopeRealtimeASR=ASR)
        config = module(
            "dashscope_realtime.asr", ASRConfig=lambda **kwargs: NS(**kwargs)
        )
        tts = module(
            "dashscope.audio.tts_v2",
            AudioFormat=NS(
                **{
                    f"PCM_{rate}HZ_MONO_16BIT": rate
                    for rate in (8000, 16000, 22050, 24000)
                }
            ),
            ResultCallback=object,
            SpeechSynthesizer=Synth,
        )
        api = module(
            "livekit.api",
            LiveKitAPI=API,
            AccessToken=Token,
            VideoGrants=lambda **kwargs: NS(**kwargs),
            DeleteRoomRequest=lambda **kwargs: NS(**kwargs),
        )
        rtc = module(
            "livekit.rtc",
            Room=Room,
            AudioSource=Source,
            LocalAudioTrack=NS(create_audio_track=lambda *args: NS()),
            ParticipantKind=NS(
                PARTICIPANT_KIND_SIP=1, PARTICIPANT_KIND_STANDARD=2
            ),
            TrackKind=NS(KIND_AUDIO=1),
            AudioFrame=lambda **kwargs: NS(**kwargs),
        )
        return {
            "pyVoIP": module("pyVoIP", VoIP=voip),
            "pyVoIP.VoIP": voip,
            "dashscope_realtime": realtime,
            "dashscope_realtime.asr": config,
            "dashscope": module("dashscope"),
            "dashscope.audio": module("dashscope.audio"),
            "dashscope.audio.tts_v2": tts,
            "livekit": module("livekit", api=api, rtc=rtc),
            "livekit.api": api,
            "livekit.rtc": rtc,
        }
