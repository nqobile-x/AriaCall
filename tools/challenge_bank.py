"""Challenge bank for the interview / practice mode. Pure data, no API needed.

Types
- code (python, datascience): graded by running `tests` against the learner's code.
  The tests run in the LEARNER'S BROWSER (Pyodide), never on the server.
- rubric (java, spring): graded by static pattern checks; code is never executed.
- mcq: multiple choice, graded server-side.

`solution`, `answer` and `rubric` never leave the server until the learner submits or gives up.
"""
from __future__ import annotations

EASY, MEDIUM, HARD = "easy", "medium", "hard"
POINTS = {EASY: 10, MEDIUM: 20, HARD: 30}
LESSON_LINKS = {
    "python": "python-1", "datascience": "ds-3", "java": "java-1", "spring": "spring-3",
}


def check(cid: str, desc: str, pattern: str, fix: str, must: bool = True) -> dict:
    return {"id": cid, "description": desc, "pattern": pattern, "fix": fix, "must": must}


CHALLENGES: list[dict] = [
    # ── PYTHON ────────────────────────────────────────────────────────────────
    {
        "id": "py-1", "track": "python", "type": "code", "difficulty": EASY, "title": "Palindrome check",
        "prompt": "Write `is_palindrome(text)` that returns True if the text reads the same forwards and backwards, ignoring case, spaces and punctuation.",
        "starter": "def is_palindrome(text):\n    # TODO\n    pass\n",
        "hints": ["Keep only letters and digits first (str.isalnum).", "Lower-case everything, then compare the list with its reverse ([::-1])."],
        "explanation": "Normalise the input (drop non-alphanumerics, lower-case), then compare it with its reverse. It runs in O(n) time.",
        "solution": "def is_palindrome(text):\n    cleaned = [c.lower() for c in text if c.isalnum()]\n    return cleaned == cleaned[::-1]\n",
        "tests": r'''
def test_simple(ns):
    """Recognises a plain palindrome"""
    assert ns["is_palindrome"]("level") is True, "level should be a palindrome"

def test_ignores_case_and_punctuation(ns):
    """Ignores case, spaces and punctuation"""
    assert ns["is_palindrome"]("A man, a plan, a canal: Panama") is True, "punctuation and case must be ignored"

def test_negative(ns):
    """Rejects non-palindromes"""
    assert ns["is_palindrome"]("python") is False, "python is not a palindrome"

def test_empty(ns):
    """Handles the empty string"""
    assert ns["is_palindrome"]("") is True, "an empty string reads the same both ways"
''',
    },
    {
        "id": "py-2", "track": "python", "type": "code", "difficulty": EASY, "title": "Two sum",
        "prompt": "Write `two_sum(nums, target)` returning a tuple `(i, j)` with `i < j` of two different positions whose values add up to `target`, or `None` if there are none.",
        "starter": "def two_sum(nums, target):\n    # TODO\n    pass\n",
        "hints": ["A nested loop works but is O(n^2).", "Remember each number's index in a dict; for every n look up target - n."],
        "explanation": "One pass with a dictionary of value -> index gives O(n) time and O(n) memory, instead of O(n^2) for two loops.",
        "solution": "def two_sum(nums, target):\n    seen = {}\n    for i, n in enumerate(nums):\n        if target - n in seen:\n            return (seen[target - n], i)\n        seen[n] = i\n    return None\n",
        "tests": r'''
def test_basic(ns):
    """Finds the pair in a simple list"""
    assert ns["two_sum"]([2, 7, 11, 15], 9) == (0, 1), "expected (0, 1)"

def test_not_first_elements(ns):
    """Finds a pair that is not at the start"""
    assert ns["two_sum"]([3, 2, 4], 6) == (1, 2), "expected (1, 2)"

def test_duplicates(ns):
    """Handles duplicate values"""
    assert ns["two_sum"]([3, 3], 6) == (0, 1), "expected (0, 1)"

def test_none(ns):
    """Returns None when there is no pair"""
    assert ns["two_sum"]([1, 2, 3], 100) is None, "expected None"

def test_same_element_twice(ns):
    """Does not use one element twice"""
    assert ns["two_sum"]([5], 10) is None, "a single 5 cannot be used twice"
''',
    },
    {
        "id": "py-3", "track": "python", "type": "code", "difficulty": EASY, "title": "Word count",
        "prompt": "Write `word_count(text)` returning a dict of lower-case word -> number of times it appears. Words are runs of letters; ignore punctuation and case.",
        "starter": "def word_count(text):\n    # TODO\n    pass\n",
        "hints": ["Lower-case the text and pull out words with re.findall(r'[a-z]+', ...).", "collections.Counter counts for you; wrap it in dict()."],
        "explanation": "Normalise, tokenise with a regular expression, then count with Counter (or a dict with .get).",
        "solution": "import re\nfrom collections import Counter\n\ndef word_count(text):\n    return dict(Counter(re.findall(r'[a-z]+', text.lower())))\n",
        "tests": r'''
def test_basic(ns):
    """Counts repeated words"""
    assert ns["word_count"]("the cat and the hat") == {"the": 2, "cat": 1, "and": 1, "hat": 1}, "check the counts"

def test_case_and_punctuation(ns):
    """Ignores case and punctuation"""
    assert ns["word_count"]("Hello, hello! HELLO.") == {"hello": 3}, "case and punctuation must be ignored"

def test_empty(ns):
    """Returns an empty dict for empty text"""
    assert ns["word_count"]("") == {}, "expected {}"
''',
    },
    {
        "id": "py-4", "track": "python", "type": "code", "difficulty": MEDIUM, "title": "Flatten nested lists",
        "prompt": "Write `flatten(nested)` that turns arbitrarily nested lists into one flat list, keeping order. Strings must stay whole. Do not change the input.",
        "starter": "def flatten(nested):\n    # TODO\n    pass\n",
        "hints": ["Recursion fits: if an item is a list, flatten it, otherwise keep it.", "Check isinstance(item, list) so strings are not split into characters."],
        "explanation": "Recurse into lists and append everything else. Checking for `list` (not any iterable) prevents strings from being split into characters.",
        "solution": "def flatten(nested):\n    out = []\n    for item in nested:\n        if isinstance(item, list):\n            out.extend(flatten(item))\n        else:\n            out.append(item)\n    return out\n",
        "tests": r'''
def test_flat(ns):
    """Leaves a flat list alone"""
    assert ns["flatten"]([1, 2, 3]) == [1, 2, 3], "a flat list should be unchanged"

def test_nested(ns):
    """Flattens several levels"""
    assert ns["flatten"]([1, [2, [3, [4]], 5]]) == [1, 2, 3, 4, 5], "expected [1, 2, 3, 4, 5]"

def test_strings_stay_whole(ns):
    """Keeps strings whole"""
    assert ns["flatten"](["ab", ["cd"]]) == ["ab", "cd"], "strings must not be split"

def test_empty_lists(ns):
    """Handles empty lists"""
    assert ns["flatten"]([[], [[]], []]) == [], "expected []"

def test_no_mutation(ns):
    """Does not modify its input"""
    data = [1, [2, [3]]]
    ns["flatten"](data)
    assert data == [1, [2, [3]]], "the input list was changed"
''',
    },
    {
        "id": "py-5", "track": "python", "type": "code", "difficulty": MEDIUM, "title": "Group anagrams",
        "prompt": "Write `group_anagrams(words)` returning a list of lists, where each inner list holds words that are anagrams of each other. Group and word order do not matter.",
        "starter": "def group_anagrams(words):\n    # TODO\n    pass\n",
        "hints": ["Anagrams share the same sorted letters.", "Use the sorted letters as a dict key: groups[key].append(word)."],
        "explanation": "Sorting the letters gives a canonical key shared by all anagrams, so one pass builds the groups in O(n * k log k).",
        "solution": "def group_anagrams(words):\n    groups = {}\n    for w in words:\n        groups.setdefault(''.join(sorted(w)), []).append(w)\n    return list(groups.values())\n",
        "tests": r'''
def _norm(result):
    return sorted(tuple(sorted(g)) for g in result)

def test_basic(ns):
    """Groups classic anagrams"""
    got = _norm(ns["group_anagrams"](["eat", "tea", "tan", "ate", "nat", "bat"]))
    assert got == [("ate", "eat", "tea"), ("bat",), ("nat", "tan")], "groups are wrong"

def test_empty(ns):
    """Handles an empty list"""
    assert ns["group_anagrams"]([]) == [], "expected []"

def test_single(ns):
    """Keeps a single word in its own group"""
    assert _norm(ns["group_anagrams"](["a"])) == [("a",)], "expected one group"
''',
    },
    {
        "id": "py-6", "track": "python", "type": "code", "difficulty": MEDIUM, "title": "Fix the bug: keep the order",
        "prompt": "`unique(items)` should remove duplicates but keep the original order. The version below loses the order. Fix it.",
        "starter": "def unique(items):\n    # BUG: a set does not remember order\n    return list(set(items))\n",
        "hints": ["Sets are unordered.", "dict.fromkeys(items) keeps first-seen order (dicts preserve insertion order)."],
        "explanation": "Since Python 3.7 dicts preserve insertion order, so `list(dict.fromkeys(items))` removes duplicates in O(n) and keeps the first occurrence of each item.",
        "solution": "def unique(items):\n    return list(dict.fromkeys(items))\n",
        "tests": r'''
def test_order(ns):
    """Keeps first-seen order"""
    assert ns["unique"]([3, 1, 3, 2, 1]) == [3, 1, 2], "order must be [3, 1, 2]"

def test_strings(ns):
    """Works with strings"""
    assert ns["unique"](["b", "a", "b"]) == ["b", "a"], "expected ['b', 'a']"

def test_empty(ns):
    """Handles an empty list"""
    assert ns["unique"]([]) == [], "expected []"
''',
    },
    {
        "id": "py-7", "track": "python", "type": "code", "difficulty": HARD, "title": "LRU cache",
        "prompt": "Implement `class LRUCache` with `__init__(self, capacity)`, `get(key)` (returns -1 if missing) and `put(key, value)`. When full, `put` evicts the least recently used key. Both `get` and `put` count as a use.",
        "starter": "class LRUCache:\n    def __init__(self, capacity):\n        # TODO\n        pass\n\n    def get(self, key):\n        # TODO\n        pass\n\n    def put(self, key, value):\n        # TODO\n        pass\n",
        "hints": ["collections.OrderedDict remembers order and has move_to_end().", "On every get/put move the key to the end; when over capacity, popitem(last=False)."],
        "explanation": "An OrderedDict gives O(1) get and put: move_to_end marks a key as most recent and popitem(last=False) removes the oldest.",
        "solution": "from collections import OrderedDict\n\nclass LRUCache:\n    def __init__(self, capacity):\n        self.capacity = capacity\n        self.data = OrderedDict()\n\n    def get(self, key):\n        if key not in self.data:\n            return -1\n        self.data.move_to_end(key)\n        return self.data[key]\n\n    def put(self, key, value):\n        self.data[key] = value\n        self.data.move_to_end(key)\n        if len(self.data) > self.capacity:\n            self.data.popitem(last=False)\n",
        "tests": r'''
def test_get_missing(ns):
    """Returns -1 for a missing key"""
    assert ns["LRUCache"](2).get(1) == -1, "missing keys return -1"

def test_put_get(ns):
    """Stores and returns values"""
    c = ns["LRUCache"](2)
    c.put(1, "a")
    assert c.get(1) == "a", "expected 'a'"

def test_evicts_oldest(ns):
    """Evicts the least recently used key"""
    c = ns["LRUCache"](2)
    c.put(1, 1); c.put(2, 2); c.put(3, 3)
    assert c.get(1) == -1 and c.get(2) == 2 and c.get(3) == 3, "key 1 should have been evicted"

def test_get_refreshes(ns):
    """A get counts as a use"""
    c = ns["LRUCache"](2)
    c.put(1, 1); c.put(2, 2)
    c.get(1)
    c.put(3, 3)
    assert c.get(2) == -1 and c.get(1) == 1, "key 2 (not 1) should be evicted after get(1)"

def test_update_existing(ns):
    """Updating a key does not grow the cache"""
    c = ns["LRUCache"](2)
    c.put(1, 1); c.put(1, 10); c.put(2, 2)
    assert c.get(1) == 10 and c.get(2) == 2, "updating must not evict anything"
''',
    },
    {
        "id": "py-8", "track": "python", "type": "code", "difficulty": HARD, "title": "Merge intervals",
        "prompt": "Write `merge_intervals(intervals)` taking a list of `[start, end]` pairs (any order) and returning the merged list sorted by start. Intervals that overlap or touch (e.g. [1,4] and [4,5]) merge. Do not change the input.",
        "starter": "def merge_intervals(intervals):\n    # TODO\n    pass\n",
        "hints": ["Sort by start first.", "Walk through; if the next start <= the last merged end, extend the end with max(...)."],
        "explanation": "After sorting by start, one pass either extends the last merged interval or starts a new one: O(n log n).",
        "solution": "def merge_intervals(intervals):\n    merged = []\n    for start, end in sorted(intervals):\n        if merged and start <= merged[-1][1]:\n            merged[-1][1] = max(merged[-1][1], end)\n        else:\n            merged.append([start, end])\n    return merged\n",
        "tests": r'''
def test_basic(ns):
    """Merges overlapping intervals"""
    assert ns["merge_intervals"]([[1, 3], [2, 6], [8, 10]]) == [[1, 6], [8, 10]], "expected [[1, 6], [8, 10]]"

def test_touching(ns):
    """Merges intervals that touch"""
    assert ns["merge_intervals"]([[1, 4], [4, 5]]) == [[1, 5]], "touching intervals should merge"

def test_unsorted(ns):
    """Handles unsorted input"""
    assert ns["merge_intervals"]([[8, 10], [1, 3], [2, 6]]) == [[1, 6], [8, 10]], "sort by start first"

def test_contained(ns):
    """Handles an interval inside another"""
    assert ns["merge_intervals"]([[1, 10], [2, 3]]) == [[1, 10]], "expected [[1, 10]]"

def test_empty(ns):
    """Handles empty input"""
    assert ns["merge_intervals"]([]) == [], "expected []"

def test_no_mutation(ns):
    """Does not modify its input"""
    data = [[2, 3], [1, 2]]
    ns["merge_intervals"](data)
    assert data == [[2, 3], [1, 2]], "the input was changed"
''',
    },
    {
        "id": "py-9", "track": "python", "type": "mcq", "difficulty": EASY, "title": "The mutable default",
        "prompt": "What does this print?\n\ndef add(x, items=[]):\n    items.append(x)\n    return items\n\nprint(add(1))\nprint(add(2))",
        "options": ["[1] then [2]", "[1] then [1, 2]", "[1] then an error", "[1, 2] then [1, 2]"],
        "answer": 1, "hints": ["When is a default value created: at each call, or once?"],
        "explanation": "Default values are evaluated once, when the function is defined, so the same list is shared between calls. Use `items=None` and create a new list inside the function.",
    },
    {
        "id": "py-10", "track": "python", "type": "mcq", "difficulty": EASY, "title": "is vs ==",
        "prompt": "a = [1, 2]\nb = [1, 2]\nWhat are `a == b` and `a is b`?",
        "options": ["True, True", "True, False", "False, True", "False, False"],
        "answer": 1, "hints": ["One compares values, the other compares identity (the same object)."],
        "explanation": "`==` compares values (equal lists), `is` checks whether both names point to the same object (two separate lists). Use `is` only for None/True/False.",
    },
    {
        "id": "py-11", "track": "python", "type": "mcq", "difficulty": MEDIUM, "title": "Membership speed",
        "prompt": "You check `x in collection` inside a loop over 1,000,000 items. Which collection makes each check fastest on average?",
        "options": ["list", "tuple", "set", "string of items joined together"],
        "answer": 2, "hints": ["Think hash tables."],
        "explanation": "A set uses hashing, so membership is O(1) on average. A list or tuple scans every element (O(n)).",
    },

    # ── DATA SCIENCE ──────────────────────────────────────────────────────────
    {
        "id": "dc-1", "track": "datascience", "type": "code", "difficulty": EASY, "title": "Top N rows",
        "packages": ["pandas"],
        "prompt": "Write `top_n(df, column, n)` returning the `n` rows with the largest values in `column`, largest first, with the index reset to 0..n-1.",
        "starter": "import pandas as pd\n\ndef top_n(df, column, n):\n    # TODO\n    pass\n",
        "hints": ["DataFrame.nlargest(n, column) does the selecting and sorting.", "Finish with .reset_index(drop=True)."],
        "explanation": "`nlargest` is clearer and faster than sorting the whole frame. `reset_index(drop=True)` gives a clean 0..n-1 index.",
        "solution": "import pandas as pd\n\ndef top_n(df, column, n):\n    return df.nlargest(n, column).reset_index(drop=True)\n",
        "tests": r'''
import pandas as pd

def _df():
    return pd.DataFrame({"name": ["a", "b", "c", "d"], "score": [10, 40, 30, 20]})

def test_order(ns):
    """Returns the largest values first"""
    out = ns["top_n"](_df(), "score", 2)
    assert out["score"].tolist() == [40, 30], "expected scores [40, 30]"

def test_index_reset(ns):
    """Resets the index"""
    out = ns["top_n"](_df(), "score", 2)
    assert out.index.tolist() == [0, 1], "the index should be 0..n-1"

def test_keeps_columns(ns):
    """Keeps the other columns"""
    out = ns["top_n"](_df(), "score", 1)
    assert out["name"].tolist() == ["b"], "the name column should travel with the row"

def test_n_bigger_than_rows(ns):
    """Copes with n larger than the data"""
    assert len(ns["top_n"](_df(), "score", 10)) == 4, "should return all 4 rows"
''',
    },
    {
        "id": "dc-2", "track": "datascience", "type": "code", "difficulty": EASY, "title": "Fill missing with the median",
        "packages": ["pandas"],
        "prompt": "Write `fill_with_median(df, column)` returning a NEW DataFrame where missing values in `column` are replaced by that column's median. The original must not change.",
        "starter": "import pandas as pd\n\ndef fill_with_median(df, column):\n    # TODO\n    pass\n",
        "hints": ["Copy first: out = df.copy().", "out[column].fillna(out[column].median())."],
        "explanation": "The median is robust to outliers. Copying first avoids surprising callers by mutating their data.",
        "solution": "import pandas as pd\n\ndef fill_with_median(df, column):\n    out = df.copy()\n    out[column] = out[column].fillna(out[column].median())\n    return out\n",
        "tests": r'''
import pandas as pd

def _df():
    return pd.DataFrame({"x": [1.0, None, 3.0, 100.0], "y": ["a", "b", "c", "d"]})

def test_filled_with_median(ns):
    """Fills gaps with the median (not the mean)"""
    out = ns["fill_with_median"](_df(), "x")
    assert out["x"].tolist() == [1.0, 3.0, 3.0, 100.0], "the median of [1, 3, 100] is 3"

def test_original_untouched(ns):
    """Does not change the original DataFrame"""
    df = _df()
    ns["fill_with_median"](df, "x")
    assert df["x"].isna().sum() == 1, "the original DataFrame was modified"

def test_other_columns(ns):
    """Leaves other columns alone"""
    out = ns["fill_with_median"](_df(), "x")
    assert out["y"].tolist() == ["a", "b", "c", "d"], "other columns must be unchanged"
''',
    },
    {
        "id": "dc-3", "track": "datascience", "type": "code", "difficulty": EASY, "title": "Revenue by city",
        "packages": ["pandas"],
        "prompt": "Write `revenue_by_city(df)` returning a dict of city -> total `revenue`, ordered from the highest total to the lowest.",
        "starter": "import pandas as pd\n\ndef revenue_by_city(df):\n    # TODO\n    pass\n",
        "hints": ["groupby('city')['revenue'].sum()", "sort_values(ascending=False).to_dict() keeps that order."],
        "explanation": "Group, aggregate, sort, then convert. Python dicts keep insertion order, so the sorted order survives `to_dict()`.",
        "solution": "import pandas as pd\n\ndef revenue_by_city(df):\n    return df.groupby('city')['revenue'].sum().sort_values(ascending=False).to_dict()\n",
        "tests": r'''
import pandas as pd

def _df():
    return pd.DataFrame({"city": ["JHB", "CPT", "JHB", "DBN", "CPT"], "revenue": [100, 50, 200, 400, 25]})

def test_totals(ns):
    """Adds up revenue per city"""
    assert dict(ns["revenue_by_city"](_df())) == {"DBN": 400, "JHB": 300, "CPT": 75}, "check the totals"

def test_order(ns):
    """Orders from highest to lowest"""
    assert list(ns["revenue_by_city"](_df()).keys()) == ["DBN", "JHB", "CPT"], "order must be DBN, JHB, CPT"
''',
    },
    {
        "id": "dc-4", "track": "datascience", "type": "code", "difficulty": MEDIUM, "title": "Clean the age column",
        "packages": ["pandas"],
        "prompt": "Write `clean_ages(df)` returning a copy where the `age` column is numeric. Anything that is not a number, or is not between 1 and 120, becomes NaN.",
        "starter": "import pandas as pd\n\ndef clean_ages(df):\n    # TODO\n    pass\n",
        "hints": ["pd.to_numeric(..., errors='coerce') turns junk into NaN.", "Series.where(condition) keeps values where the condition is True and sets the rest to NaN."],
        "explanation": "Coerce first, then validate the range. Blanking impossible values (instead of guessing) keeps the data honest and auditable.",
        "solution": "import pandas as pd\n\ndef clean_ages(df):\n    out = df.copy()\n    ages = pd.to_numeric(out['age'], errors='coerce')\n    out['age'] = ages.where((ages >= 1) & (ages <= 120))\n    return out\n",
        "tests": r'''
import pandas as pd

def _df():
    return pd.DataFrame({"age": ["28", "abc", None, "-1", "200", "41", "0"], "id": range(7)})

def test_values(ns):
    """Keeps valid ages and blanks the rest"""
    out = ns["clean_ages"](_df())["age"].tolist()
    expected = [28.0, None, None, None, None, 41.0, None]
    for got, want in zip(out, expected):
        if want is None:
            assert pd.isna(got), f"expected a missing value but got {got}"
        else:
            assert got == want, f"expected {want} but got {got}"

def test_numeric_dtype(ns):
    """Returns a numeric column"""
    assert pd.api.types.is_numeric_dtype(ns["clean_ages"](_df())["age"]), "age must be numeric"

def test_original_untouched(ns):
    """Does not change the original"""
    df = _df()
    ns["clean_ages"](df)
    assert df["age"].tolist()[1] == "abc", "the original DataFrame was modified"

def test_other_columns(ns):
    """Leaves other columns alone"""
    assert ns["clean_ages"](_df())["id"].tolist() == list(range(7)), "the id column changed"
''',
    },
    {
        "id": "dc-5", "track": "datascience", "type": "code", "difficulty": MEDIUM, "title": "Reproducible train/test split",
        "packages": ["numpy"],
        "prompt": "Write `split_indices(n, test_ratio, seed)` returning `(train_idx, test_idx)` as two Python lists of row numbers 0..n-1. The test set has `round(n * test_ratio)` rows, the sets must not overlap, together they cover every row, and the same seed must give the same split.",
        "starter": "import numpy as np\n\ndef split_indices(n, test_ratio, seed):\n    # TODO\n    pass\n",
        "hints": ["Shuffle the row numbers with a seeded generator: np.random.default_rng(seed).permutation(n).", "Take the first round(n * test_ratio) shuffled numbers as the test set; the rest are training."],
        "explanation": "Seeding the shuffle makes the split reproducible. Disjoint sets with full coverage prevent leakage, the mistake of evaluating on data the model has seen.",
        "solution": "import numpy as np\n\ndef split_indices(n, test_ratio, seed):\n    order = np.random.default_rng(seed).permutation(n).tolist()\n    k = round(n * test_ratio)\n    return order[k:], order[:k]\n",
        "tests": r'''
def test_sizes(ns):
    """Test set has round(n * ratio) rows"""
    train, test = ns["split_indices"](10, 0.2, 1)
    assert len(test) == 2 and len(train) == 8, "expected 8 train and 2 test rows"

def test_disjoint_and_complete(ns):
    """No overlap and every row is used"""
    train, test = ns["split_indices"](100, 0.3, 7)
    assert not (set(train) & set(test)), "train and test overlap (data leakage)"
    assert sorted(list(train) + list(test)) == list(range(100)), "every row must appear exactly once"

def test_reproducible(ns):
    """Same seed gives the same split"""
    assert ns["split_indices"](50, 0.1, 42) == ns["split_indices"](50, 0.1, 42), "the same seed must give the same split"

def test_seed_matters(ns):
    """A different seed gives a different split"""
    assert ns["split_indices"](100, 0.3, 1) != ns["split_indices"](100, 0.3, 2), "different seeds should shuffle differently"

def test_plain_lists(ns):
    """Returns plain Python ints in lists"""
    train, test = ns["split_indices"](10, 0.2, 1)
    assert isinstance(train, list) and isinstance(test, list), "return lists"
    assert all(isinstance(i, int) for i in train + test), "row numbers should be Python ints (use .tolist())"
''',
    },
    {
        "id": "dc-6", "track": "datascience", "type": "code", "difficulty": MEDIUM, "title": "Z-score outliers",
        "prompt": "Write `zscore_outliers(values, threshold=3.0)` returning a list of booleans, True where a value's absolute z-score is greater than `threshold`. Use the population standard deviation. If every value is identical (std 0), nothing is an outlier.",
        "starter": "def zscore_outliers(values, threshold=3.0):\n    # TODO\n    pass\n",
        "hints": ["statistics.mean and statistics.pstdev give the mean and population std.", "Guard against a standard deviation of 0 before dividing."],
        "explanation": "z = (x - mean) / std measures how many standard deviations a value is from the mean. Guarding std == 0 avoids a division error on constant data.",
        "solution": "from statistics import mean, pstdev\n\ndef zscore_outliers(values, threshold=3.0):\n    m, s = mean(values), pstdev(values)\n    if s == 0:\n        return [False] * len(values)\n    return [abs((v - m) / s) > threshold for v in values]\n",
        "tests": r'''
def test_flags_the_big_one(ns):
    """Flags only the extreme value"""
    data = [10] * 20 + [1000]
    assert ns["zscore_outliers"](data) == [False] * 20 + [True], "only the last value is an outlier"

def test_constant(ns):
    """No outliers when all values are equal"""
    assert ns["zscore_outliers"]([5, 5, 5]) == [False, False, False], "a constant list has no outliers"

def test_threshold(ns):
    """Respects the threshold"""
    data = [1, 2, 3, 4, 100]
    assert ns["zscore_outliers"](data, 1.5) == [False, False, False, False, True], "100 has z = 2.0"
    assert ns["zscore_outliers"](data, 3.0) == [False] * 5, "nothing exceeds z = 3 here"

def test_returns_bools(ns):
    """Returns real booleans"""
    assert all(isinstance(x, bool) for x in ns["zscore_outliers"]([1, 2, 3])), "return Python bools"
''',
    },
    {
        "id": "dc-7", "track": "datascience", "type": "code", "difficulty": HARD, "title": "Precision and recall",
        "prompt": "Write `precision_recall(y_true, y_pred)` for a binary problem (1 = positive) returning `(precision, recall)`. If there are no predicted positives precision is 0.0; if there are no actual positives recall is 0.0.",
        "starter": "def precision_recall(y_true, y_pred):\n    # TODO\n    pass\n",
        "hints": ["Count true positives, false positives and false negatives.", "precision = tp / (tp + fp); recall = tp / (tp + fn). Guard the zero cases."],
        "explanation": "Precision asks: of the ones I flagged, how many were right? Recall asks: of the real positives, how many did I find? On imbalanced data (like fraud) accuracy hides a model that finds nothing, which is why you check both.",
        "solution": "def precision_recall(y_true, y_pred):\n    tp = sum(1 for t, p in zip(y_true, y_pred) if t == 1 and p == 1)\n    fp = sum(1 for t, p in zip(y_true, y_pred) if t == 0 and p == 1)\n    fn = sum(1 for t, p in zip(y_true, y_pred) if t == 1 and p == 0)\n    precision = tp / (tp + fp) if tp + fp else 0.0\n    recall = tp / (tp + fn) if tp + fn else 0.0\n    return precision, recall\n",
        "tests": r'''
def _close(a, b):
    return abs(a - b) < 1e-9

def test_basic(ns):
    """Computes both metrics"""
    p, r = ns["precision_recall"]([1, 0, 1, 1, 0, 0], [1, 0, 0, 1, 1, 0])
    assert _close(p, 2 / 3) and _close(r, 2 / 3), f"expected (0.667, 0.667) but got ({p:.3f}, {r:.3f})"

def test_perfect(ns):
    """Perfect predictions give 1.0 and 1.0"""
    p, r = ns["precision_recall"]([1, 0, 1], [1, 0, 1])
    assert _close(p, 1.0) and _close(r, 1.0), "expected (1.0, 1.0)"

def test_never_predicts_positive(ns):
    """The 'always negative' model: 99% accurate, useless"""
    p, r = ns["precision_recall"]([0] * 99 + [1], [0] * 100)
    assert _close(p, 0.0) and _close(r, 0.0), "expected (0.0, 0.0), with no division error"

def test_no_actual_positives(ns):
    """No actual positives means recall 0.0"""
    p, r = ns["precision_recall"]([0, 0, 0], [1, 0, 0])
    assert _close(r, 0.0) and _close(p, 0.0), "expected (0.0, 0.0)"
''',
    },
    {
        "id": "dc-8", "track": "datascience", "type": "code", "difficulty": HARD, "title": "Rolling mean per group",
        "packages": ["pandas"],
        "prompt": "Write `rolling_mean_by_group(df, group, column, window)` returning a Series (same index and row order as `df`) holding the rolling mean of `column` computed separately inside each `group`. The first `window - 1` rows of each group are NaN.",
        "starter": "import pandas as pd\n\ndef rolling_mean_by_group(df, group, column, window):\n    # TODO\n    pass\n",
        "hints": ["groupby(group)[column] then .transform(...) keeps the original row order.", "Inside transform use s.rolling(window).mean()."],
        "explanation": "`transform` returns a result aligned with the original rows, so groups can be interleaved. A plain rolling mean would blend values across groups.",
        "solution": "import pandas as pd\n\ndef rolling_mean_by_group(df, group, column, window):\n    return df.groupby(group)[column].transform(lambda s: s.rolling(window).mean())\n",
        "tests": r'''
import pandas as pd

def _df():
    return pd.DataFrame({"team": ["a", "b", "a", "b", "a", "b"], "pts": [1, 10, 3, 20, 5, 30]})

def test_values(ns):
    """Computes the rolling mean inside each group"""
    out = ns["rolling_mean_by_group"](_df(), "team", "pts", 2)
    got = out.tolist()
    want = [None, None, 2.0, 15.0, 4.0, 25.0]
    for g, w in zip(got, want):
        if w is None:
            assert pd.isna(g), f"expected NaN but got {g}"
        else:
            assert abs(g - w) < 1e-9, f"expected {w} but got {g}"

def test_alignment(ns):
    """Keeps the original index and row order"""
    df = _df()
    out = ns["rolling_mean_by_group"](df, "team", "pts", 2)
    assert out.index.tolist() == df.index.tolist(), "the result must line up with the original rows"

def test_is_series(ns):
    """Returns a Series"""
    assert isinstance(ns["rolling_mean_by_group"](_df(), "team", "pts", 2), pd.Series), "return a pandas Series"
''',
    },
    {
        "id": "dm-1", "track": "datascience", "type": "mcq", "difficulty": MEDIUM, "title": "What a p-value means",
        "prompt": "A test returns p = 0.03. Which statement is correct?",
        "options": ["There is a 3% chance the null hypothesis is true", "If the null hypothesis were true, data this extreme would appear about 3% of the time", "There is a 97% chance the effect is real", "The effect is large"],
        "answer": 1, "hints": ["A p-value is a probability about the data, given the null hypothesis."],
        "explanation": "A p-value is P(data at least this extreme | null is true). It is not the probability that the null is true, and it says nothing about effect size.",
    },
    {
        "id": "dm-2", "track": "datascience", "type": "mcq", "difficulty": MEDIUM, "title": "Scaling before the split",
        "prompt": "You fit a StandardScaler on the whole dataset, then split into train and test. What is the problem?",
        "options": ["Nothing, scaling is always safe", "Data leakage: test-set statistics influenced the training data", "The model will not converge", "The scaler needs random_state"],
        "answer": 1, "hints": ["Which rows did the scaler learn its mean and std from?"],
        "explanation": "Fit preprocessing on the training set only, then apply it to the test set. Otherwise information from the test set leaks into training and the score looks better than reality.",
    },
    {
        "id": "dm-3", "track": "datascience", "type": "mcq", "difficulty": EASY, "title": "99% accuracy",
        "prompt": "Only 1% of transactions are fraud. Your model has 99% accuracy. What should you conclude?",
        "options": ["It is excellent", "It may be no better than predicting 'not fraud' for everyone; check precision and recall", "It needs more features", "Accuracy is always the right metric"],
        "answer": 1, "hints": ["What accuracy would a model that always says 'not fraud' get?"],
        "explanation": "With a 1% base rate, always predicting the majority class already scores 99%. On imbalanced problems use precision, recall or F1 and compare with a baseline.",
    },

    # ── JAVA ──────────────────────────────────────────────────────────────────
    {
        "id": "jv-1", "track": "java", "type": "mcq", "difficulty": EASY, "title": "String equality",
        "prompt": "String a = new String(\"hi\");\nString b = new String(\"hi\");\nWhat do `a == b` and `a.equals(b)` return?",
        "options": ["true, true", "false, true", "true, false", "false, false"],
        "answer": 1, "hints": ["== compares references, equals() compares content."],
        "explanation": "`==` checks whether both variables point to the same object; `new String(...)` creates two objects. `equals()` compares the characters. Always compare Strings with equals().",
    },
    {
        "id": "jv-2", "track": "java", "type": "mcq", "difficulty": EASY, "title": "Checked exceptions",
        "prompt": "Which of these MUST be caught or declared with `throws`?",
        "options": ["NullPointerException", "IllegalArgumentException", "IOException", "ArithmeticException"],
        "answer": 2, "hints": ["Checked exceptions extend Exception but not RuntimeException."],
        "explanation": "IOException is a checked exception: the compiler forces you to handle or declare it. The others are unchecked (RuntimeException subclasses).",
    },
    {
        "id": "jv-3", "track": "java", "type": "mcq", "difficulty": MEDIUM, "title": "HashMap ordering",
        "prompt": "Which statement about HashMap iteration order is true?",
        "options": ["It is insertion order", "It is sorted by key", "It is not guaranteed", "It is reverse insertion order"],
        "answer": 2, "hints": ["Which map types promise an order?"],
        "explanation": "HashMap makes no ordering promise. Use LinkedHashMap for insertion order or TreeMap for sorted keys.",
    },
    {
        "id": "jv-4", "track": "java", "type": "rubric", "difficulty": EASY, "title": "Encapsulate a bank account",
        "prompt": "Rewrite `BankAccount` properly: private balance, a constructor taking the opening balance, `deposit`, `withdraw` and `getBalance`. Reject non-positive amounts and overdrafts by throwing an exception.",
        "starter": "public class BankAccount {\n    public double balance;\n\n    public void withdraw(double amount) {\n        balance -= amount;\n    }\n}\n",
        "hints": ["Make the field private and expose behaviour through methods.", "Validate inputs at the start of deposit/withdraw and throw IllegalArgumentException."],
        "explanation": "Encapsulation keeps the object's state valid: only its own methods can change the balance, and they enforce the rules.",
        "solution": "public class BankAccount {\n    private double balance;\n\n    public BankAccount(double opening) {\n        if (opening < 0) throw new IllegalArgumentException(\"negative\");\n        this.balance = opening;\n    }\n\n    public void deposit(double amount) {\n        if (amount <= 0) throw new IllegalArgumentException(\"amount must be positive\");\n        balance += amount;\n    }\n\n    public void withdraw(double amount) {\n        if (amount <= 0 || amount > balance) throw new IllegalArgumentException(\"invalid amount\");\n        balance -= amount;\n    }\n\n    public double getBalance() {\n        return balance;\n    }\n}\n",
        "rubric": [
            check("private", "The balance field is private", r"private\s+(double|long|int|BigDecimal)\s+balance", "Declare `private double balance;`."),
            check("no-public-field", "There are no public fields", r"public\s+(double|long|int|String|BigDecimal)\s+\w+\s*;", "Remove public fields and use methods instead.", must=False),
            check("constructor", "A constructor sets the opening balance", r"public\s+BankAccount\s*\(\s*(double|long|int|BigDecimal)\s+\w+\s*\)", "Add `public BankAccount(double opening)`."),
            check("deposit", "There is a deposit method", r"void\s+deposit\s*\(", "Add `public void deposit(double amount)`."),
            check("withdraw", "There is a withdraw method", r"void\s+withdraw\s*\(", "Keep a `withdraw(double amount)` method."),
            check("getter", "There is a getBalance method", r"\bgetBalance\s*\(\s*\)", "Add `public double getBalance()`."),
            check("validation", "Invalid amounts throw an exception", r"throw\s+new\s+(IllegalArgumentException|IllegalStateException)", "Throw IllegalArgumentException for non-positive amounts and overdrafts."),
        ],
    },
    {
        "id": "jv-5", "track": "java", "type": "rubric", "difficulty": MEDIUM, "title": "Read a file safely",
        "prompt": "`readFirstLine` leaks the file handle if an exception happens. Rewrite it with try-with-resources and do not swallow errors.",
        "starter": "public String readFirstLine(String path) throws IOException {\n    BufferedReader reader = new BufferedReader(new FileReader(path));\n    String line = reader.readLine();\n    return line;\n}\n",
        "hints": ["try (BufferedReader reader = ...) { ... } closes automatically.", "Let the IOException propagate (throws IOException) or handle it meaningfully; never leave a catch block empty."],
        "explanation": "try-with-resources closes the resource even when an exception is thrown, so no manual finally/close() is needed.",
        "solution": "public String readFirstLine(String path) throws IOException {\n    try (BufferedReader reader = new BufferedReader(new FileReader(path))) {\n        return reader.readLine();\n    }\n}\n",
        "rubric": [
            check("twr", "Uses try-with-resources", r"try\s*\(", "Use `try (BufferedReader reader = ...) { ... }`."),
            check("reader", "Reads with a BufferedReader", r"BufferedReader", "Keep using BufferedReader."),
            check("readline", "Calls readLine()", r"\.readLine\s*\(", "Call reader.readLine()."),
            check("no-empty-catch", "No empty catch block", r"catch\s*\([^)]*\)\s*\{\s*\}", "Never leave a catch block empty: handle, log or rethrow.", must=False),
            check("no-manual-close", "No manual close() call", r"\.close\s*\(", "try-with-resources already closes the reader.", must=False),
        ],
    },
    {
        "id": "jv-6", "track": "java", "type": "rubric", "difficulty": MEDIUM, "title": "Streams: sorted adult names",
        "prompt": "Given `List<Person> people` (with `getName()` and `getAge()`), return the names of people aged 18 or over, sorted alphabetically, using the Stream API (no for loops).",
        "starter": "public List<String> adultNames(List<Person> people) {\n    // TODO\n    return null;\n}\n",
        "hints": ["people.stream().filter(...).map(Person::getName)...", "Finish with .sorted() and .toList() (or collect(Collectors.toList()))."],
        "explanation": "A stream pipeline expresses filter -> transform -> sort -> collect declaratively, with no mutable loop state.",
        "solution": "public List<String> adultNames(List<Person> people) {\n    return people.stream()\n        .filter(p -> p.getAge() >= 18)\n        .map(Person::getName)\n        .sorted()\n        .toList();\n}\n",
        "rubric": [
            check("stream", "Starts a stream", r"\.stream\s*\(\s*\)", "Call people.stream()."),
            check("filter", "Filters by age", r"\.filter\s*\(", "Add .filter(p -> p.getAge() >= 18)."),
            check("map", "Maps to names", r"\.map\s*\(", "Add .map(Person::getName)."),
            check("sorted", "Sorts the names", r"\.sorted\s*\(", "Add .sorted()."),
            check("collect", "Collects to a list", r"\.toList\s*\(\s*\)|Collectors\.toList\s*\(\s*\)", "End with .toList()."),
            check("no-loop", "Does not use a for loop", r"\bfor\s*\(", "Use the stream instead of a for loop.", must=False),
        ],
    },
    {
        "id": "jv-7", "track": "java", "type": "rubric", "difficulty": HARD, "title": "equals and hashCode",
        "prompt": "Add correct `equals` and `hashCode` to `Customer` (fields `id` and `email`) so two customers with the same id and email are equal and share a hash code.",
        "starter": "public class Customer {\n    private final long id;\n    private final String email;\n\n    public Customer(long id, String email) {\n        this.id = id;\n        this.email = email;\n    }\n}\n",
        "hints": ["equals(Object o) must check identity, null/type, then compare fields (Objects.equals).", "hashCode() should use the same fields: Objects.hash(id, email)."],
        "explanation": "Equal objects must have equal hash codes, or HashMap/HashSet break. Compare the same fields in both methods and use Objects.equals/Objects.hash to be null-safe.",
        "solution": "import java.util.Objects;\n\npublic class Customer {\n    private final long id;\n    private final String email;\n\n    public Customer(long id, String email) {\n        this.id = id;\n        this.email = email;\n    }\n\n    @Override\n    public boolean equals(Object o) {\n        if (this == o) return true;\n        if (o == null || getClass() != o.getClass()) return false;\n        Customer other = (Customer) o;\n        return id == other.id && Objects.equals(email, other.email);\n    }\n\n    @Override\n    public int hashCode() {\n        return Objects.hash(id, email);\n    }\n}\n",
        "rubric": [
            check("equals", "Overrides equals(Object)", r"boolean\s+equals\s*\(\s*Object\s+\w+\s*\)", "Declare `public boolean equals(Object o)`."),
            check("hashcode", "Overrides hashCode()", r"int\s+hashCode\s*\(\s*\)", "Declare `public int hashCode()`."),
            check("override", "Uses @Override", r"@Override", "Add @Override so the compiler checks the signature."),
            check("type-check", "Checks the type in equals", r"getClass\s*\(\s*\)|instanceof", "Check `getClass() != o.getClass()` or use instanceof."),
            check("null-safe", "Compares fields null-safely", r"Objects\.equals\s*\(", "Compare fields with Objects.equals(email, other.email)."),
            check("hash-fields", "hashCode uses the fields", r"hashCode\s*\(\s*\)\s*\{[^}]*(Objects\.hash|31)", "Return Objects.hash(id, email)."),
        ],
    },
    {
        "id": "jv-8", "track": "java", "type": "rubric", "difficulty": HARD, "title": "An immutable class",
        "prompt": "Make `Money` immutable: a final class, private final fields (`amount`, `currency`), set only in the constructor, and no setters.",
        "starter": "public class Money {\n    private double amount;\n    private String currency;\n\n    public void setAmount(double amount) { this.amount = amount; }\n    public double getAmount() { return amount; }\n    public String getCurrency() { return currency; }\n}\n",
        "hints": ["Declare `public final class Money` and make the fields `private final`.", "Remove the setters; initialise everything in a constructor."],
        "explanation": "Immutable objects are thread-safe and easy to reason about. Final fields, no setters and a final class stop anyone changing or subclassing away the guarantees.",
        "solution": "public final class Money {\n    private final double amount;\n    private final String currency;\n\n    public Money(double amount, String currency) {\n        this.amount = amount;\n        this.currency = currency;\n    }\n\n    public double getAmount() { return amount; }\n    public String getCurrency() { return currency; }\n}\n",
        "rubric": [
            check("final-class", "The class is final", r"final\s+class\s+Money", "Declare `public final class Money`."),
            check("final-fields", "Fields are private final", r"private\s+final\s+(double|BigDecimal|long)\s+amount", "Declare `private final double amount;`."),
            check("final-currency", "Currency is private final", r"private\s+final\s+String\s+currency", "Declare `private final String currency;`."),
            check("constructor", "A constructor sets the state", r"public\s+Money\s*\(", "Add a constructor taking amount and currency."),
            check("no-setters", "There are no setters", r"void\s+set[A-Z]\w*\s*\(", "Remove every setter.", must=False),
        ],
    },

    # ── SPRING BOOT ───────────────────────────────────────────────────────────
    {
        "id": "sp-1", "track": "spring", "type": "mcq", "difficulty": EASY, "title": "@SpringBootApplication",
        "prompt": "Which three annotations does @SpringBootApplication combine?",
        "options": ["@Configuration, @EnableAutoConfiguration, @ComponentScan", "@Controller, @Service, @Repository", "@Bean, @Component, @Autowired", "@EnableWebMvc, @EnableJpaRepositories, @Entity"],
        "answer": 0, "hints": ["Configuration, auto-configuration and scanning."],
        "explanation": "@SpringBootApplication = @Configuration + @EnableAutoConfiguration + @ComponentScan: it declares beans, turns on auto-configuration from your classpath, and scans the package for components.",
    },
    {
        "id": "sp-2", "track": "spring", "type": "mcq", "difficulty": EASY, "title": "Status for a created resource",
        "prompt": "A POST successfully creates a new user. Which HTTP status should the API return?",
        "options": ["200 OK", "201 Created", "204 No Content", "302 Found"],
        "answer": 1, "hints": ["There is a status specifically for 'a new resource now exists'."],
        "explanation": "201 Created (ideally with a Location header) tells clients a new resource exists. In Spring: ResponseEntity.created(uri).body(...) or @ResponseStatus(HttpStatus.CREATED).",
    },
    {
        "id": "sp-3", "track": "spring", "type": "mcq", "difficulty": MEDIUM, "title": "@Transactional gotcha",
        "prompt": "A public method in your service calls another @Transactional method of the SAME class (this.save()). The second method's transaction settings are ignored. Why?",
        "options": ["@Transactional only works on interfaces", "Self-invocation bypasses the Spring proxy that applies the transaction", "Transactions require @Repository", "The method must be private"],
        "answer": 1, "hints": ["How does Spring apply @Transactional: with a proxy around the bean."],
        "explanation": "Spring applies @Transactional through a proxy. A call from inside the same object never passes through the proxy, so the annotation has no effect. Move the method to another bean.",
    },
    {
        "id": "sp-4", "track": "spring", "type": "mcq", "difficulty": MEDIUM, "title": "Why constructor injection?",
        "prompt": "Why do most teams prefer constructor injection over @Autowired fields?",
        "options": ["It is faster at runtime", "Dependencies are explicit and can be final, and the class is easy to test without Spring", "@Autowired is deprecated", "Fields cannot be injected"],
        "answer": 1, "hints": ["Think about how you would build the class in a plain unit test."],
        "explanation": "Constructor injection makes required dependencies explicit and immutable (final), and lets you instantiate the class in a unit test with mocks, with no Spring context.",
    },
    {
        "id": "sp-5", "track": "spring", "type": "rubric", "difficulty": EASY, "title": "A REST endpoint",
        "prompt": "Create `UserController` exposing `GET /api/users/{id}` that returns a user found through `UserService`.",
        "starter": "public class UserController {\n    // TODO\n}\n",
        "hints": ["Annotate the class with @RestController and @RequestMapping(\"/api/users\").", "Use @GetMapping(\"/{id}\") and @PathVariable Long id."],
        "explanation": "@RestController marks the class as a web controller returning data, @GetMapping maps the URL and @PathVariable binds `{id}` to a parameter.",
        "solution": "@RestController\n@RequestMapping(\"/api/users\")\npublic class UserController {\n    private final UserService service;\n\n    public UserController(UserService service) {\n        this.service = service;\n    }\n\n    @GetMapping(\"/{id}\")\n    public User get(@PathVariable Long id) {\n        return service.find(id);\n    }\n}\n",
        "rubric": [
            check("restcontroller", "The class is a @RestController", r"@RestController", "Annotate the class with @RestController."),
            check("getmapping", "Handles GET with @GetMapping", r"@GetMapping\s*\(", "Add @GetMapping(\"/{id}\") to the method."),
            check("pathvariable", "Binds the id with @PathVariable", r"@PathVariable", "Add @PathVariable Long id."),
            check("service", "Uses UserService", r"UserService", "Call UserService to find the user."),
            check("ctor", "Gets the service by constructor", r"public\s+UserController\s*\(\s*UserService", "Inject UserService through the constructor."),
        ],
    },
    {
        "id": "sp-6", "track": "spring", "type": "rubric", "difficulty": MEDIUM, "title": "Constructor injection",
        "prompt": "Refactor `UserService` to use constructor injection with a final repository field.",
        "starter": "@Service\npublic class UserService {\n    @Autowired\n    private UserRepository repository;\n\n    public User find(Long id) {\n        return repository.findById(id).get();\n    }\n}\n",
        "hints": ["Make the field `private final UserRepository repository`.", "Add a constructor and remove @Autowired. Also replace .get() with orElseThrow(...)."],
        "explanation": "A final field plus constructor makes the dependency mandatory and testable. orElseThrow gives a meaningful error instead of NoSuchElementException.",
        "solution": "@Service\npublic class UserService {\n    private final UserRepository repository;\n\n    public UserService(UserRepository repository) {\n        this.repository = repository;\n    }\n\n    public User find(Long id) {\n        return repository.findById(id).orElseThrow(() -> new UserNotFoundException(id));\n    }\n}\n",
        "rubric": [
            check("service", "The class is a @Service", r"@Service", "Keep the @Service annotation."),
            check("final", "The repository is a private final field", r"private\s+final\s+UserRepository", "Declare `private final UserRepository repository;`."),
            check("ctor", "A constructor receives the repository", r"public\s+UserService\s*\(\s*UserRepository\s+\w+", "Add `public UserService(UserRepository repository)`."),
            check("no-autowired-field", "No field-level @Autowired", r"@Autowired\s+(private|protected|public)", "Remove @Autowired from the field.", must=False),
            check("orelsethrow", "Uses orElseThrow instead of get()", r"\.orElseThrow\s*\(", "Replace .get() with .orElseThrow(() -> new ...)."),
        ],
    },
    {
        "id": "sp-7", "track": "spring", "type": "rubric", "difficulty": MEDIUM, "title": "Validated create endpoint",
        "prompt": "Add `POST /users` that validates the request body (`@NotBlank` name, `@Email` email) and returns HTTP 201.",
        "starter": "public record CreateUserRequest(String name, String email) {}\n\n@PostMapping(\"/users\")\npublic User create(@RequestBody CreateUserRequest request) {\n    return service.create(request);\n}\n",
        "hints": ["Add @Valid before @RequestBody, and constraint annotations on the record components.", "Return ResponseEntity.status(HttpStatus.CREATED).body(...)."],
        "explanation": "@Valid triggers Bean Validation on the body; without it the constraint annotations are never checked. 201 signals that a new resource was created.",
        "solution": "public record CreateUserRequest(@NotBlank String name, @Email String email) {}\n\n@PostMapping(\"/users\")\npublic ResponseEntity<User> create(@Valid @RequestBody CreateUserRequest request) {\n    return ResponseEntity.status(HttpStatus.CREATED).body(service.create(request));\n}\n",
        "rubric": [
            check("post", "Handles POST", r"@PostMapping", "Keep @PostMapping."),
            check("valid", "Validates the body with @Valid", r"@Valid\s+@RequestBody|@RequestBody\s+@Valid|@Validated", "Write `@Valid @RequestBody CreateUserRequest request`."),
            check("constraints", "Declares constraints on the fields", r"@(NotBlank|NotNull|NotEmpty|Email|Size)", "Add @NotBlank on name and @Email on email."),
            check("email", "The email is validated as an email", r"@Email", "Add @Email to the email component."),
            check("created", "Returns 201 Created", r"HttpStatus\.CREATED|ResponseEntity\.created\s*\(|@ResponseStatus\s*\(\s*HttpStatus\.CREATED", "Return ResponseEntity.status(HttpStatus.CREATED).body(...)."),
        ],
    },
    {
        "id": "sp-8", "track": "spring", "type": "rubric", "difficulty": HARD, "title": "Global exception handler",
        "prompt": "Create a `GlobalExceptionHandler` that turns `UserNotFoundException` into an HTTP 404 with a JSON body, without printing stack traces.",
        "starter": "public class GlobalExceptionHandler {\n    // TODO\n}\n",
        "hints": ["Annotate the class with @RestControllerAdvice and the method with @ExceptionHandler(UserNotFoundException.class).", "Return ResponseEntity.status(HttpStatus.NOT_FOUND).body(...)."],
        "explanation": "@RestControllerAdvice centralises error handling so controllers stay clean and every failure returns the same, safe shape (never a stack trace).",
        "solution": "@RestControllerAdvice\npublic class GlobalExceptionHandler {\n\n    @ExceptionHandler(UserNotFoundException.class)\n    public ResponseEntity<Map<String, String>> handle(UserNotFoundException ex) {\n        return ResponseEntity.status(HttpStatus.NOT_FOUND).body(Map.of(\"error\", \"User not found\"));\n    }\n}\n",
        "rubric": [
            check("advice", "Uses @RestControllerAdvice", r"@(Rest)?ControllerAdvice", "Annotate the class with @RestControllerAdvice."),
            check("handler", "Declares an @ExceptionHandler", r"@ExceptionHandler\s*\(", "Add @ExceptionHandler(UserNotFoundException.class)."),
            check("exception", "Handles UserNotFoundException", r"UserNotFoundException", "Handle UserNotFoundException."),
            check("404", "Returns 404", r"HttpStatus\.NOT_FOUND|\.notFound\s*\(|\b404\b", "Return HttpStatus.NOT_FOUND."),
            check("body", "Returns a response body", r"ResponseEntity|ProblemDetail|@ResponseBody", "Return a ResponseEntity with a body."),
            check("no-trace", "Does not print stack traces", r"printStackTrace\s*\(", "Never expose or print stack traces.", must=False),
        ],
    },
    {
        "id": "sp-9", "track": "spring", "type": "rubric", "difficulty": HARD, "title": "Secure the API",
        "prompt": "Configure a `SecurityFilterChain` bean that is stateless and requires authentication for every request except `/api/auth/**` and `/actuator/health`.",
        "starter": "@Configuration\n@EnableWebSecurity\npublic class SecurityConfig {\n\n    @Bean\n    public SecurityFilterChain filterChain(HttpSecurity http) throws Exception {\n        http.authorizeHttpRequests(auth -> auth.anyRequest().permitAll());\n        return http.build();\n    }\n}\n",
        "hints": ["Allow only the two paths with requestMatchers(...).permitAll(), then anyRequest().authenticated().", "Add .sessionManagement(s -> s.sessionCreationPolicy(SessionCreationPolicy.STATELESS))."],
        "explanation": "Secure by default: authenticate everything, then explicitly open the few public paths. A stateless session policy fits token-based APIs, where CSRF protection can be disabled deliberately.",
        "solution": "@Configuration\n@EnableWebSecurity\npublic class SecurityConfig {\n\n    @Bean\n    public SecurityFilterChain filterChain(HttpSecurity http) throws Exception {\n        http.csrf(csrf -> csrf.disable())\n            .sessionManagement(s -> s.sessionCreationPolicy(SessionCreationPolicy.STATELESS))\n            .authorizeHttpRequests(auth -> auth\n                .requestMatchers(\"/api/auth/**\", \"/actuator/health\").permitAll()\n                .anyRequest().authenticated());\n        return http.build();\n    }\n}\n",
        "rubric": [
            check("bean", "Declares a SecurityFilterChain @Bean", r"@Bean[\s\S]*SecurityFilterChain", "Expose a @Bean method returning SecurityFilterChain."),
            check("authorize", "Uses authorizeHttpRequests", r"authorizeHttpRequests", "Configure rules with authorizeHttpRequests(...)."),
            check("matchers", "Opens specific paths with requestMatchers", r"requestMatchers\s*\(", "Use requestMatchers(\"/api/auth/**\", \"/actuator/health\").permitAll()."),
            check("authenticated", "Requires authentication for everything else", r"anyRequest\s*\(\s*\)\s*\.\s*authenticated\s*\(", "End with .anyRequest().authenticated()."),
            check("open-all", "Does not permit every request", r"anyRequest\s*\(\s*\)\s*\.\s*permitAll\s*\(", "Never use anyRequest().permitAll().", must=False),
            check("stateless", "Is stateless", r"SessionCreationPolicy\.STATELESS", "Add sessionCreationPolicy(SessionCreationPolicy.STATELESS)."),
        ],
    },
]
