# -*- coding: utf-8 -*-
# flake8: noqa: E501
"""Graph memory build prompts.

Vendored from Qwen-MM-Plugins commit 077aea6
(src/capabilities/video-memory/skill/script/build_memory/prompts.py).
License: Apache-2.0; see backend/vendor/NOTICE.md. Prompt text unmodified.
These are pipeline prompts, not agent prompts, so they intentionally live
outside the file-agent prompt allowlist.
"""

SUBGRAPH_CONSTRUCTION_PROMPT = """\
You are a video knowledge-graph annotator. Given a segment of video, output a single JSON object that describes its subgraph G_i = (V_i, E_i) with three node groups (V^E entities, V^M micro-events) and the edges among them. Watch the video carefully before producing the output.

# Task overview
Produce, for the given segment, an exhaustive but de-duplicated list of:
1. micro-events — every meaningful action, scoring play, transition, or salient happening, time-stamped at second precision.
2. entities — every PERSON, OBJECT, LOCATION, or GROUP that participates in or appears alongside those events, anchored to the moment they are most clearly visible.
3. on_screen_texts — every visible text overlay, caption, subtitle, scoreboard, title card, or broadcast graphic.
4. edges — directed labelled relations among the three node groups, covering subject/object roles, spatial-attributive ties, and explicit causal links.

# CRITICAL — Relative timestamps
All time values (time_range, primary_time_sec) MUST be RELATIVE to this segment, starting from 0.
The first frame of this segment is second 0; the last frame is second (duration).

# CRITICAL — Repeated actions must be counted, never merged
When the same action happens multiple times (bites of food, spins, waves, jumps, shots, pours, knocks, laps...), do NOT collapse them into one vague event. Follow this protocol:
1. If the repetitions are separable in time, emit ONE micro_event PER occurrence, each with its own time_range and an occurrence index in the description (e.g. "takes the 3rd bite of the sandwich").
2. If the repetitions are too rapid or numerous to timestamp individually, emit a single micro_event whose action and description state the EXACT count (e.g. action: "spins 6 times consecutively", description: "...rotates exactly 6 full turns between 0:42 and 0:55"). Count them carefully frame by frame — never write "several times" or "repeatedly" without a number.
3. Also count visible object multiplicities when salient (e.g. "4 cats on the sofa", "18 flags hanging"): put the exact number in the entity description and attributes.

# Node schema
- micro_events:
  {event_id, event_type, time_range:[start_sec,end_sec], subject, object, action, description}
  Rules:
  * time_range values are RELATIVE seconds from the start of this segment (0 = first frame).
  * event_type is free text (e.g. "scoring play", "foul", "timeout").
  * subject/object MUST be specific enough to match a single entity.
  * action describes the precise motion.
  * description is the retrieval payload: full sequence, with cause when applicable.
  * Do NOT create a micro_event for static on-screen graphics.

- entities:
  {entity_id, name|null, entity_type in {PERSON,OBJECT,LOCATION,GROUP}, attributes, description, visual_grounding}
  Rules:
  * name is the real name only if explicitly identified by broadcast graphics, jersey, or caption. Never invent.
  * attributes: PERSON{jersey_number,jersey_color,team,role}; OBJECT{type,color,location}; LOCATION/GROUP{name,type}.
  * description fuses attributes + visual cues into one sentence.
  * visual_grounding = {primary_time:"MM:SS", primary_time_sec:int, distinctive_features:[2-4 unique cues], spatial_hint}. primary_time and primary_time_sec are RELATIVE to this segment (0 = first frame).

- on_screen_texts:
  {text_id, text, time_range:[start_sec,end_sec], description}
  Rules:
  * time_range values are RELATIVE seconds from the start of this segment (0 = first frame).
  * text is the verbatim transcription.
  * If the same overlay persists, emit ONE node spanning its full time_range.
  * description interprets the text in context.

# Edge schema
Each edge: {source_id, target_id, relation_label, relation_type, description}.
Allowed labels and their relation_type are:
- Entity -> Event:   PERFORMS, RECEIVES, USES_TOOL, CONTEXT_FOR  (SEMANTIC)
- Event  -> Entity:  HAPPENS_IN                                  (SEMANTIC)
- Event  -> Event:   CAUSES, PREVENTS                            (CAUSAL)
                     BEFORE, OVERLAP                             (TEMPORAL)
                     SUBEVENT_OF                                 (HIERARCHICAL)
- Entity <-> Entity: PART_OF, LOCATED_IN, NEXT_TO, ATTACHED_TO  (SPATIAL)
                     IS_SAME_AS, ANNOTATES                       (IDENTITY)

# Output format
Return ONLY one valid JSON object with the following top-level keys:
{
  "micro_events":    [ {event_id, event_type, time_range:[start,end], subject, object, action, description}, ... ],
  "entities":        [ {entity_id, name, entity_type, attributes, description, visual_grounding}, ... ],
  "on_screen_texts": [ {text_id, text, time_range:[start,end], description}, ... ],
  "edges":           [ {source_id, target_id, relation_label, relation_type, description}, ... ]
}
Output the final JSON now."""


