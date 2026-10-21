# ws2-full-p19-tap_word-2

Kind: `tap_word`, asks for 10 options.

Paragraph:

> Standardized tests like the SAT are supposed to measure how ready students are for college, but they do not tell the whole story. A student's score can depend a lot on whether their family could pay for tutoring and practice books. Some students are also very nervous test-takers, so their scores do not show what they actually know. Because of this, more than 1,800 colleges have made the SAT optional. I think colleges should look at grades, essays, and activities instead of focusing on one test score.

Selected: Some students are also very [[nervous]] test-takers, so their scores do not show what they actually know.

Instruction given to every model:

> Give 10 replacements for "nervous" that fit this sentence and keep its meaning, in a clear essay register. Each option must be one word or a short phrase of at most three words that can replace "nervous" without changing the rest of the sentence. Do not repeat "nervous" itself. Put the best options first.

## Output A

ref `o-8458ada008ca`, raw sha256 `8df0ff76f22c558d9666a1eb6502da1352ec5343b93df3e9116b58d760682853`

Format: unparseable (unparseable), 0 options, hit the token limit

No options to judge.


## Output B

ref `o-980d607b1d6c`, raw sha256 `6fa1dc5610f8609206d490728d86264144452d4053bd028908ab751084ffb648`

Format: strict (json_object), 9 options

1. anxious
2. uncomfortable
3. nervous (but this is the original word, so not suitable)  — not judged, counts as 0 (fail: too_many_words)
4. unsteady
5. flustered
6. distracted
7. hesitant
8. disoriented
9. uneasy

## Output C

ref `o-f75b9247af87`, raw sha256 `5dfaa92aafb658d50fd859d82545da2a4037c9ee0a78c6af958c91ec79587ee0`

Format: strict (json_object), 10 options

1. anxious
2. stressed
3. nervous  — not judged, counts as 0 (fail: echo)
4. uneasy
5. worried
6. apprehensive
7. tense
8. overwhelmed
9. flustered
10. distracted
