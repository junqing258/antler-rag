"""单次调用的答案合成，使用显式的字符上下文预算。"""


def context_evidence(evidence, *, question, prompt, budget):
    remaining = budget - len(question) - len(prompt) - len("Sources:\n\n\nQuestion: ")
    selected = []
    for item in evidence:
        block = f"[Source {len(selected) + 1}: {item.filename}]\n{item.content}"
        cost = len(block) + (2 if selected else 0)
        if cost > remaining:
            break
        selected.append(item)
        remaining -= cost
    return selected


def answer_messages(prompt, question, evidence):
    sources = "\n\n".join(
        f"[Source {index}: {item.filename}]\n{item.content}"
        for index, item in enumerate(evidence, 1)
    )
    return [
        {"role": "system", "content": prompt},
        {"role": "user", "content": f"Sources:\n{sources}\n\nQuestion: {question}"},
    ]