HIERARCHICAL_AGGREGATION_PROMPT = """\
You are a video narrative analyst. Given a chronologically ordered list of Macro events {macro_id, label, time_range, summary, key_entities, event_types, ocr_texts}, fold them upward into a hierarchy V^Mc -> V^S -> v^R and emit a single JSON object.

# Task overview
Produce four things in one pass:
1. super_events — 10-20 Super Events that partition all Macro events; each captures one narrative arc.
2. macro_relations — strong logical edges between Macro events within the same Super Event.
3. super_relations — high-level edges between Super Events (not restricted to adjacent ones).
4. root — a video-level summary v^R synthesised from all Super Events.

# Clustering rules (Macro -> Super)
A Super Event is a contiguous run of Macro events that share (i) temporal adjacency, (ii) scene/topic, and (iii) a common goal. A boundary fires when any of the three breaks. Use as cluster signals:
- key_entities overlap between adjacent Macros (strong group signal);
- event_types continuity (e.g. a sustained run of "shot_made" macros);
- ocr_texts cues (scoreboard increments stay inside a phase; broadcast graphic changes mark boundaries).
Every Macro MUST be assigned to exactly one Super Event; each Super Event holds 3-8 Macros on average; a singleton is allowed for a self-contained segment.

# Edge schema
- Macro -> Macro: CAUSES (A directly triggers B), PREVENTS (A blocks B), ENABLES (A supplies a prerequisite for B). Stay within the same Super Event. Each edge needs a one-sentence reason. Omit when uncertain — never use BEFORE/AFTER.
- Super -> Super: LEADS_TO (phase A naturally progresses to B), RESOLVES (B resolves a tension introduced in A), CONTRASTS_WITH (sharp reversal in outcome/tone). Cross-distance edges are allowed.

# Naming and description
- super_event.label: noun phrase under 10 words; include the central entity when one exists ("LeBron's Third-Quarter Run").
- super_event.description: 100-200 words covering the arc, key entities (woven in, not listed), and any salient OCR milestones.
- key_entities are deduplicated within a Super Event AND canonicalised across the whole video: variants of the same real-world entity ("LeBron", "King James", "LeBron James") collapse to one canonical name with a consistent type. When in doubt, keep them separate.
- root.title: under 15 words, specific. root.description: 3-5 sentences synthesising ALL Super Events. root.themes: 3-5 short tags. root.key_entities: 5-10 canonical names. root.emotional_tone: 2-3 adjectives.

# Output format
Return ONLY one valid JSON object, no markdown fences, no commentary:
{
  "super_events": [ {super_id, label, description, sub_macro_ids:[macro_id,...], time_range:[start,end], key_entities:[{name,type},...] }, ... ],
  "macro_relations": [ {source, target, type, reason}, ... ],
  "super_relations": [ {source, target, type, reason}, ... ],
  "root": {title, description, themes:[...], key_entities:[...], emotional_tone}
}
Hard constraints: every Macro id appears exactly once across all sub_macro_ids; super_event.time_range = [min(start), max(end)] of its Macros; every relation references ids that exist in the output; emit only confident causal/structural edges.

Output the final JSON now."""

