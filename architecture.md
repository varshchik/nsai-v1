# Architecture

This document is a condensed English overview of the NSAI architecture. The full version is [principles_en.md](./principles_en.md).

NSAI is a symbolic system for parsing, storing, and reasoning over facts extracted from natural-language text. The design principle behind every decision below is the same: **do not formalize what already emerges from the base cycle.** Whenever a proposed mechanism duplicates what graph traversal already produces, the mechanism is rejected.

## Base cycle

Signal → Framing (compression) → Floor-by-floor traversal → Coherence assessment.

The agent receives a signal, frames it against the global graph, traverses floor by floor, and produces a coherence assessment of the queried statement from the perspective of the starting nodes. Each floor expands the association front by one hop. At each floor, all participants of pulled facts — predicates and arguments alike — are counted.

Counting is a property of the traversal, not the graph. When the traversal ends, the counts vanish. The next query rebuilds them from scratch.

Two modes:
- **`perceive`** — accept signal, write facts to the graph. Memory changes.
- **`reason`** — generate an answer through traversal, no writes. Memory is read-only.

The graph mutates only from external signal via `perceive`. Internal reasoning never modifies storage.

## Framing as compression, not expansion

The signal does not seed expansion — it filters it. Each association pulled from the graph receives a weight equal to the number of signal lemmas that simultaneously activate it. An association touched by one signal lemma out of four is noise; an association touched by all four is a maximal joint match.

Threshold: at N=1 the filter is disabled (nothing to intersect); at N≥2, `max(2, ⌈N/2⌉)`. That is, at least two signal lemmas must simultaneously activate a fact. This is what eliminates "hallucination through popular lemmas": a single lemma frequent in the graph no longer drags arbitrary facts containing it into the result.

If the intersection is empty, the system falls back to open-world: the graph holds nothing jointly relevant, and the query is honestly reported as new territory.

## Coherence score: direct observations and bridges

Coherence is the sum of two independent counters, each in its own units:

- **`direct_score`** — the count of facts with full signal coverage (`_cov = N`). Each is one direct observation in the graph.
- **`bridge_score`** — the count of chains where a non-query lemma is a shared neighbor of ≥2 query lemmas from disjoint starting branches. Each is one indirect piece of evidence.

The strength of an individual chain (`a_facts × b_facts`) is a diagnostic property of the bridge; it does not enter the overall score. Otherwise popular graph nodes (like "person", "thing") would dominate through wide neighborhoods rather than relevance to the query.

## Floor-by-floor traversal, by example

Question: "Is Socrates mortal?" Graph contains: Socrates is a man; men are mortal.

- **Floor 1.** From `socrates`: `is-a-man`. From `mortal`: `applies-to-man`.
- **Floor 2.** Both signal lemmas reach `man` from disjoint branches.
- **Result.** `man` is a *bridge* — touched by two query lemmas through non-overlapping starting paths. The chain `socrates → man → mortal` is a side product of the traversal, not a separate inference step.

Syllogistic reasoning emerges from the traversal mechanism. There is no inference engine — only reachability counting.

Traversal depth is a tunable parameter. Depth 1 captures direct links only; depth 3 captures chained reasoning; deeper increases noise.

## Coherence is always perspective-relative

A single object can have several high-coherence statements simultaneously. "The glass is half full" and "the glass is half empty" both score high — they activate different association neighborhoods, and both are consistent with the graph. This is not a contradiction; it is two valid perspectives.

The system does not converge to a single truth. It honestly returns coherence from the angle the question approaches.

## Comparison, not search

Coherence score is not interpretable on its own. A single query yields a number meaningful only against another. The canonical use of the system is `compare(A, B)`: run two reason calls and compare the scores. Even a lone query "?Socrates is mortal" implicitly compares against the alternative "Socrates is immortal." NSAI is dual by nature: a comparator, not an oracle.

## Identity is not computed

There is no "identity resolution" operation. Contextual associations are pulled to the lemma in question, and the traversal naturally selects associations consistent with the surrounding signal. "The swan flew" and "the swan in the lake" are two lemma activations with different contextual neighborhoods; the graph reads them as distinct without any explicit identity tag.

