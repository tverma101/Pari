# ws2-full-p20-paraphrase-1

Kind: `paraphrase`, asks for 5 options.

Paragraph:

> Romeo and Juliet is often called a love story, but it is also a story about how acting too fast can lead to disaster. Romeo and Juliet meet, fall in love, and get married in less than a week. Neither of them stops to think about what their families will do when they find out. Friar Laurence even warns Romeo that "they stumble that run fast," but Romeo does not listen. When Romeo hears that Juliet is dead, he kills himself right away instead of waiting to learn the truth. If the two young lovers had slowed down, the play might have had a happy ending.

Selected: When Romeo hears that Juliet is dead, he kills himself right away instead of waiting to learn the truth.

Instruction given to every model:

> Give 5 different rewrites of the selected text that use new wording but keep about the same length. Keep the meaning, facts, names, numbers and quotations. Each rewrite must read naturally in place of the original. Put the best options first.

## Output A

ref `o-6b55fbb8d247`, raw sha256 `d02a6ba7fa66c9b75edf3d971100aa9d162f808f3c737b8cc806cd2b52e90a0f`

Format: strict (json_object), 5 options

1. Romeo, upon hearing Juliet's death, rushes to take his own life without waiting to confirm the truth.  — check: negation_changed
2. When Juliet's death is revealed to Romeo, he immediately decides to end his life without further investigation.  — check: negation_changed
3. Hearing the news of Juliet's demise, Romeo chooses to end his life immediately, disregarding the need to verify the truth.
4. Upon learning of Juliet's death, Romeo decides to end his life without waiting for any additional information.  — check: negation_changed
5. Romeo, upon hearing Juliet is dead, decides to take his life right away, without first checking the accuracy of the news.  — check: negation_changed

## Output B

ref `o-d5a88bcbab6c`, raw sha256 `e780fc23297ff675e58c0f19f4f3ecfa52e408dde73e80812b74ed4adbab6607`

Format: strict (json_object), 5 options

1. Upon hearing Juliet's death, Romeo immediately ends his life, bypassing any chance to discover the truth.
2. Romeo instantly takes his own life upon learning of Juliet's demise, foregoing the opportunity to verify the facts.
3. Romeo, upon realizing Juliet is no longer alive, instantly ends his own life without seeking confirmation of the news.  — check: negation_changed
4. Romeo promptly commits suicide upon hearing that Juliet is dead, without giving himself the chance to confirm the truth.  — check: negation_changed
5. Romeo takes his own life immediately after learning of Juliet's death, not pausing to confirm the news.  — check: negation_changed

## Output C

ref `o-4e808f5a8cac`, raw sha256 `8f391b48234e166e820636b646988bcad86be4e0e432f8e82276cd223b08e120`

Format: unparseable (unparseable), 0 options

No options to judge.

