# QwenPaw Design Language

> Quiet surfaces. Precise structure. Orange with purpose. Motion that follows intent.

This document defines QwenPaw's visual identity and interaction language across the product. It guides reusable components and future design decisions; feature requirements, page layouts, and implementation progress belong in their respective documents under `docs/design/`.

## Character and principles

QwenPaw should feel calm, capable, and carefully made, with the clarity of a professional instrument and the responsiveness of an object in your hand. Its identity comes from warm neutral surfaces, deliberate typography, and a recognizable orange accent.

- **Clarity:** make content, available actions, and current state immediately understandable.
- **Precision:** align edges, baselines, spacing, and optical centers. Every visible layer needs a purpose.
- **Restraint:** concentrate emphasis on the current task. Quiet surroundings make a meaningful detail more effective.
- **Continuity:** preserve the relationship between an action, its source, and its result.
- **Agency:** respond immediately, allow interruption, and keep navigation and dismissal predictable.
- **Consistency:** reuse the same visual and physical behavior for the same meaning.

Apple informs hierarchy, materials, typography, and direct manipulation. Rare UI informs the craft of individual interactions. QwenPaw translates these references into its own orange identity and shared component vocabulary.

## Color and brand identity

**QwenPaw's default brand orange is `#FF7F16` (RGB 255, 127, 22).** QwenPaw supports custom themes: this color defines the built-in identity, not a mandatory runtime UI color. Use the active theme's accent consistently for primary emphasis, selected states, active controls, and restrained interaction highlights. Do not introduce a competing decorative accent palette.

The following values reflect the built-in theme in [`console/src/styles/tokens.css`](console/src/styles/tokens.css). Components must consume semantic tokens instead of repeating literal hex values. Theme overrides remain authoritative at runtime.

| Role            | Token                  | Light theme              | Dark theme           |
| --------------- | ---------------------- | ------------------------ | -------------------- |
| Primary accent  | `--app-accent`         | `#FF7F16`                | `#FF9D4D`            |
| Hover accent    | `--app-accent-hover`   | `#FF9D4D`                | `#FF9D4D`            |
| Canvas          | `--app-bg`             | `#F9F8F4`                | `#141414`            |
| Content surface | `--app-surface`        | `#FFFFFF`                | `#1F1F1F`            |
| Subtle surface  | `--app-surface-subtle` | `#FAF9F7`                | `#1A1A1A`            |
| Raised surface  | `--app-surface-raised` | `#FFFFFF`                | `#262626`            |
| Default border  | `--app-border`         | `#EAE8E7`                | White at 12% opacity |
| Primary text    | `--app-text`           | `#141413` at 88% opacity | White at 85% opacity |
| Secondary text  | `--app-text-secondary` | `#141413` at 58% opacity | White at 65% opacity |

`#FF9D4D` (RGB 255, 157, 77) is the lighter orange variant for hover and dark surfaces; it does not replace the canonical brand color.

Derived accent tokens keep the family coherent:

| Role           | Token                 | Definition                                                            |
| -------------- | --------------------- | --------------------------------------------------------------------- |
| Pressed accent | `--app-accent-active` | 80% current accent mixed with black                                   |
| Accent text    | `--app-accent-text`   | Light: 72% accent mixed with black; dark: 60% accent mixed with white |
| Selected fill  | `--app-accent-soft`   | Light: accent at 10% opacity; dark: accent at 16% opacity             |
| Accent outline | `--app-accent-border` | Light: accent at 42% opacity; dark: accent at 50% opacity             |
| Keyboard focus | `--app-focus-ring`    | Uses `--app-accent-text`                                              |

These are sRGB mixes or transparent overlays, not additional independent brand colors. Their rendered appearance depends on the theme and underlying surface.

### Custom themes and token precedence

All literal colors and color-mix recipes in this document describe the built-in theme defaults. User-selected custom theme values take precedence for the properties they customize; unspecified properties use the existing theme system's defaults. Light and dark variants must resolve through that same system.

- Consume the active semantic tokens for accents, surfaces, text, borders, focus, and interaction states. Do not hardcode the default orange or neutral palette inside components.
- Derive rail gradients, glows, reflections, selected fills, and animated highlights from the resolved theme tokens. They must follow a theme change just like static controls, including while a panel is open or an animation is running.
- References to “orange” elsewhere in this document describe the default visual treatment. Under a custom theme, apply the same hierarchy and behavior using that theme's accent family.
- Preserve theme-defined state colors and contrast adjustments. Built-in mix percentages are defaults, not a reason to overwrite customized semantic tokens or assume every accent has sufficient contrast.
- Reuse the existing custom-theme mechanism. This design language does not introduce a second palette configuration, a compatibility layer, or per-component theme overrides.

### Color discipline

