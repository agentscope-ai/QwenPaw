---
name: deep-interview
description: Socratic deep interview with mathematical ambiguity gating before execution
argument-hint: "[--quick|--standard|--deep] <idea or vague description>"
level: 3
---

<Purpose>
Deep Interview implements Ouroboros-inspired Socratic questioning with mathematical ambiguity scoring. It replaces vague ideas with crystal-clear specifications by asking targeted questions that expose hidden assumptions, measuring clarity across weighted dimensions, and refusing to proceed until ambiguity drops below the resolved threshold. The output feeds into a gated pipeline ensuring maximum clarity before any mutation starts.
</Purpose>

<Use_When>
- User has a vague idea and wants thorough requirements gathering before execution
- User says "deep interview", "interview me", "ask me everything", "don't assume", "make sure you understand"
- User says "ouroboros", "socratic", "I have a vague idea", "not sure exactly what I want"
- User wants to avoid "that's not what I meant" outcomes from autonomous execution
- Task is complex enough that jumping to code would waste cycles on scope discovery
- User wants mathematically-validated clarity before committing to execution
</Use_When>

<Do_Not_Use_When>
- User has a detailed, specific request with file paths, function names, or acceptance criteria — execute directly
- User wants to explore options or brainstorm — use planning instead
- User wants a quick fix or single change — delegate directly or use ralph
- User says "just do it" or "skip the questions" — respect their intent
- User already has a PRD or plan file and explicitly asks to execute it
</Do_Not_Use_When>

<Why_This_Exists>
AI can build anything. The hard part is knowing what to build. Single-pass expansion struggles with genuinely vague inputs. Deep Interview applies Socratic methodology to iteratively expose assumptions and mathematically gate readiness, ensuring genuine clarity before spending execution cycles.

Inspired by the Ouroboros project which demonstrated that specification quality is the primary bottleneck in AI-assisted development.
</Why_This_Exists>

<Execution_Policy>
- Ask ONE question at a time — never batch multiple questions
- Target the WEAKEST clarity dimension with each question
- Before Round 1 ambiguity scoring, run a one-time Round 0 topology enumeration gate that confirms the top-level component list
- Make weakest-dimension targeting explicit every round: name the weakest dimension, state its score/gap, and explain why the next question is aimed there
- Gather codebase facts via exploration BEFORE asking the user about them
- For brownfield confirmation questions, cite the repo evidence that triggered the question
- Score ambiguity after every answer — display the score transparently
- When the locked topology has multiple active components, score and target each component explicitly
- Do not proceed to execution until ambiguity ≤ the resolved threshold and the user explicitly approves
- Allow early exit with a clear warning if ambiguity is still high
- Challenge agents activate at specific round thresholds to shift perspective
</Execution_Policy>

<Steps>

## Phase 0: Resolve Ambiguity Threshold

Default ambiguity threshold: `0.2` (20%). Configurable per session.

## Phase 1: Initialize

1. **Parse the user's idea** from arguments
2. **Detect brownfield vs greenfield**:
   - Check if cwd has existing source code, package files, or git history
   - If source files exist AND the user's idea references modifying/extending something: **brownfield**
   - Otherwise: **greenfield**
3. **For brownfield**: Explore the codebase to build context before designing questions
4. **Initialize state** in `.qwenpaw/loop_state/{sessionId}/interview-state.json`
5. **Announce the interview** to the user with current ambiguity score

## Round 0: Topology Enumeration Gate

Run exactly once after Phase 1 initialization and before Phase 2 ambiguity scoring.

1. **Enumerate candidate top-level components** from the initial idea and brownfield context
2. **Ask one confirmation question** before Round 1:
   - Present identified components
   - Ask if the topology is correct
3. **Lock topology into state** after the answer

## Phase 2: Interview Loop

Repeat until `ambiguity ≤ threshold` OR user exits early:

### Step 2a: Generate Next Question

Build the question targeting the weakest clarity dimension:

