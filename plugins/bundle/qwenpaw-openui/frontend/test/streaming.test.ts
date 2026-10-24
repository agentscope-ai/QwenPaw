import { expect, it } from "vitest";
import { createUIStream } from "../src/streaming";

const first =
  'root = Stack([heading, later])\nheading = TextContent("Ready")\n';
const source = first + 'later = TextContent("A quote: \\" and a newline: \\n")';

it.each([1, 7, 37, source.length])(
  "renders complete constructs across chunks of %i characters",
  (size) => {
    const stream = createUIStream();
    let previous = "";
    for (let i = 0; i <= source.length; i += size) {
      const frame = stream(source.slice(0, i), true);
      expect(frame.error).toBe(false);
      expect(frame.response.startsWith(previous)).toBe(true);
      if (i >= first.length)
        expect(frame.response).toContain('TextContent("Ready")');
      previous = frame.response;
    }
    expect(stream(source, false)).toEqual({ response: source, error: false });
  },
);

it("keeps the previous frame while a multiline component is unfinished", () => {
  const stream = createUIStream();
  stream(first, true);
  const partial = first + 'later = TextContent(\n"Second card"';
  expect(stream(partial, true)).toEqual({ response: first, error: false });
  expect(stream(partial + "\n)", true)).toEqual({
    response: partial + "\n)",
    error: false,
  });
});

it("accepts Markdown's synthetic trailing newline without clearing an earlier frame", () => {
  const stream = createUIStream();
  stream(first, true);
  // Markdown terminates every code-node payload with a newline, including
  // the current partial line. That newline moves as more tokens arrive.
  stream(first + "later\n", true);
  const frame = stream(first + "later = TextContent(\n", true);
  expect(frame.response).toContain('TextContent("Ready")');
});

it("clears old content when the program is replaced and rejects invalid completion", () => {
  const stream = createUIStream();
  stream(source, false);
  expect(stream('root = TextContent("replacement', true)).toEqual({
    response: "",
    error: false,
  });
  expect(stream('root = TextContent("replacement', false)).toEqual({
    response: "",
    error: true,
  });
  expect(stream(first, false)).toEqual({ response: "", error: true });
});

it.each(["Query", "Mutation"])(
  "rejects %s before passing it to the runtime",
  (call) => {
    const stream = createUIStream();
    const program = `root = TextContent("hello")\nforbidden = ${call}("fetch", {})`;
    expect(stream(program, true)).toEqual({ response: "", error: true });
    expect(stream(program, false)).toEqual({ response: "", error: true });
  },
);
