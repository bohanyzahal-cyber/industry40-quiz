"""Builds index.html from template.html and the question banks.

Run:  python build.py   (from this folder)

Each bank in banks/*.json looks like:
  {"topic": "...", "items": [{"s": "מצגת", "q": "...", "o": [correct, d1, d2, d3], "e": "..."}]}
The correct answer is always written first. The build shuffles the options with a
seed taken from the question text, so the answer letter is spread evenly and stays
stable between builds. The app shuffles again on every round.
"""
import glob, hashlib, json, os, random, re, sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)            # .../industry40-quiz
COURSE = os.path.dirname(REPO)          # the course folder
TARGETS = [
    os.path.join(REPO, "index.html"),
    os.path.join(COURSE, "בוחן תרגול - Industry 4.0.html"),
]
# The same page for publishing as a claude.ai Artifact (not committed).
ARTIFACT = os.path.join(REPO, "artifact-build", "page.html")

# Options the app would break by shuffling, e.g. "all of the above".
POSITIONAL = re.compile(r'כל התשובות|כל ההיגדים|כל הנ["״\']ל|אף תשובה|אף אחת מהתשובות|תשובות? א[\'׳]\s*\+|א[\'׳]\s*\+\s*ב[\'׳]')


def clean(text):
    """The app renders questions with innerHTML and prints them with textContent,
    so the text must stay plain: no angle brackets, and line breaks become spaces."""
    text = re.sub(r"\s+", " ", str(text)).strip()
    return re.sub(r" ([.,;:!?])", r"\1", text)


def word_set(text):
    """The words of an option, ignoring order and punctuation."""
    return frozenset(re.findall(r"\w+", text.lower()))


def length_rank(lengths):
    """Where the correct option (written first) falls by length."""
    if lengths[0] > max(lengths[1:]):
        return "longest"
    if lengths[0] < min(lengths[1:]):
        return "shortest"
    return "middle"


def load_banks():
    banks = []
    for path in sorted(glob.glob(os.path.join(HERE, "banks", "*.json"))):
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        banks.append((os.path.basename(path), data))
    return banks


def build():
    problems, warnings = [], []
    out, seen = [], {}
    by_topic, by_src, letters = {}, {}, [0, 0, 0, 0]
    # Length of the correct option against the distractors, per group of questions.
    # With four options, chance is about 25% longest and 25% shortest.
    ranks = {}
    banks = load_banks()
    order = [b["topic"] for _, b in banks if b.get("topic")]
    for fname, bank in banks:
        for n, item in enumerate(bank["items"], 1):
            topic = item.get("t") or bank.get("topic")
            where = f"{fname} #{n}"
            if topic not in order:
                problems.append(f"{where}: unknown lecture '{topic}'")
                continue
            q, opts, exp, src = item.get("q", ""), item.get("o", []), item.get("e", ""), item.get("s", "")
            if not (q and exp and src):
                problems.append(f"{where}: a field is missing")
            if len(opts) != 4 or any(not str(o).strip() for o in opts):
                problems.append(f"{where}: needs exactly four non-empty options")
                continue
            if len({re.sub(r"\s+", " ", o).strip() for o in opts}) < 4:
                problems.append(f"{where}: two options are identical")
            elif len({word_set(o) for o in opts}) < 4:
                problems.append(f"{where}: two options use the same words (reworded or reordered duplicate)")
            if any(POSITIONAL.search(o) for o in opts):
                problems.append(f"{where}: an option depends on position (breaks when shuffled)")
            if len(exp) < 40:
                problems.append(f"{where}: explanation shorter than 40 characters")
            key = re.sub(r"\s+", " ", q).strip()
            if key in seen:
                problems.append(f"{where}: duplicate of {seen[key]}")
            seen.setdefault(key, where)
            for o in opts:
                words = o.split()
                for a, b in zip(words, words[1:]):
                    if len(a) >= 4 and a == b:
                        problems.append(f"{where}: repeated word '{a}'")
            group = "class questions" if src == "שאלות הכיתה" else "authored questions"
            rank = length_rank([len(clean(o)) for o in opts])
            ranks.setdefault(group, {"longest": 0, "shortest": 0, "middle": 0})[rank] += 1
            perm = list(range(4))
            random.Random(hashlib.md5(key.encode("utf-8")).hexdigest()).shuffle(perm)
            shuffled = [opts[i] for i in perm]
            c = perm.index(0)
            letters[c] += 1
            if any(ch in (q + exp + "".join(opts)) for ch in "<>"):
                problems.append(f"{where}: angle brackets are not allowed in the text")
            out.append({"t": topic, "s": src, "q": clean(q), "o": [clean(o) for o in shuffled], "c": c, "e": clean(exp)})
            by_topic[topic] = by_topic.get(topic, 0) + 1
            by_src[src] = by_src.get(src, 0) + 1
    # The app lists lectures in the order they first appear, so keep lecture order.
    out.sort(key=lambda x: order.index(x["t"]))
    by_topic = {t: by_topic[t] for t in order if t in by_topic}
    # A length cue: a student could guess by picking (or skipping) the longest option.
    for group, r in ranks.items():
        total = sum(r.values())
        for rank in ("longest", "shortest"):
            if total >= 20 and r[rank] / total > 0.30:
                warnings.append(f"{group}: the correct option is the {rank} in {r[rank]} of {total}")
    return out, problems, warnings, by_topic, by_src, letters, ranks


