# QwenPaw OpenUI

English | [中文](README_zh.md)

Interact with QwenPaw's answers directly. OpenUI brings tables, charts, forms, and sliders into Chat, so you can adjust inputs, compare results, and continue the conversation with your choices.

- **Explore as you read**: interfaces appear progressively alongside text and images.
- **See changes immediately**: connected values and charts update locally as you adjust controls.
- **Continue the conversation**: submit your choices when you want the assistant to take the next step.

Components follow QwenPaw's light or dark theme, accent color, and font-size setting, including dropdowns and dialogs.

## Install

With QwenPaw running, install the `qwenpaw-openui-0.1.0.zip` package:

```sh
qwenpaw plugin install /path/to/qwenpaw-openui-0.1.0.zip
```

Refresh Chat to start using it. The plugin uses your existing QwenPaw model configuration and includes its frontend runtime. No additional Node.js, npm, Python packages, or OpenUI API key are needed.

QwenPaw must support the `chat.codeBlock`, `chat.submit`, and `host.openExternalLink` plugin APIs.

If QwenPaw is stopped, extract the ZIP with your archive utility, install the contained directory, then start QwenPaw:

```sh
qwenpaw plugin install /path/to/extracted/qwenpaw-openui
```

## Get started

Open Chat and describe what you need:

> I'm having friends over for a barbecue this weekend. Make a shopping list for six people, with quantities I can adjust if the headcount changes.

The assistant chooses a suitable presentation for your request. Its answer might include a headcount slider, a shopping table, and a button to continue planning. The layout and connections between controls depend on what your model generates.

Moving sliders, selecting options, and filling in forms happens in the browser. When you click a continue or submit button, the selected information becomes a visible message in the conversation. Refreshing the page restores the interface's initial values.

## Available components

The plugin includes the official OpenUI catalog of 82 components and subcomponents:

| Category | Examples |
| --- | --- |
| Tables | Data tables, editable tables |
| Charts | Bar, line, area, pie, radar, and scatter charts |
| Forms | Text inputs, dropdowns, date pickers, sliders, checkboxes, radio buttons, switches |
| Layout | Cards, tabs, accordions, steps, carousels, modals |
| Content | Markdown, images, galleries, code, callouts, lists, and metrics |

The model describes components in `openui-lang`; the official OpenUI runtime parses them and handles interaction. Each UI block has its own state and can appear between passages of ordinary text in the same reply.

## Common questions

**Getting a text-only answer?** The assistant decides when an interface is useful. Describe the values you would like to adjust or the options you want to choose from.

**Interface not appearing?** Check that the plugin is enabled and refresh Chat. A missing-API message means your QwenPaw build needs the APIs listed above. If the generated interface fails to load, ask the assistant to regenerate it.

**How do I uninstall it?** Run the following command, then refresh Chat. UI blocks in previous replies will appear as ordinary code.

```sh
qwenpaw plugin uninstall qwenpaw-openui
```

## Development

Use QwenPaw's Python 3.11+ development environment and Node `^20.19.0`, `^22.13.0`, or `>=24.0.0`. From the repository root:

```sh
npm --prefix plugins/bundle/qwenpaw-openui/frontend ci
npm --prefix plugins/bundle/qwenpaw-openui/frontend test
python -m pytest tests/unit/plugins/test_openui.py -q
python scripts/pack/generate_plugin_metadata.py --only qwenpaw-openui
```

The package is written to `dist/plugins/bundle/qwenpaw-openui/qwenpaw-openui-0.1.0.zip`. Use this ZIP or its extracted contents for local installation too; frontend source and development dependencies are excluded from the package.

[examples/seeds.openui](examples/seeds.openui) provides a reproducible interaction example: moving the slider from 5 to 8 updates total experiment runs from 35 to 56, and the continue button submits the current value.

### Integration

The frontend registers an `openui-lang` renderer and adds a capability marker to chat requests. Backend middleware adds language and component instructions generated from the official library to eligible Console requests.

Streaming updates use the official parser to display complete constructs progressively. The renderer stays mounted, and named child components retain their identity as later content arrives, preserving existing inputs and selections.

`@Set` and `@Reset` update local state. `@ToAssistant` uses QwenPaw's message queue to submit its message, explicit context, and form values. `@OpenUrl` opens HTTP(S) links through the host. Query, Mutation, tool providers, and patches to historical UI are not integrated.

The build produces `dist/index.js` and `dist/system-prompt.txt`. The frontend shares host React/ReactDOM and scopes styles to the plugin interface. `frontend/src/qwenpaw-host.d.ts` holds a public SDK type snapshot; update it when adopting host API changes.

The official `ThemeProvider` maps OpenUI's visual tokens to QwenPaw's `--app-*` tokens. Font changes update chart measurements while preserving component state. OpenUI retains its component layouts and chart series palettes.

The runtime interprets `openui-lang` through registered components, built-in functions, and host actions. Release-bundle tests cover script attempts, unsafe links, unsupported tool calls, and normal local interactions.
