"""Document classification (keyword rules + a small scikit-learn model) and workflow planning."""
from __future__ import annotations

import re

LABELS = ("invoice", "purchase_order", "goods_receipt", "vendor_record")

KEYWORDS = {
    "invoice": [r"\binvoice\b", r"grand total", r"subtotal", r"due date", r"tax total", r"bank:"],
    "purchase_order": [r"purchase order", r"\border date\b", r"unit price", r"vendor code"],
    "goods_receipt": [r"goods received", r"qty received", r"receipt date", r"\bgrn\b", r"po reference"],
    "vendor_record": [r"vendor master", r"verification status", r"vendor name", r"bank account"],
}
_TITLE = {"invoice": r"^\s*invoice\b", "purchase_order": r"^\s*purchase order\b",
          "goods_receipt": r"^\s*goods received", "vendor_record": r"^\s*vendor master"}


def classify_by_rules(text: str) -> tuple[str, float, dict]:
    """Return (label, confidence 0..1, scores). A title line is a strong signal."""
    t = text.lower()
    scores = {}
    for label, pats in KEYWORDS.items():
        hits = sum(1 for p in pats if re.search(p, t))
        scores[label] = hits / len(pats) + (1.0 if re.search(_TITLE[label], t, re.M) else 0.0)
    best = max(scores, key=scores.get)
    ordered = sorted(scores.values(), reverse=True)
    total = sum(scores.values())
    if ordered[0] < 0.3 or total == 0:
        return "unknown", 0.0, scores
    margin = ordered[0] - ordered[1]
    return best, round(min(1.0, 0.5 + margin / 2 + ordered[0] / 4), 3), scores


def training_texts(seed: int = 7, per_class: int = 120):
    """Synthetic labelled documents rendered from the generator (no external data)."""
    from backend.services.doc_text import grn_lines_text, invoice_lines_text, po_lines_text, vendor_lines_text
    from scripts.generate_data import build_dataset
    ds = build_dataset(seed)
    pools = {"invoice": [invoice_lines_text(i) for i in ds["invoices"]], "purchase_order": [po_lines_text(p) for p in ds["purchase_orders"]],
             "goods_receipt": [grn_lines_text(g) for g in ds["goods_receipts"]], "vendor_record": [vendor_lines_text(v) for v in ds["vendors"]]}
    X, y = [], []
    for label, docs in pools.items():
        for d in docs[:per_class]:
            X.append("\n".join(d))
            y.append(label)
    return X, y


def train_model(seed: int = 7):
    """TF-IDF + logistic regression. Returns None when scikit-learn is not installed."""
    try:
        from sklearn.feature_extraction.text import TfidfVectorizer
        from sklearn.linear_model import LogisticRegression
        from sklearn.pipeline import make_pipeline
    except ImportError:
        return None
    X, y = training_texts(seed)
    model = make_pipeline(TfidfVectorizer(ngram_range=(1, 2), min_df=2, lowercase=True), LogisticRegression(max_iter=500, random_state=seed))
    model.fit(X, y)
    return model


_MODEL = None


def classify(text: str, model="auto", ml_threshold: float = 0.70) -> dict:
    """ML first when confident, else keyword rules (the documented fallback), else 'unknown'."""
    global _MODEL
    rule_label, rule_conf, scores = classify_by_rules(text)
    result = {"label": rule_label, "confidence": rule_conf, "method": "rules", "rule_scores": scores}
    if model == "auto":
        if _MODEL is None:
            _MODEL = train_model() or False
        model = _MODEL or None
    if model is not None and text.strip():
        probs = model.predict_proba([text])[0]
        idx = int(probs.argmax())
        if probs[idx] >= ml_threshold:
            return {**result, "label": str(model.classes_[idx]), "confidence": round(float(probs[idx]), 3), "method": "sklearn_tfidf_logreg"}
    if rule_conf < 0.5:
        result.update(label="unknown", method="rules_low_confidence")
    return result


def make_plan(doc_type: str, is_scanned: bool, has_po: bool, has_grn: bool) -> list[str]:
    """Deterministic workflow plan for the document (LangGraph planning node uses this)."""
    steps = ["validate_upload", "ocr" if is_scanned else "read_text_layer"]
    if doc_type == "invoice":
        steps += ["extract_fields", "validate_schema", "arithmetic_checks", "two_way_match" if has_po else "flag_missing_po"]
        steps += ["three_way_match" if has_grn else "flag_missing_grn", "duplicate_check", "create_exceptions",
                  "explain_findings", "verify_explanation", "human_review", "audit_summary"]
    elif doc_type in ("purchase_order", "goods_receipt", "vendor_record"):
        steps += ["extract_fields", "validate_schema", "store_record", "audit_summary"]
    else:
        steps += ["manual_classification"]
    return steps
