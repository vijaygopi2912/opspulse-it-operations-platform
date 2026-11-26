"""Classify tickets with a free AI model that understands MEANING, not just keywords,
and compare it with the keyword ML model from train_classifier.py.

How it works, in short:
  1. A sentence-embedding model (BGE-small, free and open source, runs on your laptop)
     turns each ticket into 384 numbers that capture what it MEANS. Tickets about the
     same kind of problem end up with similar numbers, even with completely different words:
     "printer jammed" lands close to "can't print anything".
  2. Zero-shot: compare each ticket with a one-line description of each category and pick
     the closest. No training examples at all.
  3. Trained: a classifier learns from the meaning-numbers of the training tickets.
  4. All methods are tested on the SAME unseen-wording test set as the keyword model,
     so the comparison is fair.

First run downloads the model once (about 70 MB) and takes a minute or two.
No account, no API key, no cost.

Setup (once):  pip install fastembed
Input : data/processed/tickets_with_text.csv
Output: models/semantic_classifier.joblib
        data/processed/test_tickets_semantic.csv
        reports/ai/semantic_results.json
        reports/ai/model_comparison.png
Run from the project root:  python src/semantic_classifier.py
"""
import json
from pathlib import Path

import joblib
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from fastembed import TextEmbedding
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, classification_report, f1_score, precision_score, recall_score
from sklearn.pipeline import make_pipeline

from train_classifier import CORRECT_GROUP, split_new_wording

IN_FILE = "data/processed/tickets_with_text.csv"
EMB_CACHE = Path("data/processed/ticket_embeddings.npy")
TEST_OUT = "data/processed/test_tickets_semantic.csv"
MODEL_FILE = Path("models/semantic_classifier.joblib")
OUT_DIR = Path("reports/ai")
EMBED_MODEL = "BAAI/bge-small-en-v1.5"

# One line per category, the way a service-desk routing guide would describe it.
# The zero-shot method only ever sees these descriptions, never a labelled ticket.
CATEGORY_GUIDE = {
    "Network": "Network connectivity problem: VPN, wifi, slow internet, no connection, network ports or switch down",
    "Hardware": "Physical device problem: laptop, printer, monitor or screen, keyboard, docking station, battery",
    "Software": "Software application problem: Excel, Word, Teams, OneDrive, SAP or ERP, web browser, installing software",
    "Access": "User account access problem: password reset, account locked, cannot log in, permission to a folder or system",
    "Email": "Email problem: Outlook, mailbox, sending or receiving emails, spam or junk mail, shared mailbox",
    "Security": "Security threat: phishing email, virus or malware, antivirus alert, suspicious login, compromised account",
}


def embed(model, texts):
    """Turn texts into meaning-vectors, normalised so a dot product = cosine similarity."""
    vecs = np.array(list(model.embed(list(texts))), dtype=np.float32)
    return vecs / np.linalg.norm(vecs, axis=1, keepdims=True)


def load_embeddings(model, df):
    """Embedding 3,000 tickets takes a minute, so save them and reuse them next time."""
    if EMB_CACHE.exists():
        cached = np.load(EMB_CACHE)
        if len(cached) == len(df):
            print(f"Using saved embeddings from {EMB_CACHE}")
            return cached
    print(f"Embedding {len(df)} tickets with {EMBED_MODEL} (first run downloads the model)...")
    vecs = embed(model, df["description"])
    np.save(EMB_CACHE, vecs)
    return vecs


def scores(y_true, y_pred):
    return {"accuracy": round(accuracy_score(y_true, y_pred), 3),
            "macro_f1": round(f1_score(y_true, y_pred, average="macro"), 3)}


