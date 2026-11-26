"""Train a machine-learning model that reads a ticket and predicts its
category and priority, then uses the category to suggest the right team.

How it works, in short:
  1. TF-IDF turns each ticket's text into numbers: words that are common in
     one kind of ticket but rare overall (e.g. "printer", "VPN") get high scores.
  2. A classifier learns which words go with which category / priority.
  3. We test it on tickets it has never seen and measure accuracy.

Two tests:
  - Familiar wording: a random 20% of tickets. The same sentence patterns also appear in
    training, so this mostly measures memory and is too optimistic.
  - New wording (the honest test): for every subcategory, one way of describing the problem
    is held back completely. The model must cope with phrasing it has never seen,
    which is what happens with real tickets.

Three models are compared for each question:
  - Baseline:            always guesses the most common answer (the "do nothing" score to beat)
  - Naive Bayes:         a simple, fast probability model
  - Logistic Regression: a stronger linear model, usually the best for short text

Input : data/processed/tickets_with_text.csv
Output: models/ticket_classifier.joblib        (trained models, reused by later scripts)
        data/processed/test_tickets.csv         (the unseen test set, reused for the Claude comparison)
        reports/ai/ml_results.json               (accuracy numbers)
        reports/ai/ml_confusion_category.png     (where the model gets confused)
Run from the project root:  python src/train_classifier.py
"""
import json
import random
from pathlib import Path

import joblib
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd
from sklearn.dummy import DummyClassifier
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (ConfusionMatrixDisplay, accuracy_score, classification_report,
                             f1_score, precision_score, recall_score)
from sklearn.model_selection import train_test_split
from sklearn.naive_bayes import MultinomialNB
from sklearn.pipeline import make_pipeline

IN_FILE = "data/processed/tickets_with_text.csv"
TEST_FILE = "data/processed/test_tickets.csv"
MODEL_FILE = Path("models/ticket_classifier.joblib")
OUT_DIR = Path("reports/ai")
SEED = 42

CORRECT_GROUP = {
    "Network": "Network Team", "Hardware": "Desktop Support",
    "Software": "Application Support", "Access": "Service Desk",
    "Email": "Service Desk", "Security": "Security Operations",
}


def candidates():
    """The three models we compare. Each one is: text -> TF-IDF numbers -> classifier."""
    def tfidf():
        # word pairs ("account locked") carry more meaning than single words
        return TfidfVectorizer(ngram_range=(1, 2), sublinear_tf=True, min_df=2)
    return {
        "Baseline (most common)": make_pipeline(tfidf(), DummyClassifier(strategy="most_frequent")),
        "Naive Bayes": make_pipeline(tfidf(), MultinomialNB()),
        "Logistic Regression": make_pipeline(tfidf(), LogisticRegression(max_iter=2000, C=5)),
    }


def evaluate(target, train, test):
    """Train every candidate on `target`, return scores and the best model."""
    scores, fitted = {}, {}
    for name, model in candidates().items():
        model.fit(train["description"], train[target])
        pred = model.predict(test["description"])
        scores[name] = {
            "accuracy": round(accuracy_score(test[target], pred), 3),
            "macro_f1": round(f1_score(test[target], pred, average="macro"), 3),
        }
        fitted[name] = model
    best = max(scores, key=lambda n: scores[n]["macro_f1"])
    return scores, best, fitted[best]


def split_new_wording(df):
    """Hold back one sentence pattern per subcategory: those tickets become the test set."""
    rng = random.Random(SEED)
    held = [rng.choice(sorted(t)) for _, t in df.groupby("subcategory")["template_id"].unique().items()]
    is_test = df["template_id"].isin(held)
    return df[~is_test], df[is_test]


