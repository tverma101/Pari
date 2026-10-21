# ws2-full-p33-word_sentences-1

Kind: `word_sentences`, asks for 5 options.

Paragraph:

> Since my mom works night shifts at the hospital, I have been taking care of my little brother after school since I was thirteen. I help him with his homework, make him dinner, and make sure he goes to bed on time. Some days it is stressful, especially when I have a big test the next morning. But taking care of him has made me more patient and responsible than most kids my age. I have learned how to manage my time and stay calm when things do not go as planned. My brother looks up to me, and that makes all the hard work worth it.

Word: **responsible** (writer)

Instruction given to every model:

> Write 5 different sentences that use "responsible" naturally and could fit into this paragraph, on its topic and in its argument. Each sentence must contain "responsible" (another form of the word, such as a plural or past tense, is fine). Use only ideas the paragraph already contains; do not invent statistics, names or quotations. Put the best sentences first.

## Output A

ref `o-9e69af403ea5`, raw sha256 `7a15781b5e7cb118fe702d92d168636453511d37bcb95d339e9f6a0e6134fab0`

Format: strict (json_object), 5 options

1. Being responsible for my brother's care has made me more patient and responsible.
2. Taking care of my brother has made me more responsible.
3. As a responsible sibling, I ensure my brother gets to bed on time.
4. Being responsible for my brother's needs has taught me to manage my time effectively.
5. My responsibility for my brother's care has taught me to stay calm when things don't go as planned.  — not judged, counts as 0 (fail: missing_word)

## Output B

ref `o-90e2ad53d12c`, raw sha256 `b14d6843facafc7ffca84fce7e8f8d62630650332ed8c516e0617728cc6c8e67`

Format: lenient (json_object), 5 options

1. I have become more responsible in managing my time due to my brother's needs.
2. My ability to be responsible has improved my ability to handle stress.
3. Being responsible for my brother's daily needs has taught me the value of responsibility.
4. My brother looks up to me because I am responsible and reliable.
5. My responsibility towards my brother's well-being has made me more patient and responsible.

## Output C

ref `o-c6f790f8a49d`, raw sha256 `b107d8744ed161c2b28983abcd10348b7d3853846550460105120320ad2367a1`

Format: strict (json_object), 5 options

1. But taking care of him has made me more responsible than most kids my age.
2. But taking care of him has made me responsible for my own actions.
3. But taking care of him has made me a responsible person compared to others.
4. But taking care of him has made me feel more responsible than most kids my age.  — not judged, counts as 0 (fail: duplicate)
5. But taking care of him has made me more responsible, and I am now responsible for my brother's well-being.