def main():
    df = pd.read_csv(IN_FILE)
    train, test = split_new_wording(df)  # exactly the same split as the keyword model
    print(f"Training on {len(train)} tickets, testing on {len(test)} tickets in unseen wording\n")

    model = TextEmbedding(EMBED_MODEL)
    vecs = load_embeddings(model, df)
    X_train, X_test = vecs[train.index], vecs[test.index]

    results = {"category": {}, "priority": {}}

    # 1. Keyword ML (same as train_classifier.py), retrained here so all methods sit side by side
    keyword = make_pipeline(TfidfVectorizer(ngram_range=(1, 2), sublinear_tf=True, min_df=2),
                            LogisticRegression(max_iter=2000, C=5))
    keyword.fit(train["description"], train["category"])
    results["category"]["Keyword ML (TF-IDF)"] = scores(test["category"], keyword.predict(test["description"]))

    # 2. Zero-shot semantic: closest category description, no training tickets used
    names = list(CATEGORY_GUIDE)
    guide_vecs = embed(model, CATEGORY_GUIDE.values())
    zero_shot = np.array(names)[(X_test @ guide_vecs.T).argmax(axis=1)]
    results["category"]["Semantic AI, zero-shot"] = scores(test["category"], zero_shot)

    # 3. Semantic + trained classifier
    cat_clf = LogisticRegression(max_iter=3000, C=10).fit(X_train, train["category"])
    sem_cat = cat_clf.predict(X_test)
    results["category"]["Semantic AI, trained"] = scores(test["category"], sem_cat)

    pri_kw = make_pipeline(TfidfVectorizer(ngram_range=(1, 2), sublinear_tf=True, min_df=2),
                           LogisticRegression(max_iter=2000, C=5)).fit(train["description"], train["priority"])
    results["priority"]["Keyword ML (TF-IDF)"] = scores(test["priority"], pri_kw.predict(test["description"]))
    pri_clf = LogisticRegression(max_iter=3000, C=10).fit(X_train, train["priority"])
    sem_pri = pri_clf.predict(X_test)
    results["priority"]["Semantic AI, trained"] = scores(test["priority"], sem_pri)

    for target in ("category", "priority"):
        print(f"Predicting {target.upper()} (unseen wording)")
        for name, s in results[target].items():
            print(f"  {name:<26} accuracy {s['accuracy']:.1%}   macro F1 {s['macro_f1']:.3f}")
        print()

    # Use whichever semantic method was better for the detailed look
    best_name = max(["Semantic AI, zero-shot", "Semantic AI, trained"],
                    key=lambda n: results["category"][n]["macro_f1"])
    best_cat = zero_shot if best_name == "Semantic AI, zero-shot" else sem_cat
    print(f"Category report ({best_name}):")
    print(classification_report(test["category"], best_cat, digits=3))

    # Misrouting check, same as before
    test = test.copy()
    test["sem_category"] = best_cat
    test["sem_priority"] = sem_pri
    test["sem_group"] = test["sem_category"].map(CORRECT_GROUP)
    flagged = (test["sem_group"] != test["assignment_group"]).astype(int)
    results["routing"] = {
        "tickets_misrouted": int(test["misrouted"].sum()),
        "tickets_flagged": int(flagged.sum()),
        "precision": round(precision_score(test["misrouted"], flagged), 3),
        "recall": round(recall_score(test["misrouted"], flagged), 3),
        "group_accuracy": round(accuracy_score(test["correct_group"], test["sem_group"]), 3),
    }
    r = results["routing"]
    print(f"Misrouting check: correct team for {r['group_accuracy']:.1%} of tickets; "
          f"caught {r['recall']:.1%} of misrouted tickets, {r['precision']:.1%} of flags were right\n")
    results["best_semantic_method"] = best_name
    results["embedding_model"] = EMBED_MODEL

    wrong = test[test["sem_category"] != test["category"]]
    if len(wrong):
        print(f"Examples it still gets wrong ({len(wrong)} of {len(test)}):")
        for _, row in wrong.sample(min(5, len(wrong)), random_state=1).iterrows():
            print(f"  said {row['sem_category']:<9} actual {row['category']:<9} | {row['description'][:85]}")

    # Save
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    MODEL_FILE.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump({"embedding_model": EMBED_MODEL, "category": cat_clf, "priority": pri_clf,
                 "category_guide": CATEGORY_GUIDE}, MODEL_FILE)
    test.to_csv(TEST_OUT, index=False)
    (OUT_DIR / "semantic_results.json").write_text(json.dumps(results, indent=2))

    labels = list(results["category"])
    values = [results["category"][n]["accuracy"] for n in labels]
    fig, ax = plt.subplots(figsize=(7.5, 3.6))
    bars = ax.barh(labels, values, color=["#94A3B8", "#3B82F6", "#1D4ED8"])
    for b, v in zip(bars, values):
        ax.text(v + 0.01, b.get_y() + b.get_height() / 2, f"{v:.0%}", va="center")
    ax.set_xlim(0, 1.08)
    ax.xaxis.set_major_formatter(matplotlib.ticker.PercentFormatter(1.0))
    ax.set_title("Ticket category accuracy on unseen wording (623 test tickets)", loc="left", fontsize=11)
    ax.invert_yaxis()
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    fig.tight_layout()
    fig.savefig(OUT_DIR / "model_comparison.png", dpi=130)
    print(f"\nSaved model to {MODEL_FILE}, results and chart to {OUT_DIR}/")

    print("\nTry it on new tickets:")
    for text in ["My screen goes black every 5 minutes, please help",
                 "URGENT the whole finance team cannot connect to SAP",
                 "got a weird email asking me to reset my password via a link"]:
        v = embed(model, [text])
        cat = cat_clf.predict(v)[0]
        pri = pri_clf.predict(v)[0]
        print(f"  '{text}'\n     -> {cat} / {pri} / send to {CORRECT_GROUP[cat]}")


if __name__ == "__main__":
    main()
