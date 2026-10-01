"""规模场景：10万分类、50万引用；叶分类(10万引用)连续并入5000个兄弟 + 1万次查询 <= 30秒。"""
import time

from pixelcanvas import CategoryStore

N_CATEGORIES = 100_000
N_REFS = 500_000
N_SIBLINGS = 5_000
N_QUERIES = 10_000
TIME_BUDGET = 30.0


def test_scale_scenario(tmp_path):
    db = tmp_path / "perf.db"
    # ---- 初始化（不计时）----
    # 1 root；2 hot(10万引用)；3..5002 兄弟；其余为填充分类
    cats = [(1, "root", None), (2, "hot", 1)]
    cats += [(3 + i, f"sib{i}", 1) for i in range(N_SIBLINGS)]
    first_filler = 3 + N_SIBLINGS
    cats += [
        (first_filler + i, f"filler{i}", 1)
        for i in range(N_CATEGORIES - 2 - N_SIBLINGS)
    ]
    # 10万条内容各自引用 hot；再各补4条填充引用（每内容<=5个分类，<=10）
    refs = [(c, 2) for c in range(1, N_CATEGORIES + 1)]
    refs += [
        (c, first_filler + (c * k) % (N_CATEGORIES - 2 - N_SIBLINGS))
        for k in range(1, 5)
        for c in range(1, N_CATEGORIES + 1)
    ]
    assert len(refs) == N_REFS
    s = CategoryStore(str(db))
    s.initialize(cats, refs)

    # ---- 计时：5000次连续合并 + 1万次查询 ----
    t0 = time.perf_counter()
    for i in range(N_SIBLINGS):
        assert s.merge(2, 3 + i)          # 始终用最早的旧ID 2 发起
    final_live = 3 + N_SIBLINGS - 1
    for q in range(N_QUERIES):
        if q % 2 == 0:
            assert s.get_category(2 + (q % N_SIBLINGS)).id == final_live
        else:
            got = s.get_content_categories(1 + (q % N_CATEGORIES))
            assert final_live in got and len(got) <= 10
    elapsed = time.perf_counter() - t0
    s.close()

    print(f"\n5000 merges + {N_QUERIES} queries: {elapsed:.2f}s "
          f"(budget {TIME_BUDGET}s)")
    assert elapsed < TIME_BUDGET
