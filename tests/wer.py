"""Word error rate, for checking that a change did not make transcription worse."""
import re


def words(text: str) -> list[str]:
    text = re.sub(r"\[\d{2}:\d{2}\]\s*[^:\n]+:", " ", text.lower())   # drop "[mm:ss] Speaker:"
    return re.findall(r"[\w'%$-]+", text)


def wer(reference: str, hypothesis: str) -> float:
    ref, hyp = words(reference), words(hypothesis)
    if not ref:
        return 0.0 if not hyp else 1.0
    prev = list(range(len(hyp) + 1))
    for i, r in enumerate(ref, 1):
        cur = [i]
        for j, h in enumerate(hyp, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (r != h)))
        prev = cur
    return prev[-1] / len(ref)