**Question styles by dimension:**
| Dimension | Question Style | Example |
|-----------|---------------|---------|
| Goal Clarity | "What exactly happens when...?" | "When you say 'manage tasks', what specific action does a user take first?" |
| Constraint Clarity | "What are the boundaries?" | "Should this work offline, or is internet connectivity assumed?" |
| Success Criteria | "How do we know it works?" | "If I showed you the finished product, what would make you say 'yes, that's it'?" |
| Context Clarity (brownfield) | "How does this fit?" | "I found JWT auth in `src/auth/`. Should this feature extend that path or diverge?" |
| Scope-fuzzy / ontology | "What IS the core thing?" | "You've named Tasks, Projects, and Workspaces. Which one is the core entity?" |

### Step 2b: Ask the Question

Present clearly with current ambiguity context:
```
Round {n} | Component: {target} | Targeting: {weakest_dimension} | Ambiguity: {score}%

{question}
```

### Step 2c: Score Ambiguity

After receiving the user's answer, score clarity across all dimensions.

**Calculate ambiguity:**

Greenfield: `ambiguity = 1 - (goal × 0.40 + constraints × 0.30 + criteria × 0.30)`
Brownfield: `ambiguity = 1 - (goal × 0.35 + constraints × 0.25 + criteria × 0.25 + context × 0.15)`

### Step 2d: Report Progress

```
Round {n} complete.

| Dimension | Score | Weight | Weighted | Gap |
|-----------|-------|--------|----------|-----|
| Goal | {s} | {w} | {s*w} | {gap or "Clear"} |
| Constraints | {s} | {w} | {s*w} | {gap or "Clear"} |
| Success Criteria | {s} | {w} | {s*w} | {gap or "Clear"} |
| Context (brownfield) | {s} | {w} | {s*w} | {gap or "Clear"} |
| **Ambiguity** | | | **{score}%** | |
```

### Step 2e: Update State

Update interview state with the new round and scores.

### Step 2f: Check Soft Limits

- **Round 3+**: Allow early exit if user says "enough", "let's go", "build it"
- **Round 10**: Show soft warning
- **Round 20**: Hard cap — proceed with current clarity level

## Phase 3: Challenge Agents

At specific round thresholds, shift the questioning perspective:

### Round 4+: Contrarian Mode
Challenge core assumptions: "What if the opposite were true?" or "What if this constraint doesn't actually exist?"

### Round 6+: Simplifier Mode
Probe whether complexity can be removed: "What's the simplest version that would still be valuable?"

### Round 8+: Ontologist Mode (if ambiguity still > 0.3)
Find the essence: "What IS this, really?" — examine the ontology for the core concept.

Challenge modes are used ONCE each, then return to normal Socratic questioning.

## Phase 4: Crystallize Spec

When ambiguity ≤ threshold (or hard cap / early exit):

1. **Generate the specification**
2. **Write to file**: `.qwenpaw/loop_state/{sessionId}/deep-interview-spec.md`

Spec structure:

```markdown
# Deep Interview Spec: {title}

## Metadata
- Interview ID: {uuid}
- Rounds: {count}
- Final Ambiguity Score: {score}%
- Type: greenfield | brownfield
- Generated: {timestamp}
- Threshold: {threshold}

## Clarity Breakdown
| Dimension | Score | Weight | Weighted |
|-----------|-------|--------|----------|

## Topology
{List confirmed top-level components with coverage notes}

## Goal
{crystal-clear goal statement}

## Constraints
- {constraint 1}
- ...

## Non-Goals
- {explicitly excluded scope}

## Acceptance Criteria
- [ ] {testable criterion 1}
- ...

## Assumptions Exposed & Resolved
| Assumption | Challenge | Resolution |
|------------|-----------|------------|

## Interview Transcript
<details>
<summary>Full Q&A ({n} rounds)</summary>

### Round 1
**Q:** {question}
**A:** {answer}
**Ambiguity:** {score}%
</details>
```

## Phase 5: Execution Bridge

After the spec is written, present execution options:

