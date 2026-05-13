"""Тесты sensor cross-check (natasha vs pymorphy3).

Группа конструкций где natasha мисклассифицирует NOUN-instr как ADJ-amod
(самоссылочный head, ADJ помеченный amod без NOUN-родителя).
Pymorphy3 в этих случаях даёт уверенный NOUN-разбор.
"""
import sys
import json
import io
import contextlib

import main


def _silent_perceive(text, cur, con):
    main.reset_buffers()
    old = main.PERCEIVE_VERBOSE
    main.PERCEIVE_VERBOSE = False
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            main.perceive(text, _cursor=cur, _conn=con)
    finally:
        main.PERCEIVE_VERBOSE = old


def _read_facts(cur):
    cur.execute("SELECT fact, args_json, type FROM knowledge ORDER BY id")
    rels, ents = [], []
    for fact, aj, t in cur.fetchall():
        args = json.loads(aj) if aj else []
        if t == 'relation':
            rels.append((fact, args))
        elif t == 'entity':
            ents.append(fact)
    return rels, ents


def check_contains(name, text, must_contain_rels):
    """Проверяет что среди relations есть указанные (не строгое равенство —
    natasha может сгенерировать дополнительные факты помимо целевого)."""
    con, cur = main.init_db(':memory:')
    try:
        _silent_perceive(text, cur, con)
        rels, ents = _read_facts(cur)
    finally:
        con.close()

    act_set = {(f, tuple(sorted(a))) for f, a in rels}
    missing = []
    for f, a in must_contain_rels:
        want = (f, tuple(sorted(a)))
        if want not in act_set:
            missing.append(f"   MISS: {f} -> {sorted(a)}")
    if missing:
        actual = "\n   ".join(f"{f} -> {a}" for f, a in rels)
        return False, f"FAIL: {name}\n   Input: «{text}»\n" + "\n".join(missing) + f"\n   ACTUAL:\n   {actual}"
    return True, f"OK:   {name} → нашёл {must_contain_rels}"


CASES = [
    # Основной кейс
    ("зонт через с", "человек идёт с зонтом",
     [("идти", ["человек", "зонт"])]),
    
    # Другие NOUN-instr с предлогом «с»
    ("молоток через с", "плотник работает с молотком",
     [("работать", ["плотник", "молоток"])]),
    
    ("нож через с", "повар режет с ножом",
     [("резать", ["повар", "нож"])]),
    
    # Контроль: «под дождём» — natasha уже корректна, ничего не должно
    # поменяться от нашего cross-check'а
    ("под дождём (контроль)", "человек идёт под дождём",
     [("идти", ["человек", "дождь"])]),
    
    # Контроль: прямое obj без предлога
    ("прямое obj (контроль)", "человек видит зонт",
     [("видеть", ["человек", "зонт"])]),
]


def main_run():
    print("=" * 64)
    print("SENSOR CROSS-CHECK TESTS")
    print("=" * 64)
    passed = failed = 0
    failures = []
    for name, text, must_have in CASES:
        ok, detail = check_contains(name, text, must_have)
        if ok:
            passed += 1
            print(f"   ✓ {detail}")
        else:
            failed += 1
            failures.append(detail)
            print(f"   ✗ FAIL: {name}")
    print()
    print(f"ИТОГ: {passed} passed, {failed} failed")
    if failures:
        print("\n--- ДЕТАЛИ ---")
        for f in failures:
            print(f)
            print()
    return failed == 0


if __name__ == '__main__':
    sys.exit(0 if main_run() else 1)
