# NSAI

**Symbolic knowledge graph system for Russian text.** Independent research, draft v0.1.

NSAI parses Russian sentences into a typed knowledge graph stored in SQLite, then answers questions through floor-by-floor graph traversal — not statistical generation. The goal is a system whose answers are *paths through known facts*, with explainability built in by construction rather than added on top.

## What this is

- A symbolic alternative to LLM-based approaches for knowledge representation and retrieval over Russian text.
- A single-author research project, written from first principles without prior reading of relevant literature; overlaps with existing work (Wittgenstein, Saussure, semantic networks, frame semantics) are likely and welcome to point out.
- Draft code intended to demonstrate the core architecture, not a production system.

## What this is not

- A generative model. NSAI does not predict tokens.
- A general-purpose NLP pipeline.
- A replacement for LLMs. It addresses a different problem: structured retrieval with inspectable derivation paths.

## Architecture in one paragraph

Input signal is parsed into facts `(predicate, [participants])` via natasha's dependency tree and stored without weights or metadata. Each sentence additionally writes one *observation* record holding all its lemmas together — this is what enables joint-activation scoring later. Reasoning is framing-first: the signal compresses the association space by intersection — only facts jointly activated by a sufficient number of signal lemmas survive (threshold `max(2, ⌈N/2⌉)` for N≥2). Then floor-by-floor traversal expands from that compressed seed. Coherence is the sum of two independent counts: direct facts with full coverage, and bridge chains where a shared neighbor connects two query lemmas from disjoint branches. Chain strength stays as bridge diagnostics, not part of the score, so popular graph hubs do not dominate. Conflicts are not a system operation; tensions between facts surface as output of `reason()`, not a background scan.

Full architectural documents:
- [principles_ru.md](./principles_ru.md) (Russian, canonical) · [principles_en.md](./principles_en.md) (English translation)
- [architecture_ru.md](./architecture_ru.md) · [architecture_en.md](./architecture_en.md) (condensed overviews)

## Installation

Requires Python 3.10+.

```bash
git clone https://github.com/varshchik/nsai
cd nsai
pip install -r requirements.txt
```

## Usage

### Interactive mode

```bash
python main.py
```

Sample session:

```
NSAI v0.1
  ввод → perceive | ?ввод → reason | !load файл
  !clear — сброс сессии | !debug — отладка
  !curiosity | !ask | @лемма | !stats | !cmp a || b

>>> мама мыла раму
  💾 [relation] мыть -> ['мама', 'рама']
  💾 [observation] ['мама', 'мыть', 'рама']

>>> кот не спит
  💾 [relation] не_спать -> ['кот']
  💾 [observation] ['кот', 'не_спать']

>>> ?кот спит
  📡 Сигнал: ['кот', 'спать']
  🏢 Обход: 2 этажа, N фактов | согласованность: ... (прямых: ..., мостов: ...)
```

Commands:

- `text` — parse and store (perceive)
- `?text` — query without storing (reason)
- `@lemma` — look up all facts about a lemma
- `!load file` — read a file line by line into the graph
- `!cmp a || b` — compare coherence of two queries side by side
- `!curiosity` — list open questions ranked by cascade score
- `!ask` — ask the user the top open question
- `!clear` — reset session cache
- `!stats` — storage statistics

### Running tests

```bash
python test_corpus.py
```

## Project structure

```
nsai/
├── README.md
├── LICENSE                  # AGPL-3.0
├── .gitignore
├── requirements.txt
├── main.py                  # core: perceive, reason, parser
├── test_corpus.py           # parser tests
├── principles_ru.md         # canonical: full architectural principles
├── principles_en.md         # English translation
├── architecture_ru.md       # condensed Russian overview
└── architecture_en.md       # condensed English overview
```

## How it works

**Parser.** natasha builds a dependency tree for each sentence. Facts are extracted from the tree by relation type: VERB nodes with nsubj/obj/obl become predicate-argument relations; amod becomes modifier relations; prepositional phrases become preposition-relation triples; particles compound with their head verb (`не` + `спать` → `не_спать`); enumerations are gathered through conj/appos/nmod siblings; relative clauses resolve their antecedent through tree head lookup. A linear positional fallback handles short sentences where natasha mistags a NOUN as root and orphans the VERB. Linear positional parsing as the primary mechanism was tried and rejected — Russian's free word order requires structural analysis.

**Storage.** Each sentence produces atomic facts plus one observation record holding all sentence lemmas together. Args follow role order (nsubj → obj → ...), not surface position, which gives a stable canonical key — semantically identical sentences with different word order deduplicate naturally. Predicates are indexed alongside arguments — they are full graph nodes.

**Reasoning.** Query lemmas activate associations from the graph. Each association gets a coverage weight = number of query lemmas it jointly contains. Threshold `max(2, ⌈N/2⌉)` for N≥2 filters out single-match noise. Floor-by-floor traversal expands from compressed seeds; each node tracks which query lemmas reached it, surfacing bridge lemmas as a side effect of the same traversal. Coherence score = direct facts with full coverage + bridge-chain count, both as unit counts. Coherence is not interpretable on its own — the canonical use is `compare(A, B)`: NSAI is a comparator, not an oracle.

## Known limitations (v0.1)

- **Tokenizer is naive.** natasha Segmenter splits on whitespace/punctuation. Punctuation marks, operators, and numbers are not yet first-class graph nodes (numbers are stored as literal entities). This is the first task for v0.2.
- **Syntax parser fails on degenerate sentences.** natasha mistags very short sentences without context (e.g. `мама мыла раму` → `мама` as root). A linear fallback covers the common case but isn't perfect.
- **Heavily nested relative clauses** are parsed by natasha with errors — documented as a system boundary, not an implementation bug.
- **Russian only.** The architecture is language-agnostic in principle; the parser depends on natasha and pymorphy3.
- **No parallelism.** Single-process, single-thread.

## What's next (v0.2)

- Tokenizer: punctuation, operators, numbers as first-class graph nodes — opens architecture to non-linguistic inputs.
- Per-query traversal with reachability intersection, removing the explicit `find_chains` mechanism — bridges fully emerge from traversal counts.
- Tension-driven autonomous iteration: feed `reason()` tensions back as next signal.

## Licensing

Dual-licensed:

- **Open source: GNU Affero General Public License v3.0 (AGPL-3.0).** Derivative works (including SaaS deployments) must be released under the same license with full source available.
- **Commercial license available.** Contact the author if AGPL terms are incompatible with your use case.

Documentation (principles_*.md, architecture_*.md) is licensed under [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/).

## Author

Independent researcher based in Canada. Project developed in personal time, outside any institutional or corporate affiliation.

For commercial licensing, collaboration, or substantive technical questions: me@varshchik.dev

## Contributing

Open an issue before submitting a pull request. Contributions to core code require a CLA granting the author the right to relicense (necessary for the dual-licensing model). For prior art references: open an issue with a citation.