- Keep most of the interface neutral. Orange should reveal priority and state rather than cover large areas by default.
- Use soft orange fills and clear labels for selection. Use a solid orange fill when an action needs stronger emphasis.
- Use the contrast-adjusted accent text token for small orange text. Do not assume white text is readable on `#FF7F16`; choose a tested foreground/background pair.
- Preserve semantic success, warning, error, and information colors when they carry distinct meaning. Pair them with text or icons; orange must not blur those distinctions.
- Keep decorative reflections and glows within the active accent family, orange by default. Avoid rainbow borders and unrelated gradients in everyday work surfaces.
- Dark mode uses its own material hierarchy and lighter accent. Do not invert a light theme mechanically.

## Typography and iconography

Use the platform system font stack: `-apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif`, with appropriate system fallbacks for other scripts. This gives QwenPaw familiar, readable text on macOS, Windows, and Linux.

| Role              | Starting size | Weight  | Line height | Tracking        |
| ----------------- | ------------- | ------- | ----------- | --------------- |
| Display           | 32–48px       | 600     | 1.10–1.15   | Around -0.02em  |
| Heading           | 22–28px       | 600     | 1.20–1.30   | Around -0.015em |
| Section title     | 16–18px       | 600     | 1.35–1.45   | Near 0          |
| Body and controls | 14–16px       | 400–500 | 1.45–1.60   | 0               |
| Supporting text   | 12–13px       | 400–500 | 1.40–1.50   | 0               |

These are QwenPaw starting values, not fixed dimensions or Apple specifications. Express text sizes in relative units, support user scaling, and adjust tracking for the script. Keep long prose around 60–75 characters per line. Use tabular numerals for changing numeric values; reserve monospace for code and identifiers.

Use sentence case and concise action labels. Keep essential state and errors visible. Secondary explanations may appear on demand, accessible through focus and touch as well as hover.

### Minimal visible copy

Keep the interface concise and easy to scan. Show the information needed to recognize a control, understand its current state, and take the next action. Avoid explanatory paragraphs beneath every heading, repeated descriptions, redundant labels, and persistent instructions for familiar interactions.

- Put secondary explanations, terminology, examples, and configuration guidance behind a small question-mark help icon from `lucide-react`, placed beside the relevant label. Do not repeat the same explanation elsewhere in the visible layout.
- Use a short tooltip for brief, noninteractive help. Show it on hover and keyboard focus, not hover alone. Give its trigger an accessible name that identifies the subject.
- Use a click/tap-accessible popover for longer explanations or content with links and actions. A question-mark control must work on touch devices; interactive content must not live inside a hover-only tooltip.
- Keep help open long enough to read, support predictable dismissal, and preserve keyboard focus. Reuse existing accessible tooltip and popover primitives instead of building custom hover behavior.
- Keep essential labels, selected values, actionable errors, pending or failed save states, and consequential action details visible. Do not hide information required to make a safe, informed decision behind a question mark.
- Prefer one concise label over a title plus a sentence that repeats it. Use icon-only actions only when their meaning is familiar, with accessible names and hover/focus help; minimal copy must not make controls ambiguous.

Review visible copy by asking: does this text identify something, show meaningful state, or enable the next action? If it only explains how or why, move it into contextual help unless it is essential at that moment.

**Use `lucide-react` for interface icons.** Do not use emoji as controls or introduce another icon library. Start with 16px icons in compact controls, 20px for standard controls, and 24px for larger actions; use a consistent stroke weight, typically 1.75–2. Match optical alignment to the text rather than relying only on bounding boxes. Icon-only controls need accessible names and hover/focus help.

## Spacing, geometry, and composition

Use a 4px spacing unit with a restrained scale: **4, 8, 12, 16, 24, 32, 48**. Default to 16px horizontal gaps and 16px or 24px vertical gaps. Use 24px content padding on standard surfaces, reducing toward 16px when space is limited.

- Align related surfaces and controls to shared edges and baselines.
- Use proximity to establish relationships before adding borders or containers.
- Let importance determine area. Bento composition can combine a dominant surface with smaller supporting surfaces while preserving a common grid.
- Use cards for meaningful grouping, not as a wrapper around every line of content.
- Give each group one clear visual entry point. Avoid equal-weight tiles competing for attention.
- Keep empty space intentional: enough to distinguish groups, without distancing controls from the content they affect.

### Corners

Use a small hierarchy of radii: approximately 8–12px for compact controls, 16px for small surfaces, and 24px for larger cards or panels. Use a full capsule only when its shape supports the control's identity.

Nested contours should feel concentric. Start an inner radius near the outer radius minus its inset, then adjust optically. Avoid a tiny inner corner floating inside an excessively rounded shell.

The supplied image's “short edge × 18%” rule is a proportional study for small forms, **not an Apple-wide formula**. Do not apply it mechanically to large panels, editors, or wide rectangles.

### Responsive composition

Reflow according to content, not device labels. Reduce columns before compressing controls, preserve reading order, and retain useful alignment when groups stack. Scale outer padding with available width. Account for safe areas, zoom, long translations, and the software keyboard.

