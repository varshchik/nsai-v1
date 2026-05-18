*Some algorithms suppress emergence; others draw it out. Our task is to detect and amplify it, not formalize it. Design through interaction of algorithms, periodically revisit what has been done, think in systems and processes.*

# 1. Core

The agent receives a signal, records what it understood, honestly notes what was left unsaid, does not guess.

Base cycle: Signal → Framing (compression) → Floor-by-floor traversal of global memory → Coherence assessment. Global memory changes only from external signal (perceive), never from inside the answer-generation cycle (reason).

**Floor-by-floor traversal.** A floor is a one-step expansion of the association front. At each floor, all participants of the pulled facts — predicates and arguments — are counted. The output of traversal is a coherence assessment of the queried statement against the graph, from the perspective of the starting nodes. Counting is a property of the traversal, not of the graph. When traversal ends, the count is gone. The next query rebuilds it from scratch.

**Framing = compression, not expansion.** The signal is not a seed for expansion but a filter. Each association from the graph receives a weight: how many signal lemmas simultaneously activate it. An association activated by one lemma out of four is noise. An association activated by all four is maximal identity. Threshold: at N=1 the filter is disabled (nothing to intersect); at N≥2, `max(2, ⌈N/2⌉)`. That is, at least two signal lemmas must simultaneously activate a fact, and on larger signals at least half is required. An empty intersection → open-world response: the graph has nothing jointly known.

**Coherence score** is the sum of two independent terms, each in its own units: `direct_score` — the count of facts with full signal coverage (`_cov = N`); `bridge_score` — the count of chains where a non-query lemma is a shared neighbor of ≥2 query lemmas from disjoint starting branches. Each unit is one piece of evidence observable in the graph (direct or indirect). The strength of an individual chain (`a_facts × b_facts`) remains a diagnostic property of the bridge; it does not enter the overall score, so that popular graph nodes do not dominate.

**Inference chains** emerge from traversal as an observable property: if two query lemmas have a common neighbor (a bridge lemma) in the graph, a chain exists between them. The syllogism "Socrates is a man, men are mortal → Socrates is mortal" derives through the bridge "man" without a separate inference mechanism.

**Coherence is always perspectival.** A glass half empty and half full — both coherent, no conflict. The system does not converge to a single truth.

**Comparison, not search.** Coherence score is not interpretable on its own. A single query yields a number meaningful only against another. The canonical use of the system is `compare(A, B)`: run two reason calls and compare the scores. Even a lone query "?Socrates is mortal" implicitly compares against the alternative "Socrates is immortal." NSAI is dual by nature: a comparator, not an oracle.

Two modes: **perceive** — accept signal, write facts. **reason** — generate an answer through graph traversal, no writing.

# 2. Architecture

**A fact is a single structure:** `(predicate, [participants])`. The type (`relation`, `entity`, `IS_A`) is a service tag for query filtering, not an architectural entity:

- `relation` → `(wash, [mom, frame])`
- `entity` → `(apple, [])`
- `IS_A` → `(be, [socrates, man])`

Each perceive call additionally writes one fact with an empty predicate and all sentence lemmas as participants: `('', [wash, mom, frame])`. Purpose: explicit recording of a joint observation. Without it, framing-as-compression has no way to know that four lemmas were observed *together* rather than separately.

The predicate is indexed in `knowledge_args` alongside arguments — it is a full-fledged graph node.

**Global memory holds only positive observations.** A fact either is or isn't there. `INSERT OR IGNORE` on duplicates. 100 identical confirmations = 1 edge. Open world: absence of a record about X means "X was not observed," not "X does not exist."

**Negative universal statements are not stored.** "Nothing on the table" is an infinite list of negatives. The graph holds observations.

**Conclusions are not stored.** Results of reason exist only in working memory and are reassembled on every query.

**Working memory.** One layer: a session cache of user-signal lemmas. Used as a starting-front bias in `floor_traversal`. The active-association stack from v4.x was removed along with the linear parser — it accumulated state nobody read.

**Identity is neither stored nor computed.** A lemma in context pulls associations; the traversal selects the consistent ones. There is no separate operation.

**Conflict is not a system operation.** Each fact independently receives coherence. Two statements about the same object with independently high coherence is a normal state, not an error. Tension is a **`reason()` output**, not a background scanner: traversal activates both sides of a tension if the signal touched them.

**Self = global memory; world = input signal.** The boundary requires no marker.

# 3. Rejected Solutions

