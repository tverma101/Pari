# ws2-full-p47-academic-1

Kind: `academic`, asks for 5 options.

Paragraph:

> I will be the first person in my family to go to college, and that comes with a lot of pressure. My parents did not have the chance to continue their education because they had to start working when they were teenagers. They have always told me that school is the key to a better life. Filling out applications was confusing because no one at home had done it before, so I had to ask my counselor for help with almost every step. Even though the process was hard, it made me more determined to succeed. I want to make my parents proud and show my younger cousins that college is possible for them too.

Selected: My parents did not have the chance to continue their education because they had to start working when they were teenagers.

Instruction given to every model:

> Give 5 different rewrites of the selected text in a more academic register suitable for a school or college essay. Keep the same meaning and the same level of certainty. Do not add evidence, statistics, names, citations or new ideas. Put the best options first.

## Output A

ref `o-c82f2496274d`, raw sha256 `c9dbb76f988a0fbc695c1fbd85331396647690ba94b15377d25d9743a3c07808`

Format: lenient (json_object_then_text), 5 options

1. My parents were unable to pursue further education due to the necessity of entering the workforce at a young age.
2. They did not have the opportunity to continue their education because they had to begin working before they were legally allowed.
3. Their educational pursuits were curtailed by the need to start working as teenagers, preventing them from pursuing higher education.  — check: negation_changed
4. They were forced to abandon their educational ambitions due to the requirement to start working at a young age.  — check: negation_changed
5. The early onset of employment hindered their ability to continue their education.  — check: negation_changed

## Output B

ref `o-7d5446284434`, raw sha256 `32a51e342a1cb3c79353e9aad2799ddc6d26482c3a795442711d2e9a76dd59a2`

Format: strict (json_object), 5 options

1. My parents were compelled to enter the workforce during their teenage years, which prevented them from pursuing further education.  — check: negation_changed
2. My parents were unable to continue their schooling because they were required to begin working while still teenagers.
3. My parents lacked the opportunity to further their education as they were forced to start working during their teenage years.
4. My parents did not have the chance to pursue higher education since they had to commence work as teenagers.
5. My parents were unable to continue their education because they were obliged to start working during their teenage years.

## Output C

ref `o-4bdd3a38bde6`, raw sha256 `8a1f3144c7d527103d8e98adfa426baf439af89b6a0d7592094dc1c40df87c75`

Format: strict (json_object), 5 options

1. My parents were unable to pursue further education as they were required to commence employment during their teenage years.
2. The lack of opportunity for my parents to continue their education stemmed from the necessity for them to begin working at a young age.
3. My parents did not have the chance to continue their education because they had to start working when they were teenagers.  — not judged, counts as 0 (fail: echo)
4. The inability of my parents to continue their education was due to the necessity of starting work during their teenage years.
5. My parents were compelled to begin working during their teenage years, which precluded them from pursuing further education.  — check: negation_changed
