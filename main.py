import re, json, sqlite3
from collections import defaultdict
from natasha import Segmenter, NewsEmbedding, NewsMorphTagger, NewsSyntaxParser, Doc as NatashaDoc
import pymorphy3 as _pm3_lib

# ═══════════════════════════════════════════
#  Токенизация
# ═══════════════════════════════════════════

_RU_LETTERS = set('абвгдеёжзийклмнопрстуфхцчшщъыьэюя')

def is_literal(token):
    """Не русское слово (число, латиница). Литерал = лемма-самосебе."""
    return bool(token) and token[0] not in _RU_LETTERS

# ═══════════════════════════════════════════
#  БД
# ═══════════════════════════════════════════

def init_db(path='nsai_memory.db'):
    conn = sqlite3.connect(path)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS knowledge (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        fact TEXT, args_json TEXT, type TEXT,
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP)''')
    c.execute('''CREATE TABLE IF NOT EXISTS knowledge_args (
        knowledge_id INTEGER, arg_lemma TEXT,
        FOREIGN KEY(knowledge_id) REFERENCES knowledge(id))''')
    for idx in ['idx_fact ON knowledge(fact)',
                'idx_arg ON knowledge_args(arg_lemma)',
                'idx_fact_type ON knowledge(fact, type)']:
        c.execute(f'CREATE INDEX IF NOT EXISTS {idx}')
    conn.commit()
    return conn, c

def load_templates(path='template.json'):
    """Заглушка для обратной совместимости с read_book.py.
    template.json больше не загружается — роли выводятся из UD POS natasha.
    """
    return {}

# ═══════════════════════════════════════════
#  Хранение
# ═══════════════════════════════════════════

def save_fact(fact, args, ftype, *, cur, con):
    """Единая функция записи факта в граф. Тип — служебная метка.

    Структура одна: (предикат, [участники]).
      relation    → (мыть, [мама, рама])
      entity      → (яблоко, [])
      IS_A        → (являться, [сократ, человек])
      observation → ('', [мама, мыть, рама])  ← все леммы предложения

    Дедуп:
      entity      — по fact (одно имя, одна запись).
      observation — по args_json (тот же набор лемм = то же предложение).
      relation    — по (fact, args_json).

    Предикат индексируется в knowledge_args наравне с args, чтобы
    pull_by_lemma находил факт и через имя предиката, и через имя
    аргумента. Для observation предикат пустой — индексируются только args.
    """
    args_clean = sorted(set(args)) if ftype == 'observation' else list(args)
    aj = json.dumps(args_clean, ensure_ascii=False)

    # Дедуп по типу
    if ftype == 'entity':
        cur.execute("SELECT 1 FROM knowledge WHERE fact=? AND type='entity'", (fact,))
        if cur.fetchone(): return
    elif ftype == 'observation':
        if not args_clean: return
        cur.execute("SELECT 1 FROM knowledge WHERE args_json=? AND type='observation'", (aj,))
        if cur.fetchone(): return
    elif ftype == 'relation':
        cur.execute("SELECT 1 FROM knowledge WHERE fact=? AND args_json=? AND type='relation'", (fact, aj))
        if cur.fetchone(): return

    cur.execute("INSERT INTO knowledge (fact, args_json, type) VALUES (?,?,?)", (fact, aj, ftype))
    kid = cur.lastrowid

    # Индексация участников. Предикат добавляется только если непустой
    # (observation имеет fact='', индексируем только args).
    participants = list(args_clean)
    if fact and fact not in args_clean:
        participants.insert(0, fact)
    for a in participants:
        cur.execute("INSERT INTO knowledge_args (knowledge_id, arg_lemma) VALUES (?,?)", (kid, a))

    if ftype == 'observation':
        print(f"  💾 [observation] {args_clean}")
    else:
        print(f"  💾 [{ftype}] {fact} -> {args_clean}")


# ═══════════════════════════════════════════
#  Морфология — Natasha стек
# ═══════════════════════════════════════════

class _NatashaMorph:
    """Natasha — POS + feats (контекстный).
    pymorphy3 — лемматизация, направляемая POS от natasha.

    MorphVocab убран: он тянет pymorphy2 + pkg_resources,
    что ломается на Windows. pymorphy3 лемматизирует надёжнее
    и уже есть в зависимостях.
    """

    # UD POS → pymorphy3 POS (для выбора правильного разбора при лемматизации)
    _UD_TO_PM = {
        'NOUN':  ('NOUN', 'NPRO'),
        'PROPN': ('NOUN',),
        'VERB':  ('VERB', 'INFN'),
        'ADJ':   ('ADJF', 'ADJS'),
        'ADP':   ('PREP',),
        'ADV':   ('ADVB',),
        'PART':  ('PRCL',),
        'CCONJ': ('CONJ',),
        'SCONJ': ('CONJ',),
        'PRON':  ('NPRO',),
        'NUM':   ('NUMR',),
        'DET':   ('ADJF',),
        'INTJ':  ('INTJ',),
    }

    def __init__(self):
        self._morph3 = _pm3_lib.MorphAnalyzer()
        self._seg    = Segmenter()
        _emb         = NewsEmbedding()
        self._tag    = NewsMorphTagger(_emb)
        self._syn    = NewsSyntaxParser(_emb)

    def analyze(self, text):
        """Токены с .text .pos .lemma .feats .id .head_id .rel.
        POS — от natasha (контекстный, решает дизамбигуацию).
        Дерево зависимостей — от natasha syntax parser.
        Лемма — от pymorphy3, выбирается разбор совпадающий с natasha POS.
        """
        if not text.strip():
            return []
        doc = NatashaDoc(text)
        doc.segment(self._seg)
        doc.tag_morph(self._tag)
        doc.parse_syntax(self._syn)
        for t in doc.tokens:
            target = self._UD_TO_PM.get(t.pos, ())
            parses = self._morph3.parse(t.text)
            best = next((p for p in parses if str(p.tag.POS) in target), None)
            if best is None and parses:
                best = parses[0]
            t.lemma = best.normal_form.lower() if best else t.text.lower()
        return doc.tokens



# ═══════════════════════════════════════════
#  Граф: чтение
# ═══════════════════════════════════════════

def pull_by_lemma(lemmas, *, cur):
    """Все факты где участвуют данные леммы."""
    if not lemmas: return []
    ph = ','.join('?' * len(lemmas))
    cur.execute(f"""SELECT DISTINCT k.id, k.fact, k.args_json, k.type
        FROM knowledge k JOIN knowledge_args ka ON ka.knowledge_id = k.id
        WHERE ka.arg_lemma IN ({ph})""", list(lemmas))
    seen = set()
    out = []
    for r in cur.fetchall():
        if r[0] not in seen:
            seen.add(r[0])
            out.append({'id': r[0], 'fact': r[1], 'args': json.loads(r[2]), 'type': r[3]})
    return out

def pull_framing(fact, args, *, cur):
    """Завершённые факты с тем же предикатом и общим участником."""
    if not args: return []
    ph = ','.join('?' * len(args))
    cur.execute(f"""SELECT DISTINCT k.id, k.fact, k.args_json, k.type
        FROM knowledge k JOIN knowledge_args ka ON ka.knowledge_id = k.id
        WHERE k.fact = ? AND k.type = 'relation' AND ka.arg_lemma IN ({ph})""",
        [fact] + list(args))
    args_set, seen, out = set(args), set(), []
    for r in cur.fetchall():
        if r[0] in seen: continue
        sa = json.loads(r[2])
        if sa and args_set.intersection(sa):
            seen.add(r[0])
            out.append({'id': r[0], 'fact': r[1], 'args': sa, 'type': r[3]})
    return out


def signal_coverage(fact_rec, signal_lemmas):
    """Сколько лемм сигнала одновременно активируют этот факт.

    Работает для всех типов записей:
    - relation/entity: fact-лемма теперь тоже в knowledge_args,
      поэтому и она, и args покрываются через одно поле args.
    - observation: все леммы предложения сразу в args.

    Пример: сигнал {яблоко, красный, дерево, висеть}
      observation: [висеть, красный, яблоко, дерево]  coverage=4  ← максимум
      relation висеть → [яблоко, дерево] + fact=висеть → coverage=3
      relation красный → [яблоко] + fact=красный → coverage=2
      entity баобаб → [] + fact=баобаб → coverage=0  ← отсеивается
    """
    # args_json содержит только NP-аргументы; fact-лемма хранится отдельно.
    # Проверяем оба поля чтобы не терять предикаты при подсчёте покрытия.
    participants = set(fact_rec['args'])
    if fact_rec.get('fact'):
        participants.add(fact_rec['fact'])
    return sum(1 for l in signal_lemmas if l in participants)


# ═══════════════════════════════════════════
#  ПОЭТАЖНЫЙ ОБХОД
# ═══════════════════════════════════════════

def floor_traversal(start_lemmas, *, cur, depth=3, query_lemmas=None):
    """BFS от стартовых лемм по рёбрам графа.

    На каждом этаже расширяем фронт ассоциаций на один прыжок.
    counts[lemma] = число distinct фактов в пределах depth, в которых
    участвует лемма — включая предикаты, а не только args.

    Это критично для силлогизмов: «все люди смертны» хранится как
    смертный → [человек], где смертный — предикат. Без учёта предикатов
    запрос {сократ, смертный} не находит сходимость через человек.

    Bridge-цепочки выходят как побочный продукт обхода: каждый узел
    помечается множеством query-лемм, которые до него «дотянулись»
    через граф. Лемма, которой коснулись две query-леммы из непересекающихся
    стартовых веток — это bridge. Цепочки `find_chains` теперь не отдельный
    проход по результатам, а наблюдение из traversal.

    Возвращает:
      floors — [{'floor': N, 'facts': [...]}]
      counts — {lemma: int}
      chains — [{'from', 'to', 'bridge', 'a_facts', 'b_facts', 'strength'}]
    """
    query_lemmas = set(query_lemmas) if query_lemmas else set()
    frontier = set(start_lemmas)
    visited_lemmas = set(start_lemmas)
    visited_ids = set()
    floors = []
    counts = {}

    # Какие query-леммы дотянулись до каждого узла (через цепочку фактов).
    # Стартовый шаг: query-лемма дотягивается сама до себя.
    reached_by = {l: {l} for l in query_lemmas if l in start_lemmas}
    # Какие факты упоминают каждую лемму (для восстановления цепочки)
    fact_index = {}

    for n in range(depth):
        if not frontier:
            break
        facts = pull_by_lemma(list(frontier), cur=cur)
        floor_facts, next_frontier = [], set()

        for f in facts:
            if f['id'] in visited_ids:
                continue
            visited_ids.add(f['id'])
            floor_facts.append(f)
            participants = list(f['args'])
            if f['fact']:
                participants.append(f['fact'])

            # Какие query-леммы привели к этому факту?
            # Те, что уже дотягивались до любого его участника.
            sources = set()
            for lemma in participants:
                sources.update(reached_by.get(lemma, set()))

            for lemma in participants:
                counts[lemma] = counts.get(lemma, 0) + 1
                fact_index.setdefault(lemma, []).append(f)
                # Распространение: любая query-лемма из sources теперь
                # дотягивается до всех остальных участников этого факта.
                if lemma not in reached_by:
                    reached_by[lemma] = set()
                reached_by[lemma].update(sources)
                if lemma not in visited_lemmas:
                    visited_lemmas.add(lemma)
                    next_frontier.add(lemma)

        floors.append({'floor': n + 1, 'facts': floor_facts})
        frontier = next_frontier

    # Bridge: лемма не из query, но до неё дотянулись ≥2 query-лемм.
    # Цепочка строится из фактов, упоминающих bridge.
    chains = []
    if query_lemmas:
        seen_pairs = set()
        for bridge, sources in reached_by.items():
            if bridge in query_lemmas:
                continue
            qsources = sources & query_lemmas
            if len(qsources) < 2:
                continue
            qlist = sorted(qsources)
            for i in range(len(qlist)):
                for j in range(i + 1, len(qlist)):
                    a, b = qlist[i], qlist[j]
                    if (a, b, bridge) in seen_pairs:
                        continue
                    seen_pairs.add((a, b, bridge))
                    bridge_facts = fact_index.get(bridge, [])
                    a_facts = [f for f in bridge_facts if a in (f.get('fact'),) + tuple(f['args'])]
                    b_facts = [f for f in bridge_facts if b in (f.get('fact'),) + tuple(f['args'])]
                    if a_facts and b_facts:
                        chains.append({
                            'from': a, 'to': b, 'bridge': bridge,
                            'a_facts': a_facts, 'b_facts': b_facts,
                            'strength': len(a_facts) * len(b_facts),
                        })
    chains.sort(key=lambda c: c['strength'], reverse=True)

    return floors, counts, chains

# ═══════════════════════════════════════════
#  ЯДРО: analyze()
# ═══════════════════════════════════════════

def _is_transitive_verb(lemma, morph):
    """Транзитивность через pymorphy3.grammemes. Единая точка определения.

    Применяется к чистой лемме (без частицы-префикса): не_спать → спать.
    Используется в analyze (детекция дыр при perceive) и scan_curiosity
    (фоновый сбор дыр). Один архитектурный факт — одна реализация.
    """
    clean = lemma.rsplit('_', 1)[-1] if '_' in lemma else lemma
    parses = morph._morph3.parse(clean)
    if not parses:
        return False
    tag = parses[0].tag
    if str(tag.POS) not in ('VERB', 'INFN'):
        return False
    return 'tran' in tag.grammemes


def analyze(fact, args, *, cur, morph, preloaded=None):
    """Подтянуть граф, измерить согласованность, вернуть результат.

    IS_A — обычный предикат, без привилегированного обхода.
    preloaded — ассоциации из floor_traversal, фильтруются в памяти.
    """
    args_set = set(args)

    if preloaded is not None:
        associations = [a for a in preloaded
                        if any(arg in args_set for arg in a['args'])]
        framing = [a for a in preloaded
                   if a['fact'] == fact and a['type'] == 'relation'
                   and any(arg in args_set for arg in a['args'])]
    else:
        framing = pull_framing(fact, args, cur=cur)
        associations = pull_by_lemma(list(args_set), cur=cur)

    confirmations = [a for a in associations
                     if a['type'] == 'relation' and a['fact'] == fact and set(a['args']) == args_set]

    # Дыра: транзитивный глагол с менее чем 2 аргументами.
    # Транзитивность — _is_transitive_verb (pymorphy3.grammemes),
    # единая точка реализации для analyze и scan_curiosity.
    holes = []
    if _is_transitive_verb(fact, morph) and len(args) < 2:
        holes.append({'fact': fact, 'args': list(args),
                      'missing': 'объект' if args else 'субъект + объект'})

    return {'framing': framing, 'associations': associations,
            'confirmations': confirmations, 'holes': holes}

# ═══════════════════════════════════════════
#  Оперативка
# ═══════════════════════════════════════════

class WorkingMemory:
    """Сессионный кэш лемм — bias стартового фронта в reason().

    Состояние линейного парсера (entities/actions/modifiers/particles)
    убрано вместе с переходом на дерево зависимостей natasha.
    """

    def __init__(self):
        self.session = []
        self._session_lemma_cache = set()

    def reset(self):
        """Совместимость API: дерево не держит междупредложенческого состояния."""
        pass

    def clear_session(self):
        self.session.clear()
        self._session_lemma_cache.clear()

    def push_signal(self, text, morph):
        """Леммы текущего сигнала идут в кэш — bias для floor_traversal."""
        for token in morph.analyze(text):
            raw = token.text.lower()
            lemma = token.lemma.lower() if not is_literal(raw) else raw
            self._session_lemma_cache.add(lemma)
        self.session.append({'text': text})

    def session_lemmas(self):
        return self._session_lemma_cache

# ═══════════════════════════════════════════
#  Парсер (сенсорный слой)
# ═══════════════════════════════════════════

# ═══════════════════════════════════════════
#  perceive()
# ═══════════════════════════════════════════

# Если True — perceive дополнительно показывает framing/ассоциации каждого
# сохраняемого факта. Чисто наблюдательный вывод; на состояние графа
# не влияет. Каждый show_facts включает 1-2 SQL запроса, на корпусе
# может быть дорогим — выключай при batch-загрузке.
PERCEIVE_VERBOSE = True

def _run_parser(text, save_fn, wm, morph):
    """Извлечение фактов из дерева зависимостей natasha.

    Алгоритм:
      1. Каждый VERB-узел → relation: предикат + nsubj + obj/iobj/obl/xcomp.
         Дополнительно подбираются conj/appos/nmod-сиблинги аргументов
         (перечисления без запятых).
      2. Препозиционные фразы (NOUN с case-ребёнком ADP) → отдельная
         relation: предлог → [head, dep].
      3. ADJ через amod → modifier-relation.
      4. ADJ как root → predicate-relation.
      5. Частицы через advmod+PART → составная лемма.
      6. NOUN/PROPN не вошедшие ни в одну relation → entity.
      7. Литералы → entity.

    Fallback: если дерево вырождено (NOUN root + VERB не-root) — короткое
    предложение natasha не разобрала. В этом случае извлекаем relation
    из VERB напрямую через позицию NP в тексте.
    """
    tokens = morph.analyze(text)
    if not tokens:
        return set()

    by_id = {t.id: t for t in tokens}
    children = {}
    for t in tokens:
        children.setdefault(t.head_id, []).append(t)

    all_lemmas = set()
    used_ids   = set()

    def _get_lemma(t):
        base = t.lemma.lower()
        if t.pos in ('VERB', 'ADJ'):
            particles = sorted(
                c.lemma.lower() for c in children.get(t.id, [])
                if c.rel == 'advmod' and c.pos == 'PART'
            )
            if particles:
                return '_'.join(particles + [base])
        return base

    def _collect_conj(node):
        """Сиблинги через conj/appos/nmod/amod-NOUN — перечисление."""
        result = []
        for c in children.get(node.id, []):
            if c.rel in ('conj', 'appos') and c.pos in ('NOUN', 'PROPN', 'PRON'):
                result.append(c)
                result.extend(_collect_conj(c))
            elif c.rel == 'amod' and c.pos in ('NOUN', 'PROPN'):
                # amod-NOUN — natasha-аномалия: «рыбу мясо молоко»
                # рыбу → amod head=мясо. Семантически это сиблинг.
                result.append(c)
                result.extend(_collect_conj(c))
            elif c.rel == 'nmod' and c.pos in ('NOUN', 'PROPN'):
                has_case = any(cc.rel == 'case' for cc in children.get(c.id, []))
                if not has_case:
                    result.append(c)
                    result.extend(_collect_conj(c))
        return result

    # ── Fallback: дерево вырождено ──
    # Признак: NOUN/PROPN как root + хоть один VERB не-root.
    # Natasha ломается на коротких предложениях без пунктуации.
    roots = [t for t in tokens if t.head_id.endswith('_0')]
    has_noun_root = any(r.pos in ('NOUN', 'PROPN') for r in roots)
    has_orphan_verb = any(
        t.pos == 'VERB' and not t.head_id.endswith('_0')
        and t.rel not in ('aux', 'cop')
        for t in tokens
    )
    fallback = has_noun_root and has_orphan_verb

    if fallback:
        # Простой линейный режим: VERB между NP — относим всё что выглядит как NP
        verbs = [t for t in tokens if t.pos == 'VERB' and t.rel not in ('aux', 'cop')]
        if verbs:
            v = verbs[0]
            pred = _get_lemma(v)
            all_lemmas.add(pred)
            args = []
            for t in tokens:
                # ADJ включён: natasha часто тегирует NOUN:Acc как ADJ
                if t.pos in ('NOUN', 'PROPN', 'PRON', 'ADJ') and t.id != v.id:
                    arg = _get_lemma(t)
                    args.append(arg)
                    all_lemmas.add(arg)
                    used_ids.add(t.id)
            used_ids.add(v.id)
            save_fn(pred, args, 'relation')

    # ── 1. Литералы ──
    for t in tokens:
        if t.id in used_ids: continue
        if is_literal(t.text.lower()):
            lemma = t.text.lower()
            save_fn(lemma, [], 'entity')
            all_lemmas.add(lemma)
            used_ids.add(t.id)

    # ── 2. VERB-предикаты ──
    # Порядок args: ролевой приоритет (nsubj → nsubj:pass → obj → iobj →
    # obl → xcomp). Внутри роли — порядок возврата natasha, с сиблингами
    # через conj/appos/nmod сразу после своей головы. Поверхностная
    # позиция не используется: «Кот ест рыбу» и «Рыбу ест кот» дают
    # один канонический ключ для дедупликации.
    for t in tokens:
        if t.id in used_ids: continue
        if t.pos != 'VERB' or t.rel in ('aux', 'cop'):
            continue
        pred = _get_lemma(t)
        all_lemmas.add(pred)
        args = []

        order = ('nsubj', 'nsubj:pass', 'obj', 'iobj', 'obl', 'xcomp')
        deps  = children.get(t.id, [])
        for rel_type in order:
            for c in deps:
                if c.rel == rel_type and c.pos in ('NOUN', 'PROPN', 'PRON', 'NUM', 'ADJ'):
                    arg_lemma = _get_lemma(c)
                    if c.pos == 'PRON' and t.rel == 'acl:relcl':
                        head = by_id.get(t.head_id)
                        if head and head.pos in ('NOUN', 'PROPN'):
                            arg_lemma = _get_lemma(head)
                    args.append(arg_lemma)
                    all_lemmas.add(arg_lemma)
                    used_ids.add(c.id)
                    for sibling in _collect_conj(c):
                        sib_lemma = _get_lemma(sibling)
                        args.append(sib_lemma)
                        all_lemmas.add(sib_lemma)
                        used_ids.add(sibling.id)

        # Относительные клаузы: VERB с rel=acl:relcl относится к голове.
        # Голова — это объект (книга которую я читал → читал [книга]).
        # Если ни один аргумент не разрешился через PRON-замену, добавляем
        # голову явно — это и есть антецедент относительной клаузы.
        if t.rel == 'acl:relcl':
            head = by_id.get(t.head_id)
            # Если голова acl:relcl — ADJ-предикат, реальный антецедент
            # это его nsubj (Книга которую я читал была интересной:
            # читал.head=интересной[ADJ root], антецедент=Книга[nsubj]).
            if head and head.pos == 'ADJ':
                for hc in children.get(head.id, []):
                    if hc.rel in ('nsubj', 'nsubj:pass') and hc.pos in ('NOUN', 'PROPN'):
                        head = hc
                        break
            if head and head.pos in ('NOUN', 'PROPN'):
                head_lemma = _get_lemma(head)
                if head_lemma not in args:
                    args.append(head_lemma)
                    all_lemmas.add(head_lemma)
            args = [l for l in args if l not in ('который', 'что', 'кто')]

        used_ids.add(t.id)
        for c in children.get(t.id, []):
            if c.rel == 'advmod' and c.pos == 'PART':
                used_ids.add(c.id)

        save_fn(pred, args, 'relation')

    # ── 3. Препозиционные фразы: NOUN с case-ADP-ребёнком ──
    for t in tokens:
        if t.id in used_ids: continue
        if t.pos not in ('NOUN', 'PROPN'):
            continue
        prep_child = next(
            (c for c in children.get(t.id, []) if c.rel == 'case' and c.pos == 'ADP'),
            None
        )
        if prep_child is None:
            continue
        head = by_id.get(t.head_id)
        if head is None or head.pos not in ('NOUN', 'PROPN'):
            continue
        prep_lemma = prep_child.lemma.lower()
        head_lemma = _get_lemma(head)
        dep_lemma  = _get_lemma(t)
        all_lemmas.update([prep_lemma, head_lemma, dep_lemma])
        save_fn(prep_lemma, [head_lemma, dep_lemma], 'relation')
        used_ids.update([t.id, prep_child.id, head.id])

    # ── 4. ADJ через amod ──
    for t in tokens:
        if t.id in used_ids: continue
        if t.pos == 'ADJ' and t.rel == 'amod':
            head = by_id.get(t.head_id)
            if head and head.pos in ('NOUN', 'PROPN'):
                mod_lemma  = _get_lemma(t)
                head_lemma = _get_lemma(head)
                all_lemmas.update([mod_lemma, head_lemma])
                save_fn(mod_lemma, [head_lemma], 'relation')
                used_ids.add(t.id)

    # ── 5. ADJ как предикат ──
    for t in tokens:
        if t.id in used_ids: continue
        if t.pos == 'ADJ' and t.rel in ('root', 'parataxis'):
            mod_lemma = _get_lemma(t)
            all_lemmas.add(mod_lemma)
            args = []
            for c in children.get(t.id, []):
                if c.rel in ('nsubj', 'nsubj:pass') and c.pos in ('NOUN', 'PROPN', 'PRON'):
                    arg_lemma = _get_lemma(c)
                    args.append(arg_lemma)
                    all_lemmas.add(arg_lemma)
                    used_ids.add(c.id)
            if args:
                save_fn(mod_lemma, args, 'relation')
                used_ids.add(t.id)

    # ── 6. Оставшиеся NOUN/PROPN → entity ──
    for t in tokens:
        if t.id in used_ids: continue
        if t.pos in ('NOUN', 'PROPN'):
            lemma = _get_lemma(t)
            all_lemmas.add(lemma)
            save_fn(lemma, [], 'entity')
            used_ids.add(t.id)

    return all_lemmas


def perceive(text, _cursor=None, _conn=None,
             _morph=None, _wm=None):
    """Принять сигнал, записать факты в граф.

    Фильтр entity-only: если предложение породило только entity-факты
    (ни одной relation), коммит откатывается. Парсер не разобрал
    структуру — лучше пропустить чем засорить граф изолированными узлами.
    """
    morph = _morph or _MORPH
    wm = _wm or _WM; cur = _cursor or _CUR; con = _conn or _CONN
    wm.reset()
    wm.push_signal(text, morph)

    relation_count = [0]  # mutable счётчик через замыкание

    def save(fact, args, ftype):
        if ftype == 'relation':
            relation_count[0] += 1
        if PERCEIVE_VERBOSE and ftype == 'relation':
            r = analyze(fact, args, cur=cur, morph=morph)
            if r['framing']:
                print(f"  🎯 Framing ({fact} -> {args}):")
                for a in r['framing']: print(f"     {a['fact']} -> {a['args']}")
            fids = {f['id'] for f in r['framing']}
            assoc_only = [a for a in r['associations'] if a['id'] not in fids]
            if assoc_only:
                print(f"  🔗 Ассоциации ({fact} -> {args}):")
                for a in assoc_only: print(f"     {a['fact']} -> {a['args']}")
            for h in r['holes']:
                print(f"  🕳️  {h['fact']} -> {h['args']} — не хватает: {h['missing']}")
        save_fact(fact, args, ftype, cur=cur, con=con)

    # Один токен в сигнале → намеренная одиночная сущность, разрешаем.
    # Перечисление NP без глагола («Сократ человек») — тоже разрешаем,
    # это легитимное наблюдение.
    # Фильтруем только если был VERB, но relation не получилась —
    # значит парсер не сумел связать предикат с аргументами.
    tokens = morph.analyze(text)
    has_verb = any(t.pos == 'VERB' for t in tokens)

    all_lemmas = _run_parser(text, save, wm, morph)

    if has_verb and relation_count[0] == 0:
        con.rollback()
        if PERCEIVE_VERBOSE:
            print(f"  ⚠️  Предложение пропущено: парсер не связал глагол.")
        return

    save_fact('', all_lemmas, 'observation', cur=cur, con=con)
    con.commit()

# ═══════════════════════════════════════════
#  reason() — чтение с итеративной абдукцией
# ═══════════════════════════════════════════

def _extract_signal(text, morph):
    """Парсинг без записи → {lemmas, facts}."""
    wm = WorkingMemory()
    collected = []
    def fake(f, a, t): collected.append({'fact': f, 'args': list(a), 'type': t})
    lemmas = _run_parser(text, fake, wm, morph)
    return {'lemmas': list(lemmas), 'facts': collected}


def reason(text, _cursor=None, _conn=None,
           _morph=None, _wm=None):
    morph = _morph or _MORPH
    cur = _cursor or _CUR; wm = _wm or _WM

    signal = _extract_signal(text, morph)
    working = [f for f in signal['facts'] if f['type'] == 'relation']
    query_lemmas = set(signal['lemmas'])

    # Стартовый фронт = леммы запроса + bias из текущей сессии
    session_bias = wm.session_lemmas()
    start_lemmas = query_lemmas | session_bias

    floors, counts, chains = floor_traversal(start_lemmas, cur=cur, depth=3,
                                              query_lemmas=query_lemmas)
    all_associations = [f for fl in floors for f in fl['facts']]

    # Сжатие сигнала. Два независимых пути:
    # (1) прямое пересечение — факты, где >= threshold лемм сигнала
    #     одновременно присутствуют в args/предикате;
    # (2) мостовое — факты, поддерживающие найденные bridge-цепочки.
    # Когда прямого пересечения нет, мост и есть compression через
    # транзитивность. Силлогизм «Сократ — человек, человек смертен» —
    # типовой случай: ни один факт не содержит {сократ, смертный}
    # одновременно, но мост через `человек` даёт ровно те две записи,
    # на которых держится вывод. Open-world (выгрузка всех ассоциаций)
    # срабатывает только когда нет ни прямых, ни мостовых наблюдений —
    # иначе сигнал из фильтра превращается в семя расширения и
    # framing отрабатывает в обратную сторону.
    _n = len(query_lemmas)
    _threshold = max(2, (_n + 1) // 2) if _n > 1 else 1
    for a in all_associations:
        a['_cov'] = signal_coverage(a, query_lemmas)

    direct = [a for a in all_associations if a['_cov'] >= _threshold]

    bridge_supports = []
    seen_ids = {a['id'] for a in direct}
    for c in chains:
        for f in c['a_facts'] + c['b_facts']:
            if f['id'] not in seen_ids:
                seen_ids.add(f['id'])
                bridge_supports.append(f)

    compressed = direct + bridge_supports
    if not compressed:
        compressed = all_associations  # open-world: ни прямых, ни мостовых наблюдений

    # Coherence score = direct_score + bridge_score, каждое в своих единицах.
    # direct_score — число фактов с полным покрытием сигнала (_cov == N).
    # bridge_score — число цепочек: bridge-лемма как общий сосед ≥2 query-лемм
    # из непересекающихся стартовых веток.
    # Сила отдельной цепочки (a_facts × b_facts) остаётся диагностическим
    # показателем моста, но в score не входит, иначе популярные узлы
    # графа тащат score без реального совместного наблюдения.
    direct_score = sum(1 for a in compressed if a.get('_cov', 0) == _n)
    bridge_score = len(chains)
    coherence_score = direct_score + bridge_score

    # Tension — эмерджентный сигнал из traversal, не отдельный сканер.
    # Два факта в compressed об одном объекте с высоким _cov,
    # но из непересекающихся окрестностей → агент не может выбрать
    # перспективу без уточняющего сигнала.
    tensions = []
    seen_pairs = set()
    high_cov = [a for a in compressed if a.get('_cov', 0) >= _threshold]
    for i in range(len(high_cov)):
        for j in range(i + 1, len(high_cov)):
            a, b = high_cov[i], high_cov[j]
            shared = set(a['args']) & set(b['args'])
            if not shared:
                continue
            a_unique = set(a['args']) - set(b['args']) - query_lemmas
            b_unique = set(b['args']) - set(a['args']) - query_lemmas
            if not a_unique or not b_unique:
                continue
            key = (a['id'], b['id'])
            if key in seen_pairs:
                continue
            seen_pairs.add(key)
            for obj in shared:
                tensions.append({
                    'qtype': 'tension',
                    'object': obj,
                    'fact_a': a,
                    'fact_b': b,
                    'question': f"{obj}: {a['fact']} vs {b['fact']}?",
                    'cascade_score': a.get('_cov', 0) + b.get('_cov', 0),
                })
    tensions.sort(key=lambda t: t['cascade_score'], reverse=True)

    result = {
        'signal': signal,
        'floors': floors,
        'coherence_score': coherence_score,
        'counts': counts,
        'framing': [],
        'associations': compressed,
        'confirmations': [],
        'holes': [],
        'repairs': [],
        'iterations': 0,
        'questions': tensions,
        'chains': chains,
    }

    seen_f, seen_c, seen_h = set(), set(), set()
    for iteration in range(5):
        new_facts = []
        for sf in working:
            r = analyze(sf['fact'], sf['args'], cur=cur, morph=morph, preloaded=compressed)
            for a in r['framing']:
                if a['id'] not in seen_f: result['framing'].append(a); seen_f.add(a['id'])
            for c in r['confirmations']:
                if c['id'] not in seen_c: result['confirmations'].append(c); seen_c.add(c['id'])
            for h in r['holes']:
                key = (h['fact'], tuple(h['args']))
                if key not in seen_h: result['holes'].append(h); seen_h.add(key)

            # Абдукция (v4.1): для каждой дыры собрать кандидатов,
            # верифицировать каждого независимым обходом БЕЗ суггестирующих
            # фактов, ранжировать, взять top-1.
            #
            # Принцип: суггестор и валидатор смотрят в разные срезы графа.
            # Кандидат, поддерживаемый только теми же фактами, что его
            # предложили, — это эхо, а не подтверждение.
            for h in r['holes']:
                if h['missing'] != 'объект': continue
                # candidate_lemma → set(id фактов которые его предложили)
                candidates = {}
                for fr in r['framing']:
                    for c in fr['args']:
                        if c not in sf['args']:
                            candidates.setdefault(c, set()).add(fr['id'])
                if not candidates: continue

                # Независимая верификация каждого кандидата
                ranked = []
                for c, src_ids in candidates.items():
                    v_facts = pull_by_lemma(list(set(sf['args']) | {c}), cur=cur)
                    independent = [f for f in v_facts
                                   if f['id'] not in src_ids and c in f['args']]
                    ranked.append((c, len(independent), src_ids))
                ranked.sort(key=lambda x: x[1], reverse=True)

                # Берём top-1; альтернативы оставляем для прозрачности
                top_c, top_score, top_src = ranked[0]
                completed_args = sf['args'] + [top_c]
                result['repairs'].append({
                    'fact': sf['fact'],
                    'original_args': sf['args'],
                    'candidate': top_c,
                    'source_framing_ids': sorted(top_src),
                    'iteration': iteration,
                    'verified_score': top_score,
                    'alternatives': [(c, s) for c, s, _ in ranked[1:5]],
                })
                new_facts.append({'fact': sf['fact'], 'args': completed_args, 'type': 'relation'})

        result['iterations'] = iteration + 1
        if not new_facts: break
        working = new_facts

    repaired = {(r['fact'], tuple(r['original_args'])) for r in result['repairs']}
    for h in result['holes']:
        if (h['fact'], tuple(h['args'])) in repaired: continue
        result['questions'].append(f"{h['fact']} → [{', '.join(h['args'])}, ???] — что именно?"
                                   if h['missing'] == 'объект' else f"{h['fact']} — кто и что?")
    return result


def compare(query_a, query_b, **kw):
    """Сравнить согласованность двух утверждений в одном графе.

    coherence_score сам по себе не интерпретируем. Эта функция —
    канонический способ его использовать: запустить два reason'а,
    вернуть пару (score_a, score_b) для сопоставления.
    """
    a = reason(query_a, **kw)
    b = reason(query_b, **kw)
    return {
        'a': {'query': query_a, 'score': a['coherence_score']},
        'b': {'query': query_b, 'score': b['coherence_score']},
        'verdict': 'a' if a['coherence_score'] > b['coherence_score']
                   else ('b' if b['coherence_score'] > a['coherence_score'] else 'tie'),
    }


def print_reason(r):
    sig = r['signal']
    print(f"\n  📡 Сигнал: {sig['lemmas']}")
    for f in sig['facts']: print(f"     {f['type']}: {f['fact']} → {f['args']}")

    floors = r.get('floors', [])
    score = r.get('coherence_score', 0)
    total_facts = sum(len(fl['facts']) for fl in floors)
    if floors:
        print(f"\n  🏢 Обход: {len(floors)} этажа, {total_facts} фактов | согласованность: {score} (отн.)")
        for fl in floors:
            print(f"     Этаж {fl['floor']}: {len(fl['facts'])} фактов")

    if r['framing']:
        print(f"\n  🎯 Framing ({len(r['framing'])}):")
        for a in r['framing']: print(f"     {a['fact']} → {a['args']}")

    counts = r.get('counts', {})
    fids = {a['id'] for a in r['framing']}
    assoc = sorted(
        [a for a in r['associations'] if a['id'] not in fids],
        key=lambda a: (a.get('_cov', 0), sum(counts.get(arg, 0) for arg in a['args'])),
        reverse=True
    )
    if assoc:
        shown = assoc[:5]
        print(f"\n  🔗 Ассоциации ({len(assoc)}" + (", топ-5" if len(assoc) > 5 else "") + "):")
        for a in shown:
            s = sum(counts.get(arg, 0) for arg in a['args'])
            cov = a.get('_cov', '?')
            print(f"     [cov={cov} score={s}] {a['fact']} → {a['args']}")

    if r['confirmations']:
        print(f"\n  ✅ Согласованность ({len(r['confirmations'])}):")
        for c in r['confirmations']: print(f"     {c['fact']} → {c['args']}")

    if r.get('chains'):
        print(f"\n  ⛓  Цепочки вывода ({len(r['chains'])}):")
        for ch in r['chains'][:3]:
            a_pred = ch['a_facts'][0]['fact'] if ch['a_facts'] else '?'
            b_pred = ch['b_facts'][0]['fact'] if ch['b_facts'] else '?'
            print(f"     {ch['from']} —[{ch['bridge']}]→ {ch['to']}"
                  f"  (через: {a_pred}, {b_pred}  сила={ch['strength']})")

    if r['holes']:
        print(f"\n  🕳️  Дыры:")
        for h in r['holes']: print(f"     {h['fact']} → {h['args']} — {h['missing']}")

    if r['repairs']:
        print(f"\n  🔧 Абдукция ({r['iterations']} итераций):")
        for rp in sorted(r['repairs'], key=lambda x: x['verified_score'], reverse=True):
            score_v = rp['verified_score']
            marker = '✓' if score_v > 0 else '?'
            line = f"     [{marker} indep={score_v}] {rp['fact']} → {rp['original_args']} + [{rp['candidate']}]"
            if rp.get('alternatives'):
                alts = ', '.join(f"{c}({s})" for c, s in rp['alternatives'])
                line += f"   альт: {alts}"
            print(line)

    if r['questions']:
        print(f"\n  ⚡ Напряжения ({len(r['questions'])}):")
        for t in r['questions'][:3]:
            print(f"     [{t['object']}]: {t['fact_a']['fact']}→{t['fact_a']['args']}"
                  f"  vs  {t['fact_b']['fact']}→{t['fact_b']['args']}"
                  f"  (сила={t['cascade_score']})")

    if not any([r['confirmations'], r['holes'], r['repairs']]):
        if score > 0:
            top = sorted(counts.items(), key=lambda x: x[1], reverse=True)[:3]
            print(f"\n  💭 Новая территория. Ближайшее в графе: {[l for l, _ in top]}")
        else:
            print(f"\n  💭 Новая территория.")

# ═══════════════════════════════════════════
#  Curiosity
# ═══════════════════════════════════════════

def scan_curiosity(*, cur=None, morph=None, limit=10):
    cur = cur or _CUR; morph = morph or _MORPH
    questions = []

    cur.execute("SELECT k.fact, k.args_json FROM knowledge k WHERE k.type = 'relation'")
    rows = cur.fetchall()

    for (fact, aj) in rows:
        args = json.loads(aj)
        if _is_transitive_verb(fact, morph) and len(args) < 2:
            framed = pull_framing(fact, args, cur=cur)
            cands = list({fa for fr in framed for fa in fr['args'] if fa not in args})
            if args:
                cur.execute("SELECT COUNT(*) FROM knowledge_args WHERE arg_lemma IN ({})".format(','.join('?' * len(args))), args)
                score = cur.fetchone()[0] + len(cands) * 2
            else:
                score = len(cands) * 2
            questions.append({'qtype': 'hole', 'question': f"{fact} → [{', '.join(args)}, ???]",
                              'lemma': fact, 'fact': fact, 'args': args,
                              'candidates': cands, 'cascade_score': score,
                              'action_hint': f"кандидаты: {', '.join(cands)}" if cands else "ответь объектом"})

    questions.sort(key=lambda q: q['cascade_score'], reverse=True)
    return questions[:limit]


def process_answer(q, answer, *, cur=None, con=None, morph=None):
    """Записать ответ напрямую в граф (v4.1).

    Раньше: текстовая сборка + perceive — порядок и падежи терялись.
    Теперь: нормализуем ответ, дописываем как arg к (fact, args).
    """
    cur = cur or _CUR; con = con or _CONN; morph = morph or _MORPH
    answer = answer.strip().lower()
    if not answer or q['qtype'] != 'hole':
        return
    tokens = morph.analyze(answer)
    lemma = None
    for tok in tokens:
        raw = tok.text.lower()
        if is_literal(raw):
            lemma = raw; break
        if tok.lemma:
            lemma = tok.lemma.lower(); break
    if not lemma:
        print(f"  ⚠️ Не удалось извлечь лемму из ответа: {answer!r}")
        return
    completed = q['args'] + [lemma]
    save_fact(q['fact'], completed, 'relation', cur=cur, con=con)
    con.commit()
    print(f"  ✓ Записано: {q['fact']} → {completed}")

# ═══════════════════════════════════════════
#  Глобальные объекты
# ═══════════════════════════════════════════

_MORPH = _NatashaMorph()
_CONN, _CUR = init_db()
_WM = WorkingMemory()

def reset_buffers():
    """Сброс глобальной WM. Используется тестами для изоляции."""
    _WM.clear_session()

# ═══════════════════════════════════════════
#  Утилиты
# ═══════════════════════════════════════════

def segment_text(text):
    """Разбиение на предложения. Главы/контексты убраны (v4.1)."""
    result = []
    for line in text.strip().split('\n'):
        line = line.strip()
        if not line: continue
        for s in re.split(r'(?<=[.!?])\s+', line):
            if s.strip() and len(s.strip()) > 1:
                result.append(s.strip())
    return result

def load_text(filepath):
    with open(filepath, 'r', encoding='utf-8') as f: text = f.read()
    sentences = segment_text(text)
    print(f"  Файл: {filepath} | {len(sentences)} предложений")
    for s in sentences:
        print(f"  > {s}"); perceive(s)
    _CUR.execute("SELECT COUNT(*) FROM knowledge")
    print(f"\n  Всего: {_CUR.fetchone()[0]} фактов.")

def search_by_lemma(lemma):
    return pull_by_lemma([lemma], cur=_CUR)

def print_stats():
    _CUR.execute("SELECT COUNT(*) FROM knowledge"); t = _CUR.fetchone()[0]
    _CUR.execute("SELECT COUNT(*) FROM knowledge WHERE type='relation'"); r = _CUR.fetchone()[0]
    _CUR.execute("SELECT COUNT(*) FROM knowledge WHERE type='entity'"); e = _CUR.fetchone()[0]
    print(f"  {t} фактов ({r} relation, {e} entity)")

# ═══════════════════════════════════════════
#  CLI
# ═══════════════════════════════════════════

if __name__ == '__main__':
    print("NSAI v0.1")
    print("  <текст>       → perceive (запомнить)")
    print("  ?<текст>      → reason (запрос)")
    print("  !load <файл>  → загрузить корпус")
    print("  !clear — сброс сессии | !debug — отладка")
    print("  !curiosity | !ask | @<лемма> | !stats | !cmp a || b\n")
    pending, debug = None, False
    try:
        while True:
            if pending:
                icon = {'hole': '🕳️'}.get(pending['qtype'], '?')
                inp = input(f"{icon} {pending['question']}\n>>> ").strip()
            else:
                prompt = "🔍 >>> " if debug else ">>> "
                inp = input(prompt).strip()
            if not inp: continue
            if pending and not inp.startswith(('!', '?', '@')):
                process_answer(pending, inp); pending = None; continue
            pending = None
            if inp == "!debug":
                debug = not debug
                print(f"  🔍 Режим отладки: {'ON' if debug else 'OFF'}"); continue
            if inp == "!clear":
                _WM.clear_session(); print(f"  🧹 Сессия очищена."); continue
            if inp.startswith("!load "):
                p = inp.split(None, 1); load_text(p[1]); continue
            if inp == "!curiosity":
                qs = scan_curiosity()
                if qs:
                    print(f"\n  🧠 {len(qs)} вопросов:")
                    for i, q in enumerate(qs, 1): print(f"    {i}. {q['question']} (каскад: {q['cascade_score']})")
                else: print("  💤 Нет вопросов.")
                continue
            if inp == "!ask":
                qs = scan_curiosity(limit=1); pending = qs[0] if qs else None
                if not pending: print("  💤 Нет вопросов.")
                continue
            if inp == "!stats": print_stats(); continue
            if inp.startswith("!cmp "):
                # !cmp утверждение_a || утверждение_b
                rest = inp[5:]
                if '||' not in rest:
                    print("  Использование: !cmp текст_a || текст_b"); continue
                a, b = [x.strip() for x in rest.split('||', 1)]
                res = compare(a, b)
                print(f"  a: «{a}» → score={res['a']['score']}")
                print(f"  b: «{b}» → score={res['b']['score']}")
                print(f"  → {res['verdict']}")
                continue
            if inp.startswith("@"):
                fs = search_by_lemma(inp[1:].strip().lower())
                for f in fs: print(f"  {f['type']}: {f['fact']} → {f['args']}")
                if not fs: print(f"  Не найден.")
                continue
            if inp.startswith("?"): r = reason(inp[1:].strip()); print_reason(r); continue
            perceive(inp)
            if debug:
                print(f"  {'─'*40}")
                r = reason(inp)
                print_reason(r)
    except KeyboardInterrupt: _CONN.close(); print("\nСохранено.")