1. **Execute with autopilot** — Full autonomous pipeline
2. **Execute with ralph** — Persistence loop with verification
3. **Refine further** — Continue interviewing
</Steps>

<Examples>
<Good>
Targeting weakest dimension:
```
Scores: Goal=0.9, Constraints=0.4, Criteria=0.7
Next question targets Constraints (lowest at 0.4):
"You mentioned this should 'work on mobile'. Does that mean a native app,
a responsive web app, or a PWA?"
```
Why good: Identifies weakest dimension and asks a specific question to improve it.
</Good>

<Good>
Gathering codebase facts before asking:
```
[explores codebase: "find authentication implementation"]
[finds: "Auth is in src/auth/ using JWT with passport.js"]

Question: "I found JWT authentication with passport.js in `src/auth/`.
For this new feature, should we extend the existing auth middleware or create
a separate authentication flow?"
```
Why good: Explored first, cited repo evidence, then asked an informed question.
</Good>

<Good>
Contrarian mode activation:
```
Round 5 | Contrarian Mode | Ambiguity: 42%

You've said this needs to support 10,000 concurrent users. What if it only
needed to handle 100? Would the architecture change fundamentally?
```
Why good: Challenges a specific assumption that could dramatically simplify the solution.
</Good>

<Bad>
Batching multiple questions:
```
"What's the target audience? And what tech stack? And how should auth work?
Also, what's the deployment target?"
```
Why bad: Four questions at once — causes shallow answers and makes scoring inaccurate.
</Bad>

<Bad>
Asking about codebase facts:
```
"What database does your project use?"
```
Why bad: Should have explored the codebase to find this. Never ask the user what the code already tells you.
</Bad>

<Bad>
Proceeding despite high ambiguity:
```
"Ambiguity is at 45% but we've done 5 rounds, so let's start building."
```
Why bad: 45% ambiguity means nearly half the requirements are unclear.
</Bad>
</Examples>

<Escalation_And_Stop_Conditions>
- **Hard cap at 20 rounds**: Proceed with whatever clarity exists, noting the risk
- **Soft warning at 10 rounds**: Offer to continue or proceed
- **Early exit (round 3+)**: Allow with warning if ambiguity > threshold
- **User says "stop", "cancel", "abort"**: Stop immediately, save state for resume
- **Ambiguity stalls** (same score ±0.05 for 3 rounds): Activate Ontologist mode to reframe
- **All dimensions at 0.9+**: Skip to spec generation even if not at round minimum
- **Codebase exploration fails**: Proceed as greenfield, note the limitation
</Escalation_And_Stop_Conditions>

<Final_Checklist>
- [ ] Interview completed (ambiguity ≤ threshold OR user chose early exit)
- [ ] Ambiguity score displayed after every round
- [ ] Every round explicitly names the weakest dimension and why it is the next target
- [ ] Challenge agents activated at correct thresholds (round 4, 6, 8)
- [ ] Spec file written with goal, constraints, acceptance criteria, clarity breakdown, transcript
- [ ] Spec includes topology section with confirmed components
- [ ] Execution bridge presented to user
- [ ] Brownfield confirmation questions cite repo evidence before asking
</Final_Checklist>

## Configuration

Default ambiguity threshold: `0.2` (20%).

## Brownfield vs Greenfield Weights

| Dimension | Greenfield | Brownfield |
|-----------|-----------|------------|
| Goal Clarity | 40% | 35% |
| Constraint Clarity | 30% | 25% |
| Success Criteria | 30% | 25% |
| Context Clarity | N/A | 15% |

## Challenge Agent Modes

| Mode | Activates | Purpose |
|------|-----------|---------|
| Contrarian | Round 4+ | Challenge assumptions |
| Simplifier | Round 6+ | Remove complexity |
| Ontologist | Round 8+ (if ambiguity > 0.3) | Find essence |

## State File

Path: `.qwenpaw/loop_state/{sessionId}/interview-state.json`

The loop exits when the interview is synthesized (ambiguity ≤ threshold and spec is written).

Task: {{ARGUMENTS}}