No essential interaction may depend on hover, a precision pointer, or a drag gesture alone. Use comfortably sized touch targets, aiming for at least 44 × 44 CSS px where touch is expected, even when the visible icon is smaller.

## Surfaces, light, and depth

The reference images suggest coherent rounded geometry, varied but aligned card proportions, subtle surface separation, and soft directional light. Translate those qualities into working UI with lower contrast and less theatrical shadow than a presentation collage.

- Separate the canvas and content through a small tonal difference, supported by a fine border or quiet shadow when needed.
- Keep normal content surfaces largely opaque. Reserve translucency for floating layers where seeing context underneath helps orientation.
- Use stronger depth for genuinely raised surfaces. Static content should not appear to hover as strongly as a temporary panel.
- Keep light direction consistent. A restrained upper-edge highlight and soft shadow can suggest material without adding visual noise.
- Protect text from glare, blur, and moving light. Decorative layers must not intercept input.
- Avoid stacking translucent layers; provide solid alternatives for contrast and reduced-transparency preferences.

The screenshot's `#F5F5F7` canvas and white card illustrate tonal separation. QwenPaw retains its actual `#F9F8F4` canvas token. The stated “1% gray difference” is visual shorthand, not a measured requirement or a guarantee of accessible contrast.

## Interaction grammar

Controls should express what can be done and provide a clear response when it happens. Define default, hover, focus, pressed, selected, disabled, pending, and error states wherever applicable. Keep geometry stable between them.

Use switches for standalone binary settings, segmented controls for a few short exclusive choices, and searchable selection for long lists. When enabling a capability and adjusting its amount form one natural action, consider the integrated magnetic rail described below. Use free text when the content actually requires it. These are reusable selection principles, not mandates for particular product modules.

Pending feedback must reflect real work; completion feedback must reflect a confirmed result. Failures should explain the next useful action and preserve recoverable input. Prefer inline status to disruptive announcements for routine changes.

## Interaction craft

QwenPaw should contain small, thoughtful interactions that make a control easier to understand and more satisfying to use. Craft comes from connecting shape, state, movement, and feedback around one intention. A well-designed control can feel distinctive without adding visual decoration or extra steps.

### Compose around one intention

- **Combine related decisions:** enabling a capability and choosing its intensity can occupy one continuous control when their relationship is clear. Keep unrelated actions separate.
- **Make boundaries tangible:** a detent, a small gap, or a change in resistance can distinguish a discrete mode change from continuous adjustment. Pair the physical cue with a readable state.
- **Keep feedback coupled:** the handle, rail, label, and number should describe the same target state. They may move differently, but must feel like one response.
- **Reveal precision on demand:** direct manipulation supports exploration; an editable value supports exact input. Both operate on the same state.
- **Make reversal easy:** an accessible reset action and predictable cancellation reduce the cost of exploration.
- **Use a signature detail selectively:** one magnetic stop or coordinated digit roll can give a control character. Repeating every flourish across every component dilutes the effect.

Combining effects is appropriate when each explains a different part of the same action. Magnetic settling explains a boundary; rolling digits explain a changing quantity. Their combination is a coherent interaction, not a stack of unrelated animations.

### MAGNETIC ENABLE RAIL

**Reference:** the user-supplied thinking-budget visual combines a separate low-end stop, an orange rail, a raised circular thumb, and a numeric readout. The requested behavior adds magnetic Off/On transitions and rolling digits. This specification translates that reference into a reusable pattern; exact GIF timing has not been measured.

**Use when:** a capability has a supported Off state and a meaningful adjustable amount when enabled. The intended gesture is “turn it on and set how much.” Examples may include an effort or intensity budget, but the pattern does not prescribe a product module or an API format.

**Do not use when:** the setting is only binary, its choices are unrelated categories, or the underlying capability cannot be disabled. A minimum positive amount is not automatically equivalent to Off. Inheritance or automatic behavior also remains distinct from explicit Off.

#### Anatomy and visual behavior

| Part        | Design purpose                                                | Behavior                                                                                                       |
| ----------- | ------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------- |
| Off detent  | A small, visibly distinct stop before the active range        | Holds the thumb at the disabled state; exposes a readable Off label                                            |
| On detent   | The beginning of the supported active range                   | Marks the minimum enabled amount and the transition into adjustment                                            |
| Active rail | A continuous, rounded orange track                            | Encodes increasing amount through position; a restrained light-to-deep orange gradient may reinforce direction |
| Thumb       | A raised circular surface with a fine outline and soft shadow | Tracks input directly and settles into meaningful stops without changing its hit area                          |
| Readout     | Stable-width number plus stationary unit                      | Rolls toward the selected amount; displays Off as text in the disabled state                                   |
| Reset       | A quiet Lucide icon action with an accessible name            | Restores the declared default or inheritance policy and updates the entire control together                    |