## Conflict is not a system operation

Each fact carries its own coherence independently of other facts about the same object. If two statements about the same object both score high in `reason()`, this is a *tension* — surfaced as part of the reasoning output, not detected by a background scanner. Tension exists only as a property of the moment: the signal must touch both branches for the tension to be observable. Alternatives in the graph that no current signal activates do not matter and are not pursued.

## What is stored

A single structure: `(predicate, [participants])`. The type field is a query filter, not an architectural distinction:

- `relation` → `(wash, [mom, frame])`
- `entity` → `(apple, [])`
- `observation` → `('', [wash, mom, frame])` — all lemmas of one sentence, written for every `perceive` call

The observation record is what enables joint-activation scoring. Without it, framing has no way to know that several lemmas were observed *together* rather than just present in the graph at different times.

Args in `relation` follow role order (`nsubj → nsubj:pass → obj → iobj → obl → xcomp`), not surface position. This produces a stable canonical key: Russian `Кот ест рыбу` and `Рыбу ест кот` (both meaning "the cat eats the fish", differing only in word order) yield the same record.

The predicate is indexed alongside arguments. There is no privileged path for predicates — they are full graph nodes.

No metadata, no statuses, no weights, no confidence scores. `INSERT OR IGNORE` on duplicates: 100 identical confirmations equal one edge. Open-world assumption: absence of a record means "not observed," not "false."

**Negative universal statements are not stored.** "Nothing is on the table" is not a fact — it is an infinite list of negations. The graph holds observations.

**Conclusions are not stored.** Reasoning results live in working memory for one query and are recomputed each time the same question is asked.

## Particles do not get special handling

A particle followed by a predicate forms a *compound lemma*. `не работает` becomes a single node `не_работать`. `вряд ли работает` becomes `вряд_ли_работать`. There is no negation prefix, no special path for `не`. The graph treats `работать` and `не_работать` as two distinct nodes that may share contextual neighborhoods in some places and diverge in others. Opposition is emergent, not encoded.

## Working memory

One layer: a session cache holding lemmas of recent user signals. The cache biases the starting front of `floor_traversal` — the same query asked in a richer conversational context activates a wider seed.

There is no stack of active associations. An earlier design kept a 7-slot stack, but the slots accumulated state that no consumer read; it was removed along with the linear parser.

## Self and world

`Self = global memory; world = input signal.` The boundary requires no explicit marker. Meta-reasoning emerges when the same traversal mechanism operates on facts from the agent's own graph, with the graph itself as the object of inspection.

## Curiosity

The autonomous agent's goal is **resolving alternatives in its own graph** — not maximizing knowledge, not exploring outward. The agent acts when there is concrete ambiguity to resolve, and rests when the graph is stable.

Curiosity is the output of `reason()`, not a background scan. Three signal types, all surface manifestations of one underlying mechanism (insufficient or split coherence in the traversal):
- **Hole** — a transitive verb without an object. Transitivity is read from `pymorphy3.grammemes` via a single helper `_is_transitive_verb`. Framing suggests candidates.
- **Tension** — two facts with full signal coverage, sharing one participant but disjoint in their other participants.
- **Low coherence** — the traversal cannot accumulate enough support in any direction.

Open questions are ranked by `cascade_score` — the magnitude of follow-up work that resolution would unblock.

Autonomous iteration: tensions from one `reason()` become the next signal. The cycle runs over its own outputs, not over the graph.

## Rejected solutions

Each item below was considered and discarded because it duplicates what the base cycle already produces:

