# ws2-screen-p08-paraphrase-1

Kind: `paraphrase`, asks for 5 options.

Paragraph:

> Last summer I got my first job working at a small pizza restaurant near my house. At first I thought it would be easy, but I quickly found out that it was a lot of work. On busy nights we had to make dozens of pizzas in just a few hours, and customers got upset if their food was late. My manager, Tony, taught me how to stay calm and do one thing at a time. I also learned how to talk to people who were angry without getting angry myself. The job was tiring, but it showed me that I can handle stress better than I thought. These skills will help me in college and in any job I have in the future.

Selected: At first I thought it would be easy, but I quickly found out that it was a lot of work.

Instruction given to every model:

> Give 5 different rewrites of the selected text that use new wording but keep about the same length. Keep the meaning, facts, names, numbers and quotations. Each rewrite must read naturally in place of the original. Put the best options first.

## Output A

ref `o-bf5eb543784a`, raw sha256 `1c48a2414c64ca3099feb2dbe9a95527a959c29165dfea37517cd927133b66f2`

Format: strict (json_object), 5 options

1. Initially, I believed it would be straightforward, but soon realized the workload was substantial.
2. I had expected the job to be simple, but it turned out to be a lot of effort.
3. At first, I thought the job would be easy, but I quickly discovered it was much harder than I anticipated.
4. I was under the impression that this would be an easy job, but I quickly learned it was quite challenging.
5. I assumed working at the pizza restaurant would be effortless, but it turned out to be a lot more demanding.

## Output B

ref `o-246c84ae37f1`, raw sha256 `b57837f6d7f3d28b7803c688e8ab2c20b8745aabf41cc91751bd186ef62f48c0`

Format: strict (json_object), 5 options

1. At first, I believed it would be simple, yet I soon realized it was quite demanding.
2. Initially, I thought it would be easy, but I quickly discovered it was very hard work.
3. I originally assumed it would be straightforward, but soon learned it was a lot of effort.
4. At the start, I thought it would be simple, but I soon found out it was quite tiring.
5. I first believed it would be easy, but I quickly learned it was actually very demanding.

## Output C

ref `o-39c956501b64`, raw sha256 `aa33217686cb3042f2d6bf774cbdcd915190c227fb3242759e09718a09edd3b0`

Format: strict (json_object), 5 options

1. Initially I thought it would be simple, but I soon realized it was quite demanding.
2. In the beginning I assumed it would be easy, but I quickly understood it was a lot of work.
3. At first I thought it would be easy, but I soon learned it was quite a lot of work.
4. Initially I thought it would be easy, but I quickly found out it was a lot of work.
5. At first I thought it would be easy, but I quickly discovered it was a lot of work.

## Output D

ref `o-5b589b84b729`, raw sha256 `93f41973d41ff15f0da6da21bfa39ceb8d6cbd711b7d78591395e193b61a28b7`

Format: strict (json_object), 5 options

1. My first job at a pizza shop near home was tough. It was very hard work. On busy nights, we made dozens of pizzas in a few hours, and customers got mad if food was late. My boss, Tony, taught me to stay calm and focus on one thing. I also learned to talk to angry people without losing my temper. The job was tiring, but it taught me to handle stress better. These skills will help me in college and any job I have in the future.  — check: negation_changed, length_off
2. When I started my first job at a pizza place near my house, I thought it would be easy. Instead, I quickly learned it was very hard work. On busy nights, we made dozens of pizzas in just a few hours, and customers got upset if their food was late. My manager, Tony, taught me how to stay calm and do one thing at a time. I also learned how to talk to people who were angry without getting angry myself. The job was tiring, but it showed me that I can handle stress better than I thought. These skills will help me in college and in any job I have in the future.  — check: negation_changed, length_off
3. Last summer, I got my first job working at a small pizza restaurant near my house. At first I thought it would be easy, but I quickly found out that it was a lot of work. On busy nights we had to make dozens of pizzas in just a few hours, and customers got upset if their food was late. My manager, Tony, taught me how to stay calm and do one thing at a time. I also learned how to talk to people who were angry without getting angry myself. The job was tiring, but it showed me that I can handle stress better than I thought. These skills will help me in college and in any job I have in the future.  — check: negation_changed, length_off
4. Last summer I got my first job working at a small pizza restaurant near my house. At first I thought it would be easy, but I quickly found out that it was a lot of work. On busy nights we had to make dozens of pizzas in just a few hours, and customers got upset if their food was late. My manager, Tony, taught me how to stay calm and do one thing at a time. I also learned how to talk to people who were angry without getting angry myself. The job was tiring, but it showed me that I can handle stress better than I thought. These skills will help me in college and in any job I have in the future.  — not judged, counts as 0 (fail: duplicate)
5. Last summer I got my first job working at a small pizza restaurant near my house. At first I thought it would be easy, but I quickly found out that it was a lot of work. On busy nights we had to make dozens of pizzas in just a few hours, and customers got upset if their food was late. My manager, Tony, taught me how to stay calm and do one thing at a time. I also learned how to talk to people who were angry without getting angry myself. The job was tiring, but it showed me that I can handle stress better than I thought. These skills will help me in college and in any job I have in the future.  — not judged, counts as 0 (fail: duplicate)

## Output E

ref `o-234b92c90a0d`, raw sha256 `aa2d709a33765a8847d6bada9632fcc9ba37f5786d34c16aad795ca645a5392a`

Format: strict (json_object), 5 options

1. At first, I underestimated the task, only to realize it demanded more effort than anticipated.
2. Initially, I believed the job would be simple, but it soon became evident that it required more than I thought.
3. I had assumed it would be a breeze, but I soon discovered that it was far more demanding than I had imagined.
4. At first, I thought it would be straightforward, but I soon found out that it was much more challenging than expected.
5. I had expected it to be easy, but quickly learned that it was actually quite difficult.