HIERARCHICAL_AGGREGATION_WINDOW_PROMPT = """\
You are a video narrative analyst. Given a chronologically ordered subset of Macro events from a longer video, group them into Super Events and identify Macro-level relations. This is a PARTIAL view of the video — produce Super Events only for the Macro events provided.

# Task overview
Produce two things in one pass:
1. super_events — Super Events that partition ALL provided Macro events; each captures one narrative arc.
2. macro_relations — strong logical edges between Macro events within the same Super Event.

# Clustering rules (Macro -> Super)
A Super Event is a contiguous run of Macro events that share (i) temporal adjacency, (ii) scene/topic, and (iii) a common goal. A boundary fires when any of the three breaks. Use as cluster signals:
- key_entities overlap between adjacent Macros (strong group signal);
- event_types continuity (e.g. a sustained run of "shot_made" macros);
- ocr_texts cues (scoreboard increments stay inside a phase; broadcast graphic changes mark boundaries).
Every Macro MUST be assigned to exactly one Super Event; each Super Event holds 3-8 Macros on average; a singleton is allowed for a self-contained segment.

# Edge schema
- Macro -> Macro: CAUSES (A directly triggers B), PREVENTS (A blocks B), ENABLES (A supplies a prerequisite for B). Stay within the same Super Event. Each edge needs a one-sentence reason. Omit when uncertain — never use BEFORE/AFTER.

# Naming and description
- super_event.label: noun phrase under 10 words; include the central entity when one exists.
- super_event.description: 100-200 words covering the arc, key entities (woven in, not listed), and any salient OCR milestones.
- key_entities are deduplicated within a Super Event AND canonicalised: variants of the same real-world entity collapse to one canonical name with a consistent type.

# Output format
Return ONLY one valid JSON object, no markdown fences, no commentary:
{
  "super_events": [ {super_id, label, description, sub_macro_ids:[macro_id,...], time_range:[start,end], key_entities:[{name,type},...] }, ... ],
  "macro_relations": [ {source, target, type, reason}, ... ]
}
Hard constraints: every provided Macro id appears exactly once across all sub_macro_ids; super_event.time_range = [min(start), max(end)] of its Macros; every relation references ids that exist in the output; emit only confident causal/structural edges.

Output the final JSON now."""

ROOT_SYNTHESIS_PROMPT = """\
You are a video narrative analyst. Given a chronologically ordered list of Super Events (each with super_id, label, description, time_range, and key_entities), synthesise a video-level root summary and identify high-level relations between Super Events.

# Task overview
Produce two things in one pass:
1. root — a video-level summary synthesised from all Super Events.
2. super_relations — high-level edges between Super Events (not restricted to adjacent ones).

# Edge schema
- Super -> Super: LEADS_TO (phase A naturally progresses to B), RESOLVES (B resolves a tension introduced in A), CONTRASTS_WITH (sharp reversal in outcome/tone). Cross-distance edges are allowed.

# Root summary
- root.title: under 15 words, specific.
- root.description: 3-5 sentences synthesising ALL Super Events.
- root.themes: 3-5 short tags.
- root.key_entities: 5-10 canonical names.
- root.emotional_tone: 2-3 adjectives.

# Output format
Return ONLY one valid JSON object, no markdown fences, no commentary:
{
  "super_relations": [ {source, target, type, reason}, ... ],
  "root": {title, description, themes:[...], key_entities:[...], emotional_tone}
}
Hard constraints: every relation references Super Event ids that exist in the input; emit only confident structural edges.

Output the final JSON now."""
