"""
NSAI Test Corpus v4.1

Изоляция: каждый тест получает свежую in-memory БД и сброшенную WM.
Запуск: python test_corpus.py

Замечание о natasha. Часть тестов опирается на конкретный разбор дерева
зависимостей. Natasha — обученная модель, её решения на коротких
предложениях без контекста бывают капризными. Если тест падает с
EXTRA/MISS — это не обязательно баг архитектуры; стоит посмотреть, что
именно вернул парсер, и решить: править main.py, тест или признать
границей системы.
"""

import sys
import json
import io
import contextlib

import main


def _silent_perceive(text, cur, con):
    """perceive() с подавлением вывода и сбросом сессии."""
    main.reset_buffers()
    old = main.PERCEIVE_VERBOSE
    main.PERCEIVE_VERBOSE = False
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            main.perceive(text, _cursor=cur, _conn=con)
    finally:
        main.PERCEIVE_VERBOSE = old


def _read_facts(cur):
    """Считать relation и entity. observation для тестов парсера прозрачен."""
    cur.execute("SELECT fact, args_json, type FROM knowledge ORDER BY id")
    rels, ents = [], []
    for fact, aj, t in cur.fetchall():
        args = json.loads(aj) if aj else []
        if t == 'relation':
            rels.append((fact, args))
        elif t == 'entity':
            ents.append(fact)
    return rels, ents


def run_test(name, text, exp_rels, exp_ents):
    con, cur = main.init_db(':memory:')
    try:
        _silent_perceive(text, cur, con)
        rels, ents = _read_facts(cur)
    finally:
        con.close()

    errs = []
    exp_set = {(f, tuple(a)) for f, a in exp_rels}
    act_set = {(f, tuple(a)) for f, a in rels}

    for f, a in exp_set - act_set:
        errs.append(f"   MISS  relation: {f} -> {list(a)}")
    for f, a in act_set - exp_set:
        errs.append(f"   EXTRA relation: {f} -> {list(a)}")
    for e in set(exp_ents) - set(ents):
        errs.append(f"   MISS  entity:   {e}")
    for e in set(ents) - set(exp_ents):
        errs.append(f"   EXTRA entity:   {e}")

    if errs:
        return False, f"FAIL: {name}\n   Input: «{text}»\n" + "\n".join(errs)
    return True, f"OK:   {name}"


# ═══════════════════════════════════════════
#  Тестовый корпус
# ═══════════════════════════════════════════
#
# Формат: (имя, текст, [(predicate, [args]), ...], [entity, ...])
# Тесты проверяют только relation и entity. observation игнорируется
# на этом уровне — он валидируется отдельно (см. наблюдательные тесты).

TESTS = [

    # ── SVO транзитивный ──────────────────
    ("SVO: транзитивный глагол + объект",
     "кот ест рыбу",
     [("есть", ["кот", "рыба"])], []),

    # ── Fallback: вырожденное дерево ──────
    # natasha на «мама мыла раму» делает «мама» корнем — линейный
    # fallback в main.py берёт первый VERB и собирает все NP/PROPN.
    ("FALLBACK: degenerate tree",
     "мама мыла раму",
     [("мыть", ["мама", "рама"])], []),

    # ── Непереходный ──────────────────────
    ("INTR: непереходный глагол",
     "кот спит",
     [("спать", ["кот"])], []),

    # ── Составная лемма (отрицание) ──────
    ("COMPOUND: частица + глагол",
     "кот не спит",
     [("не_спать", ["кот"])], []),

    # ── Модификатор через amod ───────────
    # ADJ-amod-NOUN → relation; голова без VERB → entity.
    ("MOD: один модификатор",
     "красный дом",
     [("красный", ["дом"])], ["дом"]),

    ("MOD: несколько модификаторов",
     "большой красный дом",
     [("большой", ["дом"]), ("красный", ["дом"])], ["дом"]),

    # ── Одиночная сущность ───────────────
    ("ENTITY: одно слово",
     "дерево",
     [], ["дерево"]),

    # ── Литерал ──────────────────────────
    # Не русское слово → entity с леммой-самосебе.
    ("LITERAL: число",
     "42",
     [], ["42"]),

    # ── Граничные ────────────────────────
    ("EDGE: пустая строка",
     "",
     [], []),

    # ── Перечисление после глагола ───────
    # Сиблинги через conj/appos/nmod-NOUN присоединяются к args.
    ("ENUM: перечисление",
     "кот ест рыбу мясо молоко",
     [("есть", ["кот", "рыба", "мясо", "молоко"])], []),
]


def main_run():
    print("=" * 60)
    print("NSAI TEST CORPUS v4.1")
    print("=" * 60)

    passed = 0
    failed = 0
    failures = []

    for name, text, rels, ents in TESTS:
        ok, detail = run_test(name, text, rels, ents)
        if ok:
            passed += 1
            print(f"   ✓ {detail}")
        else:
            failed += 1
            failures.append(detail)
            print(f"   ✗ FAIL: {name}")

    print("\n" + "=" * 60)
    print(f"ИТОГ: {passed} passed, {failed} failed из {passed + failed}")
    print("=" * 60)

    if failures:
        print("\n--- ДЕТАЛИ ПРОВАЛОВ ---")
        for f in failures:
            print(f)
            print()

    return failed == 0


if __name__ == '__main__':
    sys.exit(0 if main_run() else 1)