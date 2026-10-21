# ws2-full-p29-phrase_to_word-1

Kind: `phrase_to_word`, asks for 10 options.

Paragraph:

> The fight for women's right to vote in the United States lasted for more than seventy years. It officially began at the Seneca Falls Convention in 1848, where activists like Elizabeth Cady Stanton demanded equal rights for women. For decades, suffragists gave speeches, marched in parades, and even went to jail for their cause. Many people at the time thought that women were too emotional to make decisions about politics. Finally, in 1920, the 19th Amendment was passed, which gave women the right to vote. This victory showed that ordinary people can change the law if they keep pushing for it.

Selected: This victory showed that ordinary people can change the law if they [[keep pushing for it]].

Instruction given to every model:

> Give 10 single words that can replace "keep pushing for it" in this sentence with the same meaning. Each option must be exactly one word and must fit the sentence without changing the rest of it. Put the best options first.

## Output A

ref `o-a401a5e24544`, raw sha256 `82526fc65402d6aee9acdf2dd77a17afcb2710f25fd17171472fd6bd9bc7688c`

Format: strict (json_object), 10 options

1. persisting
2. striving
3. advocating
4. laboring
5. pushing
6. persist
7. strive
8. advocate
9. pressing
10. continuing

## Output B

ref `o-56fe219a77fc`, raw sha256 `d1c080af33880ff02bfd5902defd9582ff5e0fd2ebb54588d850f67564050c1b`

Format: strict (json_object), 10 options

1. persist
2. continue
3. maintain
4. adhere
5. pursue
6. hold on  — not judged, counts as 0 (fail: too_many_words)
7. fight for  — not judged, counts as 0 (fail: too_many_words)
8. strive for  — not judged, counts as 0 (fail: too_many_words)
9. champion
10. defend

## Output C

ref `o-02a14255fa59`, raw sha256 `c5409d41929a006b54c1db5cf489d14f0659cff393290185224042e3ebaaf01f`

Format: strict (json_object), 10 options

1. persist
2. continue
3. maintain
4. continue  — not judged, counts as 0 (fail: duplicate)
5. advocate
6. urge
7. encourage
8. strive
9. push
10. fight
