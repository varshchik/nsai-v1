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

Input signal is parsed into facts `(predicate, [participants])` via natasha's dependency tree and stored without weights or metadata. Each sentence additionally writes one *observation* record holding all its lemmas together — this is what enables joint-activation scoring later. Reasoning is framing-first: the signal compresses the association space by intersection — only facts jointly activated by a sufficient number of signal lemmas survive (threshold ⌈N/2⌉). Then floor-by-floor traversal expands from that compressed seed. Coherence scores only facts where *all* query lemmas are simultaneously present; bridge lemmas (shared neighbors of query lemmas) emerge from traversal and contribute via chain strength. Conflicts are not a system operation; tensions between facts surface as output of `reason()`, not a background scan.

Full architectural document: [explanation.md](./explanation.md) (Russian) · [architecture.md](./architecture.md) (English summary)

## Installation

Requires Python 3.10+.

```bash
git clone https://github.com/varshchik/nsai
cd nsai
pip install natasha pymorphy3