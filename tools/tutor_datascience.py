"""Data-science track for the Aria mentor: lessons and deterministic checks.

Checks are AST-based so they are explainable and never guess. They target the
mistakes that most often invalidate a beginner's analysis: leakage, silent
copies, dishonest charts and single-metric evaluation.
"""
from __future__ import annotations

import ast

DS_LESSONS: list[dict] = [
    {
        "id": "ds-1", "language": "datascience", "title": "Thinking like a data scientist",
        "goal": "Turn a vague business question into a question data can answer, and decide what result would change a decision.",
        "starter": (
            "# Business question: \"Why are customers leaving?\"\n"
            "# TODO: rewrite this as a measurable question, name the data you would need,\n"
            "#       and say what result would make the business act.\n"
            "import pandas as pd\n\n"
            "customers = pd.DataFrame({\n"
            "    'tenure_months': [2, 30, 7, 48, 5],\n"
            "    'churned': [1, 0, 1, 0, 1],\n"
            "})\n"
            "print(customers.groupby('churned')['tenure_months'].mean())\n"
        ),
    },
    {
        "id": "ds-2", "language": "datascience", "title": "pandas essentials",
        "goal": "Load, select, filter, sort and group a DataFrame confidently.",
        "starter": (
            "import pandas as pd\n\n"
            "df = pd.DataFrame({\n"
            "    'city': ['Johannesburg', 'Cape Town', 'Durban', 'Johannesburg'],\n"
            "    'plan': ['Pro', 'Free', 'Pro', 'Free'],\n"
            "    'spend': [450.0, 0.0, 450.0, 0.0],\n"
            "})\n"
            "# TODO: total spend per city, sorted from highest to lowest\n"
            "print(df)\n"
        ),
    },
    {
        "id": "ds-3", "language": "datascience", "title": "Cleaning messy data",
        "goal": "Handle missing values, duplicates, wrong types and inconsistent categories without silently changing the meaning.",
        "starter": (
            "import pandas as pd\n\n"
            "df = pd.DataFrame({'age': ['28', 'abc', None, '41'], 'city': ['cape town', 'Cape Town', 'DURBAN', None]})\n"
            "df['age'].fillna(0, inplace=True)\n"
            "df[df['city'] == 'DURBAN']['age'] = 30\n"
            "print(df)\n"
        ),
    },
    {
        "id": "ds-4", "language": "datascience", "title": "Exploratory data analysis",
        "goal": "Summarise distributions, spot outliers and relationships, and write down what you believe before modelling.",
        "starter": (
            "import pandas as pd\n\n"
            "df = pd.DataFrame({'spend': [10, 12, 11, 9, 400], 'visits': [3, 4, 3, 2, 30]})\n"
            "# TODO: describe the data, find the outlier, and compare mean with median\n"
            "print(df.describe())\n"
        ),
    },
    {
        "id": "ds-5", "language": "datascience", "title": "Visualising data honestly",
        "goal": "Pick the right chart, label it properly, and avoid charts that exaggerate differences.",
        "starter": (
            "import matplotlib.pyplot as plt\n\n"
            "plans = ['Free', 'Pro']\n"
            "revenue = [98, 100]\n"
            "plt.bar(plans, revenue)\n"
            "plt.ylim(97, 101)\n"
            "plt.show()\n"
        ),
    },
    {
        "id": "ds-6", "language": "datascience", "title": "Statistics you actually need",
        "goal": "Understand mean vs median, spread, sampling, confidence intervals and what a p-value does and does not say.",
        "starter": (
            "from scipy import stats\n\n"
            "group_a = [12, 15, 14, 10, 13]\n"
            "group_b = [16, 18, 15, 17, 19]\n"
            "# TODO: is B really better than A? Say what you can and cannot conclude from 5 samples each.\n"
            "print(stats.ttest_ind(group_a, group_b))\n"
        ),
    },
    {
        "id": "ds-7", "language": "datascience", "title": "SQL for analysts",
        "goal": "Filter, join and aggregate with SQL, and know when to push work into the database rather than pandas.",
        "starter": (
            "query = \"\"\"\n"
            "SELECT c.city, COUNT(*) AS orders, SUM(o.total) AS revenue\n"
            "FROM orders o\n"
            "JOIN customers c ON c.id = o.customer_id\n"
            "WHERE o.created_at >= '2025-01-01'\n"
            "GROUP BY c.city\n"
            "ORDER BY revenue DESC;\n"
            "\"\"\"\n"
            "# TODO: explain each clause, then add a HAVING filter for cities with fewer than 10 orders\n"
            "print(query)\n"
        ),
    },
    {
        "id": "ds-8", "language": "datascience", "title": "Your first machine-learning model",
        "goal": "Split data properly, fit a baseline classifier, and understand why the test set must stay untouched.",
        "starter": (
            "from sklearn.model_selection import train_test_split\n"
            "from sklearn.preprocessing import StandardScaler\n"
            "from sklearn.linear_model import LogisticRegression\n\n"
            "scaler = StandardScaler()\n"
            "X_scaled = scaler.fit_transform(X)\n"
            "X_train, X_test, y_train, y_test = train_test_split(X_scaled, y, test_size=0.2)\n"
            "model = LogisticRegression().fit(X_train, y_train)\n"
            "print(model.score(X_test, y_test))\n"
        ),
    },
    {
        "id": "ds-9", "language": "datascience", "title": "Evaluating models properly",
        "goal": "Choose metrics that match the cost of mistakes, handle imbalanced classes, and compare against a baseline.",
        "starter": (
            "from sklearn.metrics import accuracy_score\n\n"
            "# 1 in 100 transactions is fraud. The model predicts \"not fraud\" every time.\n"
            "y_true = [0] * 99 + [1]\n"
            "y_pred = [0] * 100\n"
            "print(accuracy_score(y_true, y_pred))\n"
        ),
    },
    {
        "id": "ds-10", "language": "datascience", "title": "Telling the story with data",
        "goal": "Write a short, honest summary for a non-technical decision maker, including limitations and a recommended next step.",
        "starter": (
            "results = {\n"
            "    'churn_rate_free': 0.31,\n"
            "    'churn_rate_pro': 0.12,\n"
            "    'sample_size': 400,\n"
            "}\n"
            "# TODO: write a 4-sentence summary for a manager: finding, evidence, caveat, recommendation.\n"
            "print(results)\n"
        ),
    },
]

_SPLIT_NAMES = {"train_test_split"}
_FITTER_HINTS = ("scal", "impute", "encod", "pca", "vectori", "normal", "transform")
_EVAL_METRICS = {"precision_score", "recall_score", "f1_score", "roc_auc_score", "classification_report", "confusion_matrix", "average_precision_score"}


def _call_name(node: ast.Call) -> str:
    if isinstance(node.func, ast.Name):
        return node.func.id
    if isinstance(node.func, ast.Attribute):
        return node.func.attr
    return ""


def _receiver_name(node: ast.Call) -> str:
    if isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name):
        return node.func.value.id
    return ""


def lint_ds_rules(code: str) -> list[dict]:
    """Data-science-specific checks. Returns [] when the code does not parse."""
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return []

    findings: list[dict] = []

    def add(severity: str, message: str) -> None:
        if not any(f["message"] == message for f in findings):
            findings.append({"severity": severity, "message": message})

    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)]
    split_lines = [c.lineno for c in calls if _call_name(c) in _SPLIT_NAMES]
    metric_names = {_call_name(c) for c in calls} | {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}

    for call in calls:
        name = _call_name(call)
        receiver = _receiver_name(call).lower()
        if any(k.arg == "inplace" and isinstance(k.value, ast.Constant) and k.value.value is True for k in call.keywords):
            add("tip", f"inplace=True on line {call.lineno} rarely saves memory and is being phased out. Assign the result instead: df = df.fillna(...).")
        if name in {"fit_transform", "fit"} and split_lines and call.lineno < min(split_lines) and any(h in receiver for h in _FITTER_HINTS):
            add("warning", f"Data leakage: '{receiver}.{name}' on line {call.lineno} learns from ALL rows before train_test_split. Split first, fit on the training set only, then transform the test set.")
        if name in _SPLIT_NAMES and not any(k.arg == "random_state" for k in call.keywords):
            add("tip", f"train_test_split on line {call.lineno} has no random_state, so results change every run. Set random_state=42 to make it reproducible.")
        if name == "iterrows":
            add("tip", f"iterrows() on line {call.lineno} is slow. Prefer vectorised column operations, or groupby/merge.")
        if name == "append" and receiver.startswith("df"):
            add("warning", f"DataFrame.append on line {call.lineno} was removed in pandas 2.0. Use pd.concat([...]).")
        if name in {"ylim", "set_ylim"} and call.args and isinstance(call.args[0], ast.Constant) and isinstance(call.args[0].value, (int, float)) and call.args[0].value > 0:
            if "bar" in {_call_name(c) for c in calls} or "barh" in {_call_name(c) for c in calls}:
                add("warning", f"The y-axis on line {call.lineno} starts at {call.args[0].value}, not 0. On a bar chart that exaggerates small differences.")

    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Subscript) and isinstance(target.value, ast.Subscript):
                    add("warning", f"Chained assignment on line {node.lineno} may modify a copy and silently do nothing. Use df.loc[mask, 'column'] = value.")
        if isinstance(node, ast.ImportFrom) and any(a.name == "*" for a in node.names):
            add("tip", f"'from {node.module} import *' on line {node.lineno} hides where names come from. Import only what you use.")

    if "accuracy_score" in metric_names and not (metric_names & _EVAL_METRICS):
        add("tip", "Accuracy alone can look great on imbalanced data. Also check precision, recall or F1, and compare against a do-nothing baseline.")
    return findings