Use `--app-accent` (`#FF7F16` in the built-in light theme) as the rail's anchor. Derive lighter and deeper stops from the same accent token. Keep the surface and thumb readable in both themes; do not copy the reference's exact shadows or assume its endpoint colors are brand tokens. A gap between Off and the active rail should communicate a mode boundary while retaining a continuous touch hit region.

The 0/1 relationship describes disabled/enabled semantics. **It does not imply that one token is the minimum budget, that a model accepts numeric 0/1 flags, or that a new wire format is required.** Use supported bounds, increments, and the existing domain representation.

#### Interaction sequence

1. **At rest:** show the current mode and amount honestly. Off parks the thumb at the separate detent; an enabled value positions it on the active rail. Inherited state remains identifiable rather than silently becoming an explicit value.
2. **Engage:** pointer-down gives immediate thumb feedback without changing the value merely because the thumb was touched. Preserve the grab offset. Clicking or tapping another position on the rail selects its corresponding valid target.
3. **Leave Off:** dragging past the activation boundary crosses a short magnetic transition and enters at the minimum valid amount. Continuing the same gesture adjusts the amount; no second activation is required.
4. **Adjust:** the thumb follows the pointer with minimal lag. The rail, optional intensity label, and readout all derive from the same quantized target value. Large changes must not queue outdated digit animations.
5. **Approach Off:** entry into the Off capture zone snaps to the detached stop and changes the label to Off. The thumb remains there until the pointer clears a wider exit zone. Crossing back and forth near a single pixel must not toggle repeatedly.
6. **Release:** settle at the valid selected value or detent using a short, highly damped spring. Velocity can influence the visual settle, but must not fling the setting into Off or change the chosen amount after release.
7. **Cancel or reset:** cancellation restores the pre-gesture draft. Reset resolves the actual default or inherited value and moves the thumb, label, and readout together. It must not merely move the thumb to the middle of the rail.

#### Magnetic geometry and hysteresis

Use explicit input zones, not a slow spring across the whole rail. A conceptual ordered domain is `Off → minimum enabled amount → … → maximum amount`; the Off stop occupies a small dedicated part of the track. Map only the remaining active region to the numeric range.

For a prototype, start with an Off capture distance around 8 CSS px and an exit distance around 14 CSS px, measured from the Off detent along the rail. These are tuning suggestions: keep both zones small relative to the control and separated from the On detent. Adapt them for narrow rails and coarse input. Preserve a large touch target without enlarging the semantic Off zone until it swallows low positive values.

While enabled, enter Off only inside the capture zone. While Off, remain there until input crosses the larger exit distance toward the active rail. This difference is hysteresis: it prevents mode flicker from hand jitter. Apply a similarly bounded attraction to the On detent if needed; do not add arbitrary magnets throughout the range. Magnetic resolution must determine the selected state, not just the thumb's appearance.

Within the active region, map position to the supported numeric range and quantize to its valid increment. Linear mapping is the default. Use a nonlinear mapping only when it improves access to meaningful values and its scale is communicated. Recompute geometry after resize; respect the interface's directional conventions.

#### Implementation recipe

1. **Reuse the foundation:** extend an appropriate shared slider using the existing accessible slider primitive. `NumberSlider` already combines the project's slider with `@number-flow/react` and optional exact input; it is a starting point, not an implementation of magnetic endpoints. Keep this behavior in a shared interaction component rather than duplicating it in feature pages.
2. **Separate semantic state from animation:** use the existing domain model to represent mode and amount. Keep draft selection, the pre-gesture value, and any persistence status distinct. Derive position, label, and displayed target from one resolved selection. A motion value must never become the source of truth for saving.
3. **Resolve input once:** translate the slider primitive's change events into the ordered logical domain, applying bounds, quantization, and detent hysteresis. Keep any logical Off index inside the control; translate back to the existing domain model before committing. Do not infer state from CSS transforms or introduce a second drag engine over the primitive.
4. **Animate the presentation:** use `motion/react` for detent settling and small thumb feedback. Let direct dragging remain responsive. Do not run a catch-up spring that leaves the thumb trailing the finger. Input arriving during settling retargets from the visible position.
5. **Coordinate the digits:** pass the resolved numeric target to `@number-flow/react`; keep units and surrounding layout still. Start with a short transition around 120–180ms and retarget immediately. The readout represents the selected target even while its glyphs roll. Crossfade or directly replace the number with Off; do not roll through fabricated token values to express a mode change.
6. **Support precision and persistence:** allow click or keyboard activation of the readout to edit a valid exact value when useful. Invalid input retains the last valid selection and explains the constraint. Follow the product's established commit policy; do not send a request for each animation frame. Where a setting is persisted, a failed commit keeps the attempted value recoverable and clearly distinguishes it from the confirmed value.

