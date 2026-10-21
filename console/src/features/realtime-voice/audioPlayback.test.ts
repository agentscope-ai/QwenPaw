import { describe, expect, it, vi } from "vitest";
import { RealtimeAudioPlayback } from "./audioPlayback";

describe("RealtimeAudioPlayback", () => {
  it("does not schedule audio invalidated while resume is pending", async () => {
    let resumePending: (() => void) | undefined;
    const createBuffer = vi.fn(() => ({
      duration: 0.1,
      getChannelData: () => new Float32Array(2),
    }));
    const createBufferSource = vi.fn();
    const resume = vi
      .fn<() => Promise<void>>()
      .mockResolvedValueOnce(undefined)
      .mockImplementationOnce(
        () =>
          new Promise<void>((resolve) => {
            resumePending = resolve;
          }),
      );
    class AudioContextStub {
      state = "suspended";
      currentTime = 0;
      destination = {};
      resume = resume;
      createBuffer = createBuffer;
      createBufferSource = createBufferSource;
      close = vi.fn(async () => undefined);
    }
    vi.stubGlobal("AudioContext", AudioContextStub);
    const playback = new RealtimeAudioPlayback();
    await playback.unlock();
    playback.begin("first", vi.fn());

    const enqueue = playback.enqueue(new ArrayBuffer(4), 24000);
    await Promise.resolve();
    playback.interrupt();
    resumePending?.();
    await enqueue;

    expect(createBuffer).not.toHaveBeenCalled();
    expect(createBufferSource).not.toHaveBeenCalled();
    vi.unstubAllGlobals();
  });

  it("does not treat a chunk gap as drained, and fences old callbacks", async () => {
    const sources: Array<{ onended: (() => void) | null; stop: () => void }> =
      [];
    class AudioContextStub {
      state = "running";
      currentTime = 0;
      destination = {};
      resume = vi.fn(async () => undefined);
      close = vi.fn(async () => undefined);
      createBuffer = () => ({
        duration: 0.1,
        getChannelData: () => new Float32Array(2),
      });
      createBufferSource = () => {
        const source = {
          onended: null as (() => void) | null,
          connect: vi.fn(),
          start: vi.fn(),
          stop: () => source.onended?.(),
        };
        sources.push(source);
        return source;
      };
    }
    vi.stubGlobal("AudioContext", AudioContextStub);
    const feedback = vi.fn();
    const playback = new RealtimeAudioPlayback();
    await playback.unlock();
    playback.begin("first", feedback);
    await playback.enqueue(new ArrayBuffer(4), 24000);
    sources[0].onended?.();
    expect(feedback).not.toHaveBeenCalled();
    await playback.enqueue(new ArrayBuffer(4), 24000);
    playback.seal("first");
    expect(feedback).not.toHaveBeenCalled();
    playback.interrupt();
    expect(feedback).toHaveBeenCalledExactlyOnceWith("first", "interrupted");
    playback.begin("second", feedback);
    await playback.enqueue(new ArrayBuffer(4), 24000);
    sources[1].onended?.();
    playback.seal("first");
    expect(feedback).toHaveBeenCalledTimes(1);
    playback.seal("second");
    sources[2].onended?.();
    expect(feedback).toHaveBeenLastCalledWith("second", "drained");
    await playback.close();
    expect(feedback).toHaveBeenCalledTimes(2);
    vi.unstubAllGlobals();
  });

  it("counts enqueue before resume so seal cannot acknowledge early", async () => {
    let resume: (() => void) | undefined;
    let ended: (() => void) | null = null;
    const context = {
      state: "running",
      currentTime: 0,
      destination: {},
      resume: vi.fn<() => Promise<void>>(async () => undefined),
      createBuffer: () => ({
        duration: 0.1,
        getChannelData: () => new Float32Array(2),
      }),
      createBufferSource: () => ({
        set onended(fn: () => void) {
          ended = fn;
        },
        connect: vi.fn(),
        start: vi.fn(),
        stop: vi.fn(),
      }),
    };
    vi.stubGlobal(
      "AudioContext",
      class {
        constructor() {
          return context;
        }
      },
    );
    const feedback = vi.fn();
    const playback = new RealtimeAudioPlayback();
    await playback.unlock();
    context.state = "suspended";
    context.resume.mockImplementation(
      () =>
        new Promise<void>((resolve) => {
          resume = resolve;
        }),
    );
    playback.begin("first", feedback);
    const pending = playback.enqueue(new ArrayBuffer(4), 24000);
    playback.seal("first");
    expect(feedback).not.toHaveBeenCalled();
    resume?.();
    await pending;
    expect(feedback).not.toHaveBeenCalled();
    (ended as (() => void) | null)?.();
    expect(feedback).toHaveBeenCalledExactlyOnceWith("first", "drained");
    vi.unstubAllGlobals();
  });
});
