"""Изолированный тест compression-фикса в reason().

Не требует natasha/pymorphy3. Конструирует синтетические all_associations
и chains для сократовского кейса, прогоняет старую и новую логику,
сравнивает compressed.

Граф моделирует то, что выдаст floor_traversal на минимальном NSAI-графе
с фактами:
  F1: являться → [сократ, человек]        # Сократ — человек
  F2: смертный → [человек]                # Люди смертны
  F3: разумный → [человек]                # Человек разумен
  F4: двуногий → [человек]                # Человек двуногий
  F5: млекопитающее → [человек]           # Человек — млекопитающее
  F6: бегать → [человек, стадион]         # Человек бегает по стадиону (шум)

Запрос: «Сократ смертен?» → query_lemmas = {сократ, смертный}

Поэтажный обход глубины 3 пройдёт через хаб `человек` и подтянет
все 6 фактов. После сжатия должны остаться только F1 и F2 —
участники моста сократ ↔ смертный через человек.
"""

# ──────────────────────────────────────────────────────────────
# signal_coverage из main.py (копия)
# ──────────────────────────────────────────────────────────────
def signal_coverage(fact_rec, signal_lemmas):
    participants = set(fact_rec['args'])
    if fact_rec.get('fact'):
        participants.add(fact_rec['fact'])
    return sum(1 for l in signal_lemmas if l in participants)


# ──────────────────────────────────────────────────────────────
# СТАРАЯ логика (как в текущем main.py)
# ──────────────────────────────────────────────────────────────
def compress_old(all_associations, chains, query_lemmas):
    _n = len(query_lemmas)
    _threshold = max(2, (_n + 1) // 2) if _n > 1 else 1
    for a in all_associations:
        a['_cov'] = signal_coverage(a, query_lemmas)
    compressed = [a for a in all_associations if a['_cov'] >= _threshold]
    if not compressed:
        compressed = all_associations
    return compressed


# ──────────────────────────────────────────────────────────────
# НОВАЯ логика (compression-фикс)
# ──────────────────────────────────────────────────────────────
def compress_new(all_associations, chains, query_lemmas):
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
        compressed = all_associations
    return compressed


# ──────────────────────────────────────────────────────────────
# Прогон
# ──────────────────────────────────────────────────────────────
def fmt(facts):
    return [f"{f['fact']}→{f['args']}" for f in facts]


def case_socrates():
    """Чистый силлогизм: нет фактов с _cov=N, есть мост."""
    F1 = {'id': 1, 'fact': 'являться',  'args': ['сократ', 'человек']}
    F2 = {'id': 2, 'fact': 'смертный',  'args': ['человек']}
    F3 = {'id': 3, 'fact': 'разумный',  'args': ['человек']}
    F4 = {'id': 4, 'fact': 'двуногий',  'args': ['человек']}
    F5 = {'id': 5, 'fact': 'млекопитающее', 'args': ['человек']}
    F6 = {'id': 6, 'fact': 'бегать',    'args': ['человек', 'стадион']}
    all_ass = [F1, F2, F3, F4, F5, F6]
    chains = [{'from': 'смертный', 'to': 'сократ', 'bridge': 'человек',
               'a_facts': [F2], 'b_facts': [F1], 'strength': 1}]
    return ("Сократ смертен? (силлогизм)",
            all_ass, chains, {'сократ', 'смертный'}, {1, 2})


def case_direct():
    """Прямые наблюдения: факт содержит обе леммы. Мостов нет.
    Шумовые факты с _cov<threshold должны быть отсеяны."""
    F1 = {'id': 1, 'fact': 'есть',    'args': ['кот', 'рыба']}
    F2 = {'id': 2, 'fact': 'любить',  'args': ['кот', 'рыба']}
    F3 = {'id': 3, 'fact': 'спать',   'args': ['кот']}
    F4 = {'id': 4, 'fact': 'плавать', 'args': ['рыба']}
    all_ass = [F1, F2, F3, F4]
    chains = []
    return ("Кот ест рыбу? (прямые наблюдения)",
            all_ass, chains, {'кот', 'рыба'}, {1, 2})


def case_mixed():
    """И прямое, и мост: оба должны попасть в compressed."""
    F1 = {'id': 1, 'fact': 'есть',     'args': ['кот', 'рыба']}      # direct
    F2 = {'id': 2, 'fact': 'являться', 'args': ['кот', 'хищник']}    # мост-опора
    F3 = {'id': 3, 'fact': 'есть',     'args': ['хищник', 'рыба']}   # мост-опора
    F4 = {'id': 4, 'fact': 'спать',    'args': ['кот']}              # шум
    all_ass = [F1, F2, F3, F4]
    chains = [{'from': 'кот', 'to': 'рыба', 'bridge': 'хищник',
               'a_facts': [F2], 'b_facts': [F3], 'strength': 1}]
    return ("Кот ест рыбу? (прямое + мост)",
            all_ass, chains, {'кот', 'рыба'}, {1, 2, 3})


def case_open_world():
    """Ни прямого, ни моста — честный open-world: вернуть всё."""
    F1 = {'id': 1, 'fact': 'светить', 'args': ['солнце']}
    F2 = {'id': 2, 'fact': 'звезда',  'args': ['альдебаран']}
    all_ass = [F1, F2]
    chains = []
    return ("Quantum thermodynamics? (open-world)",
            all_ass, chains, {'квантовый', 'термодинамика'}, {1, 2})


def fmt(facts):
    return [f"{f['fact']}→{f['args']}" for f in facts]


def main():
    cases = [case_socrates(), case_direct(), case_mixed(), case_open_world()]
    fails = 0

    for name, all_ass, chains, query, expected_new_ids in cases:
        print("=" * 64)
        print(name)
        print("=" * 64)
        print(f"query = {sorted(query)}")

        for f in all_ass:
            f.pop('_cov', None)
        old = compress_old(all_ass, chains, query)
        for f in all_ass:
            f.pop('_cov', None)
        new = compress_new(all_ass, chains, query)

        print(f"СТАРАЯ: {len(old)} → {fmt(old)}")
        print(f"НОВАЯ:  {len(new)} → {fmt(new)}")

        actual = {f['id'] for f in new}
        if actual == expected_new_ids:
            print(f"✓ ожидалось {sorted(expected_new_ids)}, получено {sorted(actual)}")
        else:
            print(f"✗ ожидалось {sorted(expected_new_ids)}, получено {sorted(actual)}")
            fails += 1
        print()

    print("=" * 64)
    if fails:
        print(f"ИТОГ: провалов {fails}")
        return 1
    print("ИТОГ: все кейсы прошли")
    return 0


if __name__ == '__main__':
    import sys
    sys.exit(main())