If a last enabled amount is retained, keep it separate from Off. Continuous dragging out of Off always enters the active range at its beginning, avoiding a surprise jump. Restoring a remembered amount requires an explicitly defined re-enable action; do not invent a second hidden gesture.

#### Keyboard, assistive technology, and reduced motion

- Expose one understandable ordered control. Give it a name, valid bounds, and a value description such as “Off” or “36,542 tokens.” The example number is illustrative, not a default budget.
- Arrow keys move by valid increments; moving below the minimum enabled value reaches Off only when supported. From Off, the forward arrow enters the minimum enabled amount. Home selects Off when available, otherwise the minimum; End selects the maximum. Define larger keyboard steps only when useful for the range.
- Keep a clear focus indicator on the stable control. The reset action and exact-value editor must also be keyboard accessible; tooltips cannot be the only way to discover their meaning.
- Offer readable mode text alongside position and color. A visual 0/1 boundary alone is insufficient. Keep the accessible value synchronized with the semantic target, not individual rolling frames.
- Under reduced motion, retain logical snapping and hysteresis but update the thumb and number directly. Remove decorative rebound and digit rolling. The control must remain equally understandable when nothing animates.

#### Review criteria

- [ ] Off, minimum enabled amount, inherited state, and unsupported disabling remain distinct.
- [ ] Slow movement and jitter around the boundary do not chatter between modes.
- [ ] One uninterrupted gesture can enable, adjust, reverse, and disable predictably.
- [ ] Rail, thumb, state label, numeric target, and committed value remain consistent.
- [ ] Fast input does not accumulate digit animations or cause a delayed mode change.
- [ ] Cancellation, reset, exact input, and keyboard navigation have predictable outcomes.
- [ ] Resize, touch scrolling, theme changes, and reduced motion preserve the interaction.

### Carry the lesson into other controls

The reusable idea is to make a meaningful boundary tangible and coordinate its feedback. A segmented selection can move one shared indicator between positions; an adjustable value can reveal exact input in place; a reset can visibly return a control to its resolved default. Each detail should reduce effort, clarify state, or explain a relationship. Do not add detents, morphs, rolling counters, or hidden gestures where they have no semantic job.

## Motion language

Motion explains cause, continuity, and physical response. A still frame should remain clear without it. QwenPaw uses restrained springs, anchored transformations, and immediate press feedback as its baseline; expressive light effects are optional accents.

Apple's _Designing Fluid Interfaces_ informs four core behaviors: respond on contact, follow direct manipulation continuously, preserve motion when gestures end, and allow the user to redirect an interaction. See the [Apple reference](https://developer.apple.com/videos/play/wwdc2018/803/).

### Shared motion rules

- Show press feedback on pointer-down; commit the action on release or the appropriate keyboard activation.
- Keep gesture-driven motion attached to the pointer. Hand release velocity into the settling behavior where supported.
- Start a redirected animation from its current visible state. Never block input until an animation finishes.
- Keep enter and exit paths spatially related and anchor expansion to its source when that relationship is meaningful.
- Default to high damping with little or no overshoot. Reserve a small rebound for tangible press or momentum feedback.
- Treat roughly 100–180ms for small state transitions and 250–400ms for larger visual transitions as tuning ranges. Spring settling is not a guaranteed fixed duration.
- Prefer transform and opacity. Bound and profile size, blur, gradient, and shadow effects; avoid continuous expensive repainting.
- Give each interaction one dominant effect. Do not combine tilt, glow, morphing, and stagger simply because they are available.

The following eight patterns are a reusable vocabulary. Their numeric ranges are proposed QwenPaw tuning guidance, not claims about existing implementation or external library defaults.

### TILT GLARE

An interactive surface gently tilts in perspective while a soft radial reflection follows pointer or touch position. Release, pointer exit, and cancellation return it to rest with a damped spring.

Start with rotation capped around 2–4 degrees and a low-opacity highlight. Keep the hit area stable. Use this for occasional tactile preview surfaces; reading, editing, and dense controls should remain steady. Touch behavior must preserve scrolling and must not activate accidentally during a scroll.

**Interaction contract:** idle → pointer tracking or intentional touch contact → damped return. Keyboard focus receives an equivalent static highlight. Leaving, releasing, losing capture, or cancelling always clears the effect; a new contact can interrupt the return.

**Implementation recipe:** begin with the existing `InteractiveCard` wrapper. Use `motion/react` motion values for normalized pointer coordinates and springs for rotation. Measure against a stable outer hit area; map horizontal position to Y rotation and vertical position to inverse X rotation. Apply perspective to the parent and rotation to an inner visual layer. Bind the same coordinates to the center of a radial highlight, clipped to the surface and marked `pointer-events: none`. Update motion values rather than React state on every pointer frame. Keep geometry measurements current after resize and scroll. On touch, abandon the decorative effect when scrolling wins gesture arbitration.

