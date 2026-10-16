# ws2-screen-p07-condense-1

Kind: `condense`, asks for 5 options.

Paragraph:

> In Macbeth, Shakespeare shows how wanting power too much can destroy a person. At the start of the play, Macbeth is a loyal soldier who fights bravely for King Duncan. After the witches tell him he will be king, he cannot stop thinking about it. Lady Macbeth pushes him to kill Duncan, and he finally agrees even though he feels guilty. Once he becomes king, he keeps killing people because he is afraid of losing what he has. By the end, Macbeth says that life is "a tale told by an idiot," which shows how empty he feels. His story is a warning about what happens when ambition gets out of control.

Selected: Once he becomes king, he keeps killing people because he is afraid of losing what he has.

Instruction given to every model:

> Give 5 different rewrites of the selected text that say the same thing in fewer words. Keep every fact, name, number and quotation, and keep the claim exactly as strong or as uncertain as it is. Put the best options first.

## Output A

ref `o-4a5097262030`, raw sha256 `d92620a6935de6dd13eda739f0ca50e5eb7078a406ddd055335b7f1bbbcbc23d`

Format: lenient (json_object_then_text), 5 options

1. Once he becomes king, he kills because he fears losing what he has.
2. Once he becomes king, he kills to avoid losing what he has.
3. Once he becomes king, he kills out of fear of losing what he has.  — not judged, counts as 0 (fail: duplicate)
4. Once he becomes king, he kills due to fear of losing what he has.  — not judged, counts as 0 (fail: duplicate)
5. Once he becomes king, he kills to guard what he has.  — not judged, counts as 0 (fail: duplicate)

## Output B

ref `o-72582f8389c5`, raw sha256 `71bab4c20c6165a899da62f5c311f34d732ca3bdde7471d137976e5b107f6ed6`

Format: strict (json_object), 5 options

1. Once king, he murders out of fear of losing power.
2. After becoming king, he murders fearing to lose his throne.
3. He kills others fearing to lose his kingdom.
4. As king, he commits murder fearing to lose his position.
5. He kills people fearing to lose his rule

## Output C

ref `o-db93897f2c71`, raw sha256 `604055a0d7981b539f3fb94dd47d25e099ba801252430e4b8be83aaef1fe44bd`

Format: strict (json_object), 5 options

1. Once crowned, Macbeth kills to retain power.
2. As king, Macbeth kills out of fear of loss.
3. King Macbeth murders to avoid losing control.
4. After becoming king, Macbeth fears losing power and kills.
5. King Macbeth kills to prevent losing his throne.

## Output D

ref `o-f01aafdbf482`, raw sha256 `406f2da264cb3f0158f011068eaa1097a6c325762ed7afe67fae2fb8e203dbd7`

Format: strict (json_object), 5 options

1. Once crowned, he continues killing out of fear of losing power.
2. After seizing the crown, he kills out of fear of losing it.
3. Once king, he murders out of fear of losing what he has.
4. Upon becoming king, he kills out of fear of losing his hold.
5. Once he is king, he kills out of fear of losing what he gained.

## Output E

ref `o-8824e3193fc6`, raw sha256 `4f05aa72e006b553733d2a2ff53a4384e96ac5d8458d02630ca9944713436587`

Format: strict (json_object), 5 options

1. Keeps killing because he fears losing what he has.
2. Kills because he fears losing what he has.  — not judged, counts as 0 (fail: duplicate)
3. Killing because he fears losing what he has.  — not judged, counts as 0 (fail: duplicate)
4. Kills to avoid losing what he has.
5. Kills because he fears losing what he has.  — not judged, counts as 0 (fail: duplicate)