- **Self-model through epistemic tags.** Self = memory, not tags.
- **[UNKNOWN_NP], omission as a DB type, group_id.** Incompleteness is a property of the analysis moment.
- **identity_link / distinct_link.** Identity manifests from the traversal.
- **Compression as a write operation.** A reading effect, not modification.
- **Density as a filter.** Coherence is a traversal criterion, not a separate module.
- **Edge weights, confirmation counters.** The graph has no weights.
- **Conflict as a separate mechanism.** Duplicates the traversal.
- **`НЕ_` prefix as a special mechanism.** Particles form compound lemmas via a general rule.
- **Negative universal statements in the graph.** The graph holds observations.
- **template.json as a source of roles.** Roles are derived from natasha's dependency tree. The file is kept as a deprecated reference.
- **`observation` as a separate fact type.** It is `(predicate='', [all lemmas])` — a special case of the general fact structure, not its own entity.
- **`find_chains` as a separate algorithm.** Bridge lemmas are an observable property of traversal. The current implementation is still explicit; the goal is to remove it once traversal is comprehensive enough.
- **Linear parser pass (`.split()` or token window).** Russian, with its free word order and complex constructions, requires structural rather than positional analysis.
- **Background scan_curiosity for tension.** Tension arises in reason(), not from scanning the graph without a signal. Alternatives in the graph carry no weight by themselves — only those activated by the current signal matter.
- **Coherence score as a sum of individual lemma counts.** A popular lemma carried score even when joint observation was absent (hallucination). Score now counts only facts with full signal coverage.
- **Chain strength (`a_facts × b_facts`) as part of the score.** The product grows with the popularity of the bridge node, dragging score with popular hubs in the graph. Moved to bridge diagnostics; only the count of chains, not their strength, enters `coherence_score`.
- **Args sort by surface position.** Produced different args lists for semantically identical sentences (`Кот ест рыбу` vs `Рыбу ест кот` → distinct records). Replaced by role-order; deduplication works without a separate mechanism.
- **Divergent transitivity check across paths.** `analyze` and `scan_curiosity` used different criteria — pymorphy3 grammemes vs natasha VerbForm. Replaced by a single helper `_is_transitive_verb`. One architectural fact — one implementation point.

# 4. Emergent Properties

Criterion: if the property disappears under attempted formalization, it is emergent.

| Property | What produces it |
|---|---|
| Syllogism | Bridge lemma in traversal |
| Generalization | Many particular cases + comparison with signal |
| Identity | Pulling associations in context |
| Insight | A shorter path appearing after a new edge |
| Coherence | Counting participants across traversal floors |
| Contradiction | Two independently high coherences about the same object |
| Tension | A neighbor in both neighborhoods with non-overlapping branches |
| Meta-thinking | Traversal with the agent's own graph as the object |

# 5. Curiosity

The goal of an autonomous agent is to resolve alternatives in its own graph. Not to maximize knowledge.

Curiosity does not scan the graph in the background. Curiosity is a **`reason()` output**. Alternatives in the global graph carry no weight by themselves; only those activated by the current signal matter. The traversal already activated both sides of a tension if the signal touched them.

Types of open spots (a single mechanism — insufficient or split coherence):
- **Hole** — a transitive verb without an object. Transitivity is determined via `pymorphy3.grammemes`. Framing suggests candidates.
- **Tension** — two facts with signal coverage, a shared object, non-overlapping other participants. Arises directly in reason().
- **Low coherence** — the traversal does not produce a confident assessment.

Autonomous iteration: tensions from a previous reason() → next signal. A loop over the agent's own outputs, not over the graph.

# 6. Parser

The sensory layer, not the core. Extracts facts from the dependency tree.

**Morphology + syntax:** natasha `NewsMorphTagger` (POS + feats, contextual) + `NewsSyntaxParser` (dependency tree). pymorphy3 — lemmatization, guided by natasha's POS.

**Fact extraction from the tree:**

| UD relation | What it generates |
|---|---|
| VERB node + nsubj/obj/iobj/obl/xcomp | relation: predicate → [args] |
| amod (ADJ ← NOUN) | relation: modifier → [head_noun] |
| ADJ as root + nsubj | relation: ADJ-predicate → [subject] |
| NOUN with case-ADP child | relation: preposition → [head, dep] |
| conj/appos/nmod/amod-NOUN siblings | join args as an enumeration |
| acl:relcl | antecedent through the head; if head is an ADJ-predicate, through its nsubj |
| advmod + PART | compound lemma: `не_спать`, `вряд_ли_знать` |
| Literals (numbers, Latin script) | entity, lemma equals the token itself |
| NOUN/PROPN not entering any relation | entity |

**Transitivity.** Determined from the object's `Case=Acc` in the tree. Stored in the graph as a fact; for hole detection, checked through `pymorphy3.grammemes` via a single helper `_is_transitive_verb` used at every point (perceive→analyze and scan_curiosity).

**Compound lemmas.** Particle + next predicate via `advmod+PART` → one lemma. Negation, modality, emphasis — without special rules. Different compound lemmas land in different topological neighborhoods through traversal.

**Args sorting.** By role priority (`nsubj → nsubj:pass → obj → iobj → obl → xcomp`); within a role — in natasha's return order, with conj/appos/nmod siblings appended right after their role-head. Surface position is not used. This produces a stable canonical key for deduplicating `relation` facts: `Кот ест рыбу` and `Рыбу ест кот` yield the same record.

**Fallback.** Natasha breaks the tree on short sentences without punctuation (e.g., `мама мыла раму` "mom washed the frame": `мама` becomes root, `мыла` becomes nmod). Sign: NOUN root + non-root VERB. In this case, the first VERB is taken as predicate, and all NOUN/PROPN/PRON/ADJ as arguments.

**Status.** Punctuation marks and operators as separate graph nodes — not implemented. This opens the architecture to non-linguistic inputs and is a priority for the next iteration.

**Known limitations.** Heavily nested relative clauses and subordinations are parsed by natasha with errors (e.g., head pointing to the node itself). Documented as a system boundary, not an implementation bug.