def main():
    bank, problems, warnings, by_topic, by_src, letters, ranks = build()
    print("questions:", len(bank))
    print("\nby lecture:")
    for k, v in by_topic.items():
        print(f"  {v:4d}  {k}")
    print("by source:", ", ".join(f"{k} {v}" for k, v in sorted(by_src.items(), key=lambda x: -x[1])))
    print("answer letter spread (א ב ג ד):", letters)
    print("correct option by length (chance is about 25% longest, 25% shortest):")
    for group, r in ranks.items():
        total = sum(r.values())
        print(f"  {group}: longest {r['longest']} ({r['longest'] / total:.0%}), "
              f"shortest {r['shortest']} ({r['shortest'] / total:.0%}), middle {r['middle']}")
    for w in warnings:
        print("  warn:", w)
    if problems:
        print("\nPROBLEMS — nothing was written:")
        for p in problems:
            print("  -", p)
        sys.exit(1)
    tpl = open(os.path.join(HERE, "template.html"), encoding="utf-8").read()
    js = "var BANK=" + json.dumps(bank, ensure_ascii=False, separators=(",", ":")) + ";"
    page = tpl.replace("/*__BANK__*/", js)
    for t in TARGETS:
        with open(t, "w", encoding="utf-8") as f:
            f.write(page)
        print("written:", t)
    os.makedirs(os.path.dirname(ARTIFACT), exist_ok=True)
    with open(ARTIFACT, "w", encoding="utf-8") as f:
        f.write(artifact_page(page))
    print("written:", ARTIFACT)
    print("size: %.0f KB" % (len(page.encode("utf-8")) / 1024))
    update_readme(len(bank), by_topic, by_src, ranks)


def artifact_page(page):
    """The Artifact host wraps a page in its own html, head and body, so the
    published file starts at <title> and sets the right-to-left direction itself."""
    start = page.index("<title>")
    style_end = page.index("</style>") + len("</style>")
    body_start = page.index("<body>") + len("<body>")
    body_end = page.rindex("</body>")
    rtl = ('\n<script>document.documentElement.setAttribute("dir","rtl");'
           'document.documentElement.setAttribute("lang","he");</script>')
    return page[start:style_end] + rtl + page[body_start:body_end] + "\n"


def update_readme(total, by_topic, by_src, ranks):
    """Keeps the numbers in README.md in step with the banks."""
    path = os.path.join(REPO, "README.md")
    if not os.path.exists(path):
        return
    text = open(path, encoding="utf-8").read()
    start, end = "<!-- STATS:START", "<!-- STATS:END -->"
    if start not in text or end not in text:
        return
    lines = [start + " — נכתב אוטומטית על ידי src/build.py, אין לערוך ידנית -->",
             f"**{total} שאלות** אמריקאיות, 4 תשובות לשאלה.", "",
             "| נושא | שאלות |", "|---|---|"]
    lines += [f"| {t} | {n} |" for t, n in by_topic.items()]
    lines += ["", "**לפי מקור:** " + " · ".join(f"{s} ({n})" for s, n in sorted(by_src.items(), key=lambda x: -x[1]))]
    parts = []
    for group, name in (("class questions", "בשאלות הכיתה"), ("authored questions", "בשאר השאלות")):
        r = ranks.get(group)
        if r:
            n = sum(r.values())
            parts.append(f"{name} הנכונה היא הארוכה ב-{r['longest'] / n:.0%} והקצרה ב-{r['shortest'] / n:.0%}")
    lines += ["", "**אורך התשובה הנכונה:** " + "; ".join(parts) + " (בניחוש מקרי: כ-25%)."]
    lines.append(end)
    block = "\n".join(lines)
    new = text[:text.index(start)] + block + text[text.index(end) + len(end):]
    if new != text:
        with open(path, "w", encoding="utf-8") as f:
            f.write(new)
        print("updated: README.md")


if __name__ == "__main__":
    main()
