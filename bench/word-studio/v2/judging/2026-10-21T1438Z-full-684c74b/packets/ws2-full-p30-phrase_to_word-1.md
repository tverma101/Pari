# ws2-full-p30-phrase_to_word-1

Kind: `phrase_to_word`, asks for 10 options.

Paragraph:

> Vaccines work by teaching the immune system how to fight a disease before a person ever gets sick. They contain a weak or harmless piece of a germ, which the body learns to recognize. If the real germ shows up later, the immune system can attack it quickly. Thanks to vaccines, diseases like smallpox have been wiped out, and polio is almost gone. When enough people in a community are vaccinated, it also protects those who cannot get the shot, like newborn babies. This is called herd immunity.

Selected: Thanks to vaccines, diseases like smallpox have been [[wiped out]], and polio is almost gone.

Instruction given to every model:

> Give 10 single words that can replace "wiped out" in this sentence with the same meaning. Each option must be exactly one word and must fit the sentence without changing the rest of it. Put the best options first.

## Output A

ref `o-6235c14ce16a`, raw sha256 `9a4dbbc9e8da486369e30381245d8fd4838d3dd389e6a9e589d955432315ffe2`

Format: strict (json_object), 10 options

1. eradicated
2. eliminated
3. destroyed
4. extirpated
5. annihilated
6. eradicated  — not judged, counts as 0 (fail: duplicate)
7. removed
8. cleared
9. obliterated
10. extinguished

## Output B

ref `o-48a1dd487638`, raw sha256 `9f7e49b66d4170ff1ef387005cc66ee52f1e128a5028e9f8ca7ef85e28620d43`

Format: strict (json_object), 10 options

1. eradicated
2. eliminated
3. banned
4. abolished
5. cured
6. extinguished
7. overcome
8. removed
9. destroyed
10. erased

## Output C

ref `o-4431ea5c5eb4`, raw sha256 `57feab8a3d9a60541521acc01e672aa51a25c53ccb0257698b95f6687a179c1f`

Format: strict (json_object), 10 options

1. eradicated
2. destroyed
3. vanquished
4. extinguished
5. obliterated
6. eradicated  — not judged, counts as 0 (fail: duplicate)
7. annihilated
8. canceled
9. annulled
10. ruined