**Verify:** center and edge tracking, rapid re-entry, touch scrolling, pointer cancellation, and text legibility. The surface must return to zero rotation without a snap or a stuck highlight.

**Reduced motion:** use a static border or tonal highlight without perspective or tracking glare.

### FLUID MORPH

A capsule trigger grows into a related panel through a continuous change in position, size, and corner radius. Use a highly damped spring with no obvious wobble. Closing restores the relationship to the trigger.

Preserve the perceived shell while introducing the panel's content at a readable size. Avoid stretching text and icons. Opening a modal still requires correct dialog semantics, focus placement, dismissal, and focus restoration.

**Interaction contract:** activate capsule → expand shell → reveal panel content; dismiss → retract shell → restore trigger. An interruption retargets from the visible geometry. The opening action executes once, and closing never activates the trigger underneath.

**Implementation recipe:** use the existing `SharedModal` foundation where applicable, retaining the accessible dialog layer. Give the trigger shell and panel shell a stable, instance-specific `layoutId`; use `AnimatePresence` to retain the departing visual during closure. Set final dimensions through layout styles and animate numeric corner radii from half the trigger height to the panel radius. Start near the existing wrapper's spring settings (`stiffness: 360`, `damping: 38`, default mass), then tune for a smooth settle. Fade content separately and use child layout correction where needed. Keep the source footprint in the layout, and remove any visually duplicated shell from keyboard and accessibility navigation. Coordinate fixed portals and scroll offsets explicitly. See [Motion layout animation](https://motion.dev/docs/react-layout-animations).

**Verify:** open-close-open during travel, viewport resize, long panel content, Escape dismissal, and focus restoration. No intermediate frame should expose two actionable copies or visibly stretch labels.

**Reduced motion:** switch directly to the final geometry, optionally using a brief crossfade.

### SHARED ELEMENT

A compact surface expands into a detailed surface while retaining recognizable container, background, and content anchors. Returning retraces that spatial relationship.

Coordinate container and contextual background scaling only where it helps explain the transition. Keep moving text legible, preserve scroll context, and avoid full-screen zoom as routine decoration. If the origin no longer exists, use a simple fade instead of inventing a destination.

**Interaction contract:** activate a compact object → expand that same object's identity → interact with detail → return to its origin. Unlike Fluid Morph, the continuity here belongs to an object and its content, not simply an action trigger.

**Implementation recipe:** use `motion/react` shared layout with stable entity-based IDs for the shell and any genuine shared visual anchors. Coordinate related participants with `LayoutGroup`; retain exiting content with `AnimatePresence`. Preserve the source's space and scroll position until the return completes. Give scroll containers `layoutScroll` and fixed motion roots `layoutRoot` when required by their structure. Keep asynchronous detail loading inside the destination shell so data arrival does not restart expansion. Any background scale should be slight, around 1 → 0.98, and isolated from fixed controls. Route transitions must retain the necessary animation participants; never delay navigation solely to play an effect.

**Verify:** return after scrolling, slow detail loading, rapid reversal, browser Back, and disappearance of the original item. Restore focus to the source or a meaningful surviving control.

**Reduced motion:** preserve content and focus continuity with a static replacement or crossfade.

### SNAP ODOMETER

A chart cursor follows horizontal input and settles onto a real data point; its associated numeric readout rolls smoothly to the same selected value.

The cursor, label, and value must share one selection state. Use tabular numerals, stable number widths, consistent precision, and units. Rapid scrubbing should retarget the latest value without a queue of stale animations. Provide keyboard navigation and readable text equivalents without announcing every animation frame.

**Interaction contract:** hover or drag across a chart → select the nearest valid sample → move the marker and roll the readout together. Left/Right selects adjacent samples, and Home/End selects the endpoints when the chart control has focus. Touch release leaves the selected sample inspectable.

**Implementation recipe:** start with `SnapTrend` and `@number-flow/react`. Convert the pointer into the chart's plot coordinates, excluding margins, and choose the nearest sample by rendered X position; do not assume evenly spaced timestamps. Store one selected sample ID or index and derive the marker, tooltip, and target number from it. Feed the actual numeric value into NumberFlow rather than implementing digit columns. Use Motion only for marker settling; during fast dragging, prioritize proximity to the finger over spring lag. Reserve readout width, keep units stable, and show missing values as missing rather than zero. Expose the selected value as accessible text; announce only useful selection changes.

**Verify:** irregular sample spacing, negative values, decimal and digit-count changes, empty data, rapid direction changes, and keyboard access. Marker and readout must never describe different samples.

**Reduced motion:** update the cursor and number directly with no rolling digits.

### BOTTOM SHEET

A sheet tracks vertical dragging, resists progressively at its bounds, and settles at a valid snap point using release position and velocity. The gesture should flow into the settling spring without a visible stop.

Provide explicit dismissal and keyboard access alongside dragging. Coordinate content scrolling with sheet dragging; account for safe areas and the software keyboard. Modal sheets manage focus and background interaction consistently, and restore focus on close.

