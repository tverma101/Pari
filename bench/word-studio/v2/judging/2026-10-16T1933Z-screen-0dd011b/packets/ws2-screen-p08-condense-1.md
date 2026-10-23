# ws2-screen-p08-condense-1

Kind: `condense`, asks for 5 options.

Paragraph:

> Last summer I got my first job working at a small pizza restaurant near my house. At first I thought it would be easy, but I quickly found out that it was a lot of work. On busy nights we had to make dozens of pizzas in just a few hours, and customers got upset if their food was late. My manager, Tony, taught me how to stay calm and do one thing at a time. I also learned how to talk to people who were angry without getting angry myself. The job was tiring, but it showed me that I can handle stress better than I thought. These skills will help me in college and in any job I have in the future.

Selected: On busy nights we had to make dozens of pizzas in just a few hours, and customers got upset if their food was late.

Instruction given to every model:

> Give 5 different rewrites of the selected text that say the same thing in fewer words. Keep every fact, name, number and quotation, and keep the claim exactly as strong or as uncertain as it is. Put the best options first.

## Output A

ref `o-b8c84e6fba3a`, raw sha256 `e89a4ac5df8b0b5a756cc9cf8453b5e62a403addd2b90fecae08364fc773ec5f`

Format: strict (json_object), 5 options

1. On busy nights, we made dozens of pizzas quickly, causing customer frustration if delayed.
2. Busy nights required dozens of pizzas in a few hours, leading to customer complaints if late.
3. During peak hours, we produced dozens of pizzas in a short time, upsetting customers with late food.
4. We made dozens of pizzas in just a few hours on busy nights, frustrating customers if late.
5. On busy nights, dozens of pizzas were made in a few hours, upsetting customers if delayed.

## Output B

ref `o-3732c2c5b8f5`, raw sha256 `3ba53075361d7d5065d0c4a33a501563d96e05420a5112e4b212f1171d6aa7ee`

Format: strict (json_object), 5 options

1. On busy nights, we made dozens of pizzas in a few hours, and customers got upset if their food was late.
2. We made dozens of pizzas in a few hours on busy nights, and customers got upset if their food was late.  — not judged, counts as 0 (fail: duplicate)
3. On busy nights, customers got upset if their food was late because we had to make dozens of pizzas in a few hours.
4. We had to make dozens of pizzas in a few hours on busy nights, and customers got upset if their food was late.  — not judged, counts as 0 (fail: duplicate)
5. Customers got upset if their food was late on busy nights when we had to make dozens of pizzas in a few hours.

## Output C

ref `o-aa1588b72c10`, raw sha256 `7da221d6c53ec4dd883407765c8f7f49ae173a5c1b712d576aae36236f7a2a00`

Format: strict (json_object), 5 options

1. Busy nights required making dozens of pizzas in hours, leaving customers upset over delays.
2. During busy nights, we made dozens of pizzas quickly, frustrating customers with late food.
3. On busy nights, dozens of pizzas had to be made in hours, causing customer anger due to lateness.
4. We made dozens of pizzas in just a few hours on busy nights, and customers grew upset about the delays.
5. Busy nights demanded dozens of pizzas be made in hours, resulting in upset customers from late food.

## Output D

ref `o-65cddd4170c4`, raw sha256 `4d7b2b0cf313dfbe142a60977c333d5c38b125c1ff3ac213f60f7377734eaffc`

Format: lenient (json_object_then_text), 5 options

1. We made dozens of pizzas in a few hours on busy nights, causing upset customers if late.
2. On busy nights, we had to produce dozens of pizzas in a short time, frustrating customers with late deliveries.
3. Busy nights required us to make dozens of pizzas quickly, leading to angry customers if late.
4. On busy nights, we produced dozens of pizzas in just a few hours, which upset customers if late.
5. Making dozens of pizzas in a short time on busy nights often resulted in angry customers due to late deliveries.

## Output E

ref `o-aa9145ee0596`, raw sha256 `cb72e0780aeea7304b1fff4bd7e5a2b15fb08ba40ee3c9fc42e5c0347d18b0d9`

Format: strict (json_object), 5 options

1. Pizza rush was intense.
2. Late food caused anger.
3. Dozens of pizzas in few hours.
4. Rush led to customer upset.
5. Fast pizza making caused upset.