def main():
    df = pd.read_csv(IN_FILE)

    # Test 1, familiar wording: random 80/20 split (shown for comparison only)
    tr, te = train_test_split(df, test_size=0.2, random_state=SEED, stratify=df["category"])
    familiar, _, _ = evaluate("category", tr, te)
    best_familiar = max(s["accuracy"] for s in familiar.values())

    # Test 2, new wording: the honest test used for everything below
    train, test = split_new_wording(df)
    print(f"Training on {len(train)} tickets, testing on {len(test)} tickets written in "
          f"sentence patterns the model has never seen\n")

    results, models = {"familiar_wording_category_accuracy": best_familiar}, {}
    for target in ("category", "priority"):
        scores, best, model = evaluate(target, train, test)
        results[target] = {"scores": scores, "best_model": best}
        models[target] = model
        print(f"Predicting {target.upper()}")
        for name, s in scores.items():
            mark = "  <- best" if name == best else ""
            print(f"  {name:<24} accuracy {s['accuracy']:.1%}   macro F1 {s['macro_f1']:.3f}{mark}")
        print()
    print(f"For comparison, with FAMILIAR wording the best category accuracy is {best_familiar:.1%}.")
    print("The gap shows how much the model memorises patterns instead of understanding them.\n")

    # ---- Detailed look at the best category model ------------------------------
    test = test.copy()
    test["ml_category"] = models["category"].predict(test["description"])
    test["ml_priority"] = models["priority"].predict(test["description"])
    test["ml_group"] = test["ml_category"].map(CORRECT_GROUP)
    print("Category report (best model):")
    print(classification_report(test["category"], test["ml_category"], digits=3))

    # ---- Routing check: does the model spot tickets sent to the wrong team? ----
    flagged = (test["ml_group"] != test["assignment_group"]).astype(int)
    routing = {
        "tickets_misrouted": int(test["misrouted"].sum()),
        "tickets_flagged": int(flagged.sum()),
        "precision": round(precision_score(test["misrouted"], flagged), 3),
        "recall": round(recall_score(test["misrouted"], flagged), 3),
        "group_accuracy": round(accuracy_score(test["correct_group"], test["ml_group"]), 3),
    }
    results["routing"] = routing
    print("Misrouting check (model's suggested team vs the team the ticket was sent to):")
    print(f"  Correct team suggested for {routing['group_accuracy']:.1%} of tickets")
    print(f"  {routing['tickets_misrouted']} tickets were really misrouted; the model flagged "
          f"{routing['tickets_flagged']}")
    print(f"  Recall {routing['recall']:.1%} (share of misrouted tickets it caught), "
          f"precision {routing['precision']:.1%} (share of its flags that were right)\n")

    # ---- A few mistakes, to understand where it struggles ----------------------
    wrong = test[test["ml_category"] != test["category"]]
    print(f"Examples of category mistakes ({len(wrong)} of {len(test)}):")
    for _, r in wrong.sample(min(6, len(wrong)), random_state=1).iterrows():
        print(f"  said {r['ml_category']:<9} actual {r['category']:<9} | {r['description'][:90]}")

    # ---- Save everything -------------------------------------------------------
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    MODEL_FILE.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(models, MODEL_FILE)
    test.to_csv(TEST_FILE, index=False)
    (OUT_DIR / "ml_results.json").write_text(json.dumps(results, indent=2))

    fig, ax = plt.subplots(figsize=(7, 6))
    ConfusionMatrixDisplay.from_predictions(test["category"], test["ml_category"], ax=ax,
                                            cmap="Blues", colorbar=False)
    ax.set_title("ML model: actual vs predicted category (test set)")
    plt.xticks(rotation=30, ha="right")
    fig.tight_layout()
    fig.savefig(OUT_DIR / "ml_confusion_category.png", dpi=130)

    print(f"\nSaved model to {MODEL_FILE}")
    print(f"Saved test set with predictions to {TEST_FILE}")
    print(f"Saved results to {OUT_DIR}/")

    # ---- Try it on brand-new tickets --------------------------------------------
    print("\nTry it on new tickets:")
    for text in ["My screen goes black every 5 minutes, please help",
                 "URGENT the whole finance team cannot connect to SAP",
                 "got a weird email asking me to reset my password via a link"]:
        cat = models["category"].predict([text])[0]
        pri = models["priority"].predict([text])[0]
        print(f"  '{text}'\n     -> {cat} / {pri} / send to {CORRECT_GROUP[cat]}")


if __name__ == "__main__":
    main()
