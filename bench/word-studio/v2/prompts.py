"""Frozen prompt protocol for the Word Studio v2 benchmark (#85).

Every candidate gets the same system and user messages. Only the model's own
chat template may differ. Changing any text here changes the rendered task
files, which makes a new benchmark version: bump ``PROMPT_VERSION`` and rebuild
the tasks before any results exist for the new version.
"""
from __future__ import annotations

PROMPT_VERSION = "ws2-prompts-v1"

#: Decoding settings shared by every candidate. One sample per task, seeded
#: from the task id so a rerun of the same candidate is reproducible.
GENERATION = {
    "do_sample": True,
    "temperature": 0.7,
    "top_p": 0.9,
    "top_k": 50,
    "repetition_penalty": 1.0,
    "samples_per_task": 1,
    "seed": "first 8 bytes of sha256(task id), big-endian",
    "thinking": "disabled: enable_thinking=False is passed to every chat template",
}

#: Options requested and the new-token cap for each feature.
TASK_KINDS = {
    "tap_word": {"options": 10, "max_new_tokens": 320, "feature": "tap a word: context-fit replacements"},
    "phrase_to_word": {"options": 10, "max_new_tokens": 256, "feature": "phrase to one word"},
    "word_sentences": {"options": 5, "max_new_tokens": 768, "feature": "word to example sentences in context"},
    "condense": {"options": 5, "max_new_tokens": 640, "feature": "sentence: same meaning in fewer words"},
    "paraphrase": {"options": 5, "max_new_tokens": 768, "feature": "sentence: same length, new words"},
    "academic": {"options": 5, "max_new_tokens": 896, "feature": "sentence: more academic, no new claims"},
}

SELECTION_KINDS = frozenset({"tap_word", "phrase_to_word"})
SENTENCE_KINDS = frozenset({"condense", "paraphrase", "academic"})

SYSTEM = (
    "You are Pari, a writing assistant for school and college essays. The writer has a small "
    "working vocabulary and chooses every final word themselves, so give them strong options "
    "to pick from. Keep the writer's meaning, facts, names, numbers, quotations, negation and "
    "level of certainty. Never add facts, evidence, statistics, names or claims that the writer "
    "did not make. Reply with JSON only, exactly in this form: {\"options\": [\"...\", \"...\"]}. "
    "No commentary, no explanations, no numbering."
)

_PARAGRAPH = 'Paragraph:\n"""\n{paragraph}\n"""\n\n'
_MARKED = "{intro} in this sentence (marked with [[ ]]):\n{marked_sentence}\n\n"
_SELECTED = 'The writer selected this text:\n"""\n{selected}\n"""\n\n'

_INSTRUCTIONS = {
    "tap_word": (
        'Give {n} replacements for "{selected}" that fit this sentence and keep its meaning, in a '
        "clear essay register. Each option must be one word or a short phrase of at most three "
        'words that can replace "{selected}" without changing the rest of the sentence. Do not '
        'repeat "{selected}" itself. Put the best options first.'
    ),
    "phrase_to_word": (
        'Give {n} single words that can replace "{selected}" in this sentence with the same '
        "meaning. Each option must be exactly one word and must fit the sentence without "
        "changing the rest of it. Put the best options first."
    ),
    "word_sentences": (
        'Write {n} different sentences that use "{word}" naturally and could fit into this '
        'paragraph, on its topic and in its argument. Each sentence must contain "{word}" '
        "(another form of the word, such as a plural or past tense, is fine). Use only ideas the "
        "paragraph already contains; do not invent statistics, names or quotations. Put the best "
        "sentences first."
    ),
    "condense": (
        "Give {n} different rewrites of the selected text that say the same thing in fewer "
        "words. Keep every fact, name, number and quotation, and keep the claim exactly as strong "
        "or as uncertain as it is. Put the best options first."
    ),
    "paraphrase": (
        "Give {n} different rewrites of the selected text that use new wording but keep about "
        "the same length. Keep the meaning, facts, names, numbers and quotations. Each rewrite "
        "must read naturally in place of the original. Put the best options first."
    ),
    "academic": (
        "Give {n} different rewrites of the selected text in a more academic register suitable "
        "for a school or college essay. Keep the same meaning and the same level of certainty. "
        "Do not add evidence, statistics, names, citations or new ideas. Put the best options "
        "first."
    ),
}


def mark(sentence: str, start: int, end: int) -> str:
    """Wrap ``sentence[start:end]`` in ``[[ ]]``."""
    return f"{sentence[:start]}[[{sentence[start:end]}]]{sentence[end:]}"


def render_messages(
    kind: str,
    *,
    paragraph: str,
    sentence: str | None = None,
    sentence_span: tuple[int, int] | None = None,
    selected: str | None = None,
    word: str | None = None,
) -> list[dict[str, str]]:
    """Return the system and user messages for one task."""
    if kind not in TASK_KINDS:
        raise ValueError(f"unknown task kind {kind!r}")
    n = TASK_KINDS[kind]["options"]
    user = _PARAGRAPH.format(paragraph=paragraph)
    if kind in SELECTION_KINDS:
        if sentence is None or sentence_span is None or selected is None:
            raise ValueError(f"{kind} needs a sentence, a span and the selected text")
        intro = (
            f'The writer tapped the word "{selected}"'
            if kind == "tap_word"
            else f'The writer selected the phrase "{selected}"'
        )
        user += _MARKED.format(intro=intro, marked_sentence=mark(sentence, *sentence_span))
        user += _INSTRUCTIONS[kind].format(n=n, selected=selected)
    elif kind in SENTENCE_KINDS:
        if selected is None:
            raise ValueError(f"{kind} needs the selected text")
        user += _SELECTED.format(selected=selected)
        user += _INSTRUCTIONS[kind].format(n=n)
    else:
        if not word:
            raise ValueError("word_sentences needs a word")
        user += f'The writer wants to use the word "{word}" in this essay.\n\n'
        user += _INSTRUCTIONS[kind].format(n=n, word=word)
    return [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}]
