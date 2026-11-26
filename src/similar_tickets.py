"""Find past tickets similar to a new one, and suggest the team, the likely fix and the typical time.

This is what an experienced service-desk agent does from memory: "I've seen this before, it was the VPN
profile, Network Team fixed it in a couple of hours." Here the memory is every resolved ticket, searched by
MEANING with the same free AI model as semantic_classifier.py (BGE-small, runs locally, no cost).

How it works:
  1. Every resolved ticket is turned into a meaning-vector (saved, so this is quick after the first run).
  2. A new ticket is turned into a vector the same way.
  3. Cosine similarity finds the closest past tickets (100% = same meaning).
  4. Suggestion: the team that resolved most of the 15 closest tickets (weighted by similarity; 15 lets the
     right team outvote the occasional misrouted ticket), the fix used on the closest match, and the
     typical time of the 5 closest.

Usage (from the project root):
  python src/similar_tickets.py                                  # evaluate, then show 3 examples
  python src/similar_tickets.py "outlook keeps asking for my password"   # any ticket text

Input : data/processed/tickets_with_text.csv, data/processed/opspulse.db
Output: reports/ai/similar_tickets_results.json  (evaluation numbers)
"""
import json
import sqlite3
import sys
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd

from train_classifier import split_new_wording

TICKETS = "data/processed/tickets_with_text.csv"
DB_FILE = "data/processed/opspulse.db"
EMB_CACHE = Path("data/processed/ticket_embeddings.npy")
OUT_FILE = Path("reports/ai/similar_tickets_results.json")
EMBED_MODEL = "BAAI/bge-small-en-v1.5"
K_VOTE = 15  # similar tickets that vote on team and category
K_TIME = 5   # closest tickets used for typical time and SLA

_model = None


def model():
    """Load the AI model only when a NEW text has to be embedded."""
    global _model
    if _model is None:
        from fastembed import TextEmbedding
        _model = TextEmbedding(EMBED_MODEL)
    return _model


def embed(texts):
    v = np.array(list(model().embed(list(texts))), dtype=np.float32)
    return v / np.linalg.norm(v, axis=1, keepdims=True)


def load():
    df = pd.read_csv(TICKETS)
    with sqlite3.connect(DB_FILE) as conn:
        extra = pd.read_sql("SELECT incident_id, resolution_hours, sla_met, assigned_to FROM incidents", conn)
    df = df.merge(extra, on="incident_id", how="left")
    if EMB_CACHE.exists() and len(np.load(EMB_CACHE)) == len(df):
        vecs = np.load(EMB_CACHE)
    else:
        print("Embedding all tickets (first run downloads the model)...")
        vecs = embed(df["description"])
        np.save(EMB_CACHE, vecs)
    return df, vecs


def neighbours(query_vec, index_vecs, k=K_VOTE):
    """Positions and similarities of the k most similar tickets in the index."""
    sims = index_vecs @ query_vec
    top = np.argsort(-sims)[:k]
    return top, sims[top]


def suggest(nb):
    """Turn the similar tickets (a DataFrame with a 'similarity' column) into a suggestion."""
    team_votes = Counter()
    for team, sim in zip(nb["assignment_group"], nb["similarity"]):
        team_votes[team] += sim
    cat_votes = Counter()
    for cat, sim in zip(nb["category"], nb["similarity"]):
        cat_votes[cat] += sim
    best, close = nb.iloc[0], nb.head(K_TIME)
    return {
        "team": team_votes.most_common(1)[0][0],
        "category": cat_votes.most_common(1)[0][0],
        "likely_fix": best["resolution_note"],
        "typical_hours": float(close["resolution_hours"].median()),
        "sla_met_share": float(close["sla_met"].mean()),
        "confidence": float(close["similarity"].mean()),
    }