**Interaction contract:** open → settle at an initial anchor → drag with direct tracking → release toward a valid anchor or permitted dismissal. Pulling beyond a bound produces increasing resistance. A slow release favors the nearby anchor; a deliberate flick may reach the next anchor based on velocity.

**Implementation recipe:** reuse `BottomSheet`, built on `vaul`, with controlled open state and content-appropriate `snapPoints`. The current wrapper exposes 0.5 and 0.9 viewport fractions in its tall configuration; these are existing examples, not universal anchors. Keep the active snap state synchronized with opening and viewport changes. Let Vaul own gesture recognition, scroll coordination, and settling; do not attach a competing Motion drag controller to the same sheet. Keep `Drawer.Title`, the explicit close control, overlay behavior, and focus restoration in the shared wrapper. Verify the installed package's velocity and resistance behavior before adding any wrapper-level adjustment. Constrain content height to the visible sheet and account for dynamic viewport height and safe-area insets.

**Verify:** slow drags, fast flicks, dragging at content scroll boundaries, interrupted settling, keyboard opening, and mobile keyboard appearance. No unreachable anchor, hidden close action, or accidental dismissal during content scrolling is acceptable.

**Reduced motion:** retain direct user control, remove decorative elasticity, and settle without a travel animation.

### CONIC GLOW

A fine conic-gradient outline and a diffuse glow beneath a surface create a restrained moment of emphasis. Use the QwenPaw orange family, a thin edge, and low-intensity light.

Reserve this for a focal interaction or meaningful temporary state. Keep it out of routine text surfaces and dense collections. Prefer a short activation over an indefinite breathing loop; stop when inactive or offscreen. The effect cannot be the only indication of progress or state.

**Interaction contract:** an explicit focal state activates the outline → a controlled sweep or gentle pulse acknowledges it → the surface returns to rest when the state ends. Routine hovering over a dense collection should not light up the entire collection.

**Implementation recipe:** start with `RunningGlow` and use Motion for playback and opacity. Place a rotating conic-gradient layer behind a fixed rounded mask or inset surface so only a roughly 1px edge remains visible. Keep the mask stationary as the gradient rotates. Add a separate orange glow beneath the lower edge, with a fixed blur; animate its opacity rather than its blur radius. Derive every stop from accent tokens and transparency. Keep both layers noninteractive and hidden from assistive technology. Start with one 1.5–2.5 second sweep and a low-opacity glow. If a persistent state requires repetition, provide a way to stop the decorative animation and pause it when hidden or offscreen; static status remains visible.

**Verify:** clipping at corners, neighboring content, dark-theme brightness, scrolling cost, offscreen suspension, and state termination. A fallback solid outline must retain the same meaning.

**Reduced motion:** use a static orange outline without rotation or breathing.

### STAGGER CASCADE

A small group enters with a short stagger and a subtle upward spring, helping the eye follow a coherent arrival.

Start around 20–40ms between items and 4–8px of travel. Cap total stagger delay around 200ms; long or virtualized collections must not make people wait. Do not replay the entrance after routine edits or every scroll. Keep overshoot barely perceptible.

**Interaction contract:** reveal a new group → establish its first item immediately → let nearby items settle in reading order. Adding one item animates that item; updating or reordering an existing group must not replay its entrance.

**Implementation recipe:** reuse `Cascade` with Motion variants or per-item transitions. Animate opacity and Y translation using stable item keys. Bound each delay with `min(index × stagger, 0.2 seconds)` and animate only the newly introduced visible group. Keep entry state separate from filtering, selection, and background refresh state. Use a strongly damped spring; do not add a second bounce to nested children. The layout should occupy its final space from the beginning. If keyboard focus enters an item before its reveal finishes, make that item fully visible immediately.

**Verify:** large collections, insertion, filtering, virtualized scrolling, repeated opening, and early keyboard input. The effect must not defer data availability, hide focused controls, or cause layout shifts.

**Reduced motion:** display the group together without travel or stagger.

### PRESS SCALE

A button compresses immediately toward `scale(0.96)` with a restrained inset shadow, then releases with a short spring and a slight overshoot where appropriate.

Keep the hit target stable and the label legible. Small or dense controls may use a milder scale or tonal feedback. Support cancellation and keyboard input; do not apply spring feedback to disabled controls. Visual tactility does not require sound or device vibration.

**Interaction contract:** contact → immediate compression and inset depth → release inside commits once and settles → release outside cancels and settles. Keyboard activation follows native button semantics, including Space cancellation and Enter activation as applicable.

**Implementation recipe:** reuse `PressFeedback` with a semantic button and Motion press handling such as `whileTap`. Transform an inner visual layer when needed to preserve a stable outer hit target. Start at scale 1, compress toward 0.96, and spring back to 1; tune damping for at most one very small overshoot, visually below about 1.01. Use a subtle inset-shadow state instead of animating a large shadow blur. Let native click handling own activation rather than executing the action in both pointer and keyboard handlers. Keep focus rings outside clipped visual layers, reset on cancellation and disabled-state changes, and allow repeated presses to retarget the spring immediately.

