"""One-shot dedup: collapse duplicate influencers sharing (platform, profile_url).

Strategy (per user decision 2026-04-24): for each duplicate group, keep the row
with the most non-null fields (tie-break: smallest id, i.e. earliest), and
merge surviving relations (scrape_task_influencers / emails / notes /
collaborations / influencer_tags) into the kept row before deleting the rest.

Rationale: one YouTube channel often exposes multiple emails (business / info
/ creator); the scraper currently creates one Influencer row per email,
making the same channel appear N times in the "网红数据" list. This script
collapses those, and a follow-up alembic migration adds a partial unique
index on (platform, profile_url) so it never happens again.

Safe to run multiple times — if no duplicates exist it's a no-op.
"""
import sqlite3
import sys
from pathlib import Path

DB_PATH = Path(__file__).resolve().parents[1] / "data" / "influencer.db"


def score_row(row: dict) -> tuple[int, int]:
    """Score by non-null-field count (desc), tie-break by id (asc)."""
    non_null = sum(
        1 for k, v in row.items()
        if k != "id" and v is not None and v != ""
    )
    return (-non_null, row["id"])  # smaller tuple wins in sort


def reassign_relations(cur: sqlite3.Cursor, keep_id: int, drop_ids: list[int]) -> None:
    """Move every FK-referencing row from drop_ids → keep_id, handling unique
    conflicts by dropping the duplicate (we keep whichever reached keep_id first).
    """
    for table, keys in [
        ("scrape_task_influencers", ("scrape_task_id",)),     # composite PK, dedup on (task, influencer)
        ("influencer_tags", ("tag_id",)),                     # uq_influencer_tag(influencer_id, tag_id)
        ("emails", None),                                     # no conflict risk — FK only
        ("notes", None),
        ("collaborations", None),
    ]:
        for drop_id in drop_ids:
            if keys is None:
                cur.execute(
                    f"UPDATE {table} SET influencer_id = ? WHERE influencer_id = ?",
                    (keep_id, drop_id),
                )
                continue
            # Composite-key tables: delete any row that would collide with keep_id
            key_cols = ", ".join(keys)
            cur.execute(
                f"""
                DELETE FROM {table}
                 WHERE influencer_id = ?
                   AND ({key_cols}) IN (
                     SELECT {key_cols} FROM {table} WHERE influencer_id = ?
                   )
                """,
                (drop_id, keep_id),
            )
            cur.execute(
                f"UPDATE {table} SET influencer_id = ? WHERE influencer_id = ?",
                (keep_id, drop_id),
            )


def main() -> int:
    if not DB_PATH.exists():
        print(f"[ERR] DB not found: {DB_PATH}", file=sys.stderr)
        return 1
    print(f"[info] DB: {DB_PATH}")

    con = sqlite3.connect(str(DB_PATH))
    con.row_factory = sqlite3.Row
    cur = con.cursor()

    # Find all (platform, profile_url) groups with duplicates.
    groups = cur.execute(
        """
        SELECT platform, profile_url, COUNT(*) n
          FROM influencers
         WHERE profile_url IS NOT NULL AND profile_url != ''
         GROUP BY platform, profile_url
         HAVING n > 1
         ORDER BY n DESC
        """
    ).fetchall()

    if not groups:
        print("[info] no duplicate (platform, profile_url) groups — nothing to do.")
        con.close()
        return 0

    print(f"[info] found {len(groups)} duplicate group(s):")
    for g in groups:
        print(f"  - {g['platform']} | {g['profile_url']} | count={g['n']}")

    total_deleted = 0
    for g in groups:
        rows = cur.execute(
            """
            SELECT id, email, nickname, profile_url, avatar_url, followers,
                   bio, relevance_score, match_reason, created_at
              FROM influencers
             WHERE platform = ? AND profile_url = ?
             ORDER BY id
            """,
            (g["platform"], g["profile_url"]),
        ).fetchall()
        rows = [dict(r) for r in rows]
        rows.sort(key=score_row)  # best (most fields, smallest id) first
        keep = rows[0]
        drop = rows[1:]
        keep_id = keep["id"]
        drop_ids = [r["id"] for r in drop]
        print(
            f"[plan] {g['platform']}|{g['profile_url']}: keep id={keep_id} "
            f"(non_null={sum(1 for v in keep.values() if v not in (None, ''))-1}), "
            f"drop ids={drop_ids}"
        )

        reassign_relations(cur, keep_id, drop_ids)
        # Now safely delete the losing rows
        placeholders = ",".join("?" * len(drop_ids))
        cur.execute(
            f"DELETE FROM influencers WHERE id IN ({placeholders})",
            drop_ids,
        )
        total_deleted += len(drop_ids)

    con.commit()
    con.close()
    print(f"[done] deleted {total_deleted} duplicate row(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