def evaluate(df, vecs):
    """Search only the training tickets for each unseen-wording test ticket, as for a brand-new ticket."""
    train, test = split_new_wording(df)
    train = train[train["resolution_hours"].notna()]  # only resolved tickets have a fix to learn from
    index_vecs = vecs[train.index]

    rows = []
    for i, t in test.iterrows():
        pos, sims = neighbours(vecs[i], index_vecs)
        nb = train.iloc[pos].assign(similarity=sims)
        s = suggest(nb)
        rows.append({
            "category_ok": s["category"] == t["category"],
            "team_ok": s["team"] == t["correct_group"],
            "top1_same_problem": nb.iloc[0]["subcategory"] == t["subcategory"],
            "fix_applies": nb.iloc[0]["subcategory"] == t["subcategory"],
            "human_routing_ok": t["assignment_group"] == t["correct_group"],
            "misrouted": t["misrouted"] == 1,
            "would_fix_routing": t["misrouted"] == 1 and s["team"] == t["correct_group"],
            "flagged": s["team"] != t["assignment_group"],
            "top1_similarity": float(sims[0]),
        })
    r = pd.DataFrame(rows)
    res = {
        "test_tickets": len(r),
        "searchable_past_tickets": len(train),
        "category_from_similar_tickets": round(r["category_ok"].mean(), 3),
        "closest_ticket_same_problem": round(r["top1_same_problem"].mean(), 3),
        "suggested_team_correct": round(r["team_ok"].mean(), 3),
        "original_human_routing_correct": round(r["human_routing_ok"].mean(), 3),
        "misrouted_tickets": int(r["misrouted"].sum()),
        "misrouted_that_suggestion_fixes": int(r["would_fix_routing"].sum()),
        "disagreements_flagged": int(r["flagged"].sum()),
        "flags_where_suggestion_is_right": round(r.loc[r["flagged"], "team_ok"].mean(), 3),
        "average_top_similarity": round(r["top1_similarity"].mean(), 3),
    }
    return res


def show(text, df, vecs, index_mask):
    """Print a suggestion card for one ticket text."""
    pool = df[index_mask]
    pos, sims = neighbours(embed([text])[0], vecs[pool.index])
    nb = pool.iloc[pos].assign(similarity=sims)
    s = suggest(nb)
    print(f'\nNew ticket: "{text}"')
    print(f"  Suggested team : {s['team']}   (category {s['category']}, confidence {s['confidence']:.0%})")
    print(f"  Likely fix     : {s['likely_fix']}")
    print(f"  Typical time   : {s['typical_hours']:.1f} hours; {s['sla_met_share']:.0%} of similar tickets met SLA")
    print("  Most similar past tickets:")
    for _, r in nb.head(3).iterrows():
        print(f"    {r['similarity']:.0%}  {r['incident_id']}  [{r['priority']} | {r['subcategory']}]  "
              f"{r['description'][:70]}")
        print(f"         fixed by {r['assignment_group']} in {r['resolution_hours']:.1f} h: {r['resolution_note']}")


def main():
    df, vecs = load()
    resolved = df["resolution_hours"].notna()

    if len(sys.argv) > 1:  # suggest for the text given on the command line
        show(" ".join(sys.argv[1:]), df, vecs, resolved)
        return

    res = evaluate(df, vecs)
    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUT_FILE.write_text(json.dumps(res, indent=2))
    print("Evaluation on tickets written in wording the search has never seen:")
    print(f"  Closest past ticket is the same kind of problem : {res['closest_ticket_same_problem']:.1%}"
          f"  (so its fix applies)")
    print(f"  Category from the 15 most similar tickets       : {res['category_from_similar_tickets']:.1%}")
    print(f"  Suggested team is the right team                : {res['suggested_team_correct']:.1%}"
          f"  (original human routing: {res['original_human_routing_correct']:.1%})")
    print(f"  Misrouted tickets the suggestion would correct  : {res['misrouted_that_suggestion_fixes']} of "
          f"{res['misrouted_tickets']}")
    print(f"  When it disagrees with the human routing ({res['disagreements_flagged']} tickets), "
          f"it is right {res['flags_where_suggestion_is_right']:.1%} of the time")
    print(f"Saved: {OUT_FILE}")

    for text in ["Outlook keeps asking me for my password since this morning",
                 "the big printer near HR is jammed and showing an error",
                 "I think I clicked a bad link in an email that looked like it came from our bank"]:
        show(text, df, vecs, resolved)


if __name__ == "__main__":
    main()