**Verify:** pointer down/up, drag-away cancellation, rapid repeated presses, Space/Enter, loss of focus, and a control becoming disabled mid-press. One completed activation must produce one action.

**Reduced motion:** use an immediate fill or inset-shadow change without scaling or rebound.

## Implementation discipline

Use established packages and existing shared components for animation, gestures, accessible interaction, and assets. Do not write a custom spring solver, drag engine, number ticker, or icon set for these effects.

The current dependency set in [`console/package.json`](console/package.json) already includes:

| Need                                        | Existing package                     |
| ------------------------------------------- | ------------------------------------ |
| Springs, presence, and shared layout motion | `motion`                             |
| Drawer and sheet foundation                 | `vaul`                               |
| Animated numeric values                     | `@number-flow/react`                 |
| Dragging and sortable interactions          | `@dnd-kit/core`, `@dnd-kit/sortable` |
| Wheel selection                             | `@ncdai/react-wheel-picker`          |
| Interface icons                             | `lucide-react`                       |

Reuse the project's wrappers before adding a dependency. Apply QwenPaw tokens and behavior to package primitives rather than copying a showcase's entire appearance. Rare UI is a reference for interaction craft; adopting its code is a separate implementation decision that requires checking suitability and license terms.

## Accessibility and quality floor

Accessibility is part of the material and interaction design, not a separate visual mode.

- Provide semantic controls, a logical focus order, visible focus, and keyboard equivalents for gestures.
- Use a minimum contrast target of 4.5:1 for normal text and 3:1 for large text and essential control boundaries. Test the actual composited colors, especially orange, translucent surfaces, and secondary text.
- Honor reduced motion throughout the component hierarchy. Provide solid materials for reduced transparency and stronger boundaries for increased contrast.
- Preserve legibility with zoom, enlarged text, long content, and narrow viewports.
- Keep decorative motion out of assistive-technology announcements. Communicate meaningful state changes at a useful cadence.
- Review interrupted motion, rapid repeated input, pointer cancellation, and scroll performance as carefully as the ideal animation.

## Design review checklist

Use this checklist for each design or implementation review. It is a reusable quality gate, not a record that the current application has passed these checks.

- [ ] The built-in theme uses QwenPaw Orange `#FF7F16` and its `#FF9D4D` variant; custom themes take precedence through semantic tokens.
- [ ] Static controls, gradients, glows, and in-progress interactions follow the active custom theme in light and dark modes without reverting to hardcoded defaults.
- [ ] Colors come from semantic tokens, with tested foreground contrast and clear status meaning.
- [ ] Type, icons, baselines, spacing, and corners form a coherent hierarchy.
- [ ] Visible copy is concise; secondary explanations use contextual help accessible by hover, focus, and touch, while essential labels, states, and errors remain visible.
- [ ] Surfaces group related content without unnecessary nesting or empty space.
- [ ] Light and dark themes preserve readable material separation.
- [ ] Responsive layouts preserve reading order, touch access, and useful density.
- [ ] Motion explains an interaction, remains interruptible, and uses one clear focal effect.
- [ ] Thoughtful control combinations simplify one intention; related visual feedback shares one semantic state.
- [ ] Magnetic boundaries are discoverable, stable under jitter, and equivalent through keyboard input.
- [ ] Reduced motion, keyboard, touch, focus restoration, and screen-reader behavior are considered.
- [ ] Existing packages and shared primitives are reused before introducing new machinery.
- [ ] Actual visual and interaction checks support any claim of implementation completion.

## References and interpretation

- [Apple: Designing Fluid Interfaces](https://developer.apple.com/videos/play/wwdc2018/803/) — direct manipulation and continuity of interaction.
- [Rare UI](https://www.rareui.com/) and its [notification bell reference](https://www.rareui.com/components/notificationbell) — small, state-linked interactions and coordinated numeric feedback. Its official component description was reviewed; the live showcase was unavailable during this revision.
- The two user-supplied images — proportional corners, aligned bento composition, tonal separation, and soft light. Their numeric shortcuts are interpreted as visual suggestions, not official Apple rules.
- The eight user-supplied effect briefs — the source of the motion vocabulary above.
- The user-supplied thinking-budget reference and description — the source of the magnetic enable rail, integrated Off/On boundary, and coordinated rolling readout. The specified thresholds and timing are QwenPaw proposals, not measurements of the reference animation.
- [`console/src/styles/tokens.css`](console/src/styles/tokens.css) — current theme color definitions; [`console/package.json`](console/package.json) — available implementation dependencies.

This document defines the intended QwenPaw language. It does not assert that every existing screen already conforms to it.