- **Epistemic source labels** (1st/2nd/3rd person provenance). Self = memory; world = signal. The boundary follows from where data came in, not from a tag.
- **`[UNKNOWN_NP]`, omission types in DB, `group_id`.** Incompleteness is a property of the moment of analysis, not of the fact.
- **`identity_link` / `distinct_link` tables.** Identity emerges from association overlap; storing it is redundant.
- **Compression as a write operation.** Path shortening is an effect of reading, not modification.
- **Density as a trust filter.** Coherence is a traversal criterion, not a separate filtering layer.
- **Edge weights, confirmation counters.** The graph has no weights. Counts arise inside a traversal and vanish when it ends.
- **Conflict detection as a separate mechanism.** Conflicts are external observations on independently scored facts.
- **`НЕ_` prefix as a special marker for negation.** Replaced by general particle-lemma compounding.
- **Negative universal facts in the graph.** "X does not exist" is not stored; absence is unobserved, not asserted.
- **`template.json` as a source of role assignments.** Roles come from natasha's UD relations. The file is no longer loaded.
- **Linear positional parsing** (`.split()` or token windows). Russian's free word order requires structural analysis through dependency trees.
- **`observation` as a separate architectural fact type.** It is `(predicate='', [all_lemmas])` — a special case of the general fact structure, not its own kind.
- **`find_chains` as a dedicated algorithm.** Bridge lemmas are an observable property of the traversal. The current implementation is still explicit; the goal is to remove it once traversal is comprehensive enough.
- **Background `scan_curiosity` for tensions.** Tensions arise inside `reason()`, not from scanning the graph without a signal.
- **Coherence score as a sum of individual lemma counts.** A popular lemma carried score even without joint observation. Score now counts only facts with full signal coverage.
- **Chain strength (`a_facts × b_facts`) as part of the score.** The product grows with the popularity of the bridge node, dragging score with popular hubs in the graph. Moved to bridge diagnostics; only the count of chains, not their strength, enters `coherence_score`.
- **Args sort by surface position.** Produced different args lists for semantically identical sentences. Replaced by role-order; deduplication works without a separate mechanism.
- **Divergent transitivity check across paths.** `analyze` and `scan_curiosity` used different criteria. Replaced by a single helper `_is_transitive_verb`. One architectural fact — one implementation point.

## Parser

The parser is the sensory layer, not the core. It maps Russian text to graph nodes from natasha's dependency tree, with pymorphy3 for lemmatization (POS-directed by natasha's UD tag).

Fact extraction by UD relation:

| UD relation | Generates |
|---|---|
| VERB + nsubj/obj/iobj/obl/xcomp | relation: predicate → [args] |
| amod (ADJ ← NOUN) | relation: modifier → [head] |
| ADJ as root + nsubj | relation: ADJ-predicate → [subject] |
| NOUN with case-ADP child (head also NOUN) | relation: preposition → [head, dep] |
| conj/appos/nmod siblings | join into args list |
| acl:relcl | antecedent through head; if head is an ADJ-predicate, dereference to its nsubj |
| advmod + PART | compound lemma: `не_спать`, `вряд_ли_знать` |
| Literals (numbers, latin) | entity, lemma = surface form |
| Remaining unattached NOUN/PROPN | entity |

Args follow role order (`nsubj → nsubj:pass → obj → iobj → obl → xcomp`); within a role, in natasha's return order with conj/appos/nmod siblings appended right after their role-head. Surface position is not used.

**Transitivity.** Object `Case=Acc` indicates transitivity for the surrounding verb. For hole detection (everywhere required) the system queries `pymorphy3.grammemes` through a single helper `_is_transitive_verb`. A dictionary lookup is reliable for an isolated lemma.

**Compound lemmas.** Particle + head verb merge through `advmod+PART`. Negation, modality, emphasis — all handled by the same general rule, no special cases. Different compound lemmas land in different topological neighborhoods through traversal.

**Fallback.** natasha occasionally mistags very short isolated sentences (e.g. `мама мыла раму` "mom washed the frame" → `мама` as root, `мыла` as nmod). Detection: NOUN root combined with an orphan VERB. In this case the parser switches to a linear pass: first VERB as predicate, all NOUN/PROPN/PRON/ADJ as arguments.

## Status

Draft v0.1. The architecture above is settled to the level where further changes are weighed carefully against the rejected-solutions principle. Known gaps tracked for v0.2:

- Punctuation marks, operators, and numbers as first-class graph nodes — opens architecture to non-linguistic input.
- Removal of explicit `find_chains` once traversal counting is comprehensive enough that bridge lemmas surface without a dedicated pass. Alternative path: per-query traversal with intersection of reachability sets.
- Heavily nested relative clauses are parsed by natasha with errors (head occasionally points to the node itself). Documented as a system boundary, not a bug.
