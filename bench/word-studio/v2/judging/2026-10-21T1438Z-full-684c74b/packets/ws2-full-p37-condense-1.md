# ws2-full-p37-condense-1

Kind: `condense`, asks for 5 options.

Paragraph:

> In Animal Farm, George Orwell uses a story about farm animals to show how power can corrupt leaders. After the animals take over the farm, they promise that all animals will be treated the same. Over time, the pigs start giving themselves special privileges, like sleeping in beds and drinking alcohol. Napoleon uses his dogs to scare anyone who questions him, and he changes the rules whenever it helps him. By the end, the other animals cannot tell the difference between the pigs and the humans. Orwell was warning readers that a revolution can end up with the same problems it was trying to fix.

Selected: Over time, the pigs start giving themselves special privileges, like sleeping in beds and drinking alcohol.

Instruction given to every model:

> Give 5 different rewrites of the selected text that say the same thing in fewer words. Keep every fact, name, number and quotation, and keep the claim exactly as strong or as uncertain as it is. Put the best options first.

## Output A

ref `o-bc1997a237d7`, raw sha256 `bc10a24ad2b7b6bd566183a67fd9b62c87a698a2ccc1c9636f776430c6204082`

Format: strict (json_object), 5 options

1. The pigs soon enjoyed special perks, such as sleeping in beds and drinking alcohol.
2. Soon, the pigs acquired special privileges, including beds and alcohol.
3. Over time, the pigs claimed special rights, like beds and alcohol.
4. The pigs gradually took special privileges, such as beds and alcohol.
5. Eventually, the pigs obtained special perks, including beds and alcohol.

## Output B

ref `o-54109aa17f29`, raw sha256 `a3a3bf506bfb5d6bec439a220001d5839effaf42665f0779336fb8d1f89fd0dc`

Format: strict (json_object), 5 options

1. As time goes on, the pigs begin to indulge in luxuries, such as beds and alcohol.  — not judged, counts as 0 (fail: not_shorter)
2. Eventually, the pigs start enjoying special treats, like beds and booze.
3. The pigs gradually start treating themselves to luxuries, including sleeping in beds and drinking alcohol.
4. Over time, the pigs start living luxuriously, sleeping in beds and drinking alcohol.
5. The pigs begin to enjoy privileges, such as sleeping in beds and drinking alcohol, over time.  — not judged, counts as 0 (fail: not_shorter)

## Output C

ref `o-268e970e8f80`, raw sha256 `77a12c7d1c30c078d346dbd230423f6d659cb04ea9b6221c773526bd5fc3d4e5`

Format: lenient (json_object_then_text), 5 options

1. The pigs gained privileges such as sleeping in beds and drinking alcohol.
2. Pigs began to enjoy special privileges, including beds and alcohol.
3. The pigs started enjoying privileges like beds and alcohol.
4. Pigs acquired special benefits, such as beds and alcohol consumption.
5. The pigs began to take for themselves privileges, including beds and alcohol.
