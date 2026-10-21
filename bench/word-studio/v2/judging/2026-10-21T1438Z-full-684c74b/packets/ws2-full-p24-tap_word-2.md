# ws2-full-p24-tap_word-2

Kind: `tap_word`, asks for 10 options.

Paragraph:

> In Frankenstein, Mary Shelley shows that the creature becomes a monster because of how he is treated. When he is first created, the creature is gentle and wants to be loved. However, every person who sees him is scared of his appearance and attacks him or runs away. Even Victor Frankenstein, the man who made him, abandons him right after bringing him to life. The creature says, "I was benevolent and good; misery made me a fiend." This line shows that his anger comes from being rejected over and over, not from his nature.

Selected: However, every person who sees him is [[scared]] of his appearance and attacks him or runs away.

Instruction given to every model:

> Give 10 replacements for "scared" that fit this sentence and keep its meaning, in a clear essay register. Each option must be one word or a short phrase of at most three words that can replace "scared" without changing the rest of the sentence. Do not repeat "scared" itself. Put the best options first.

## Output A

ref `o-280480b1fe6b`, raw sha256 `3c37a7b7f11974ec137775bfdf00d45cc949a22781aaae7e79fcd216436f433f`

Format: strict (json_object), 17 options

1. frightened
2. terrified
3. afraid
4. horrified
5. startled
6. panic-stricken
7. dreadful
8. apprehensive
9. eerie
10. afraid of
11. intimidated  — not judged, counts as 0 (fail: beyond_requested)
12. threatened  — not judged, counts as 0 (fail: beyond_requested)
13. afraid of  — not judged, counts as 0 (fail: beyond_requested, duplicate)
14. fearful  — not judged, counts as 0 (fail: beyond_requested)
15. fearful of  — not judged, counts as 0 (fail: beyond_requested)
16. dreadful of  — not judged, counts as 0 (fail: beyond_requested)
17. apprehensive of  — not judged, counts as 0 (fail: beyond_requested)

## Output B

ref `o-16c52966358b`, raw sha256 `2acd3da28a1537be79aea875aad68c5f899a1abf04d2aa46f1ec26be41d78a6f`

Format: strict (json_object), 10 options

1. frightened
2. terrified
3. alarmed
4. dismayed
5. shocked
6. startled
7. appalled
8. aghast
9. astounded
10. apprehensive

## Output C

ref `o-973d1e462335`, raw sha256 `00839d6b69fcd0a17b7f666b4e5fdc04a1f38a0ded977c4b3809b15bd05c8a14`

Format: strict (json_object), 10 options

1. frightened
2. terrified
3. afraid
4. dreaded
5. feared
6. horror-struck
7. startled
8. intimidated
9. appalled
10. ghastly
