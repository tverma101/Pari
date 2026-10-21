# ws2-full-p46-condense-1

Kind: `condense`, asks for 5 options.

Paragraph:

> Most people know that exercise is good for the body, but it is also good for the brain. When we exercise, our hearts pump more blood to the brain, which brings it extra oxygen. Studies have shown that regular exercise can improve memory and help people focus. It can also lower stress and make people feel happier because the body releases chemicals called endorphins. Even a short walk of twenty minutes can make a difference. For students, this means that taking breaks to move around might actually help them study better.

Selected: When we exercise, our hearts pump more blood to the brain, which brings it extra oxygen.

Instruction given to every model:

> Give 5 different rewrites of the selected text that say the same thing in fewer words. Keep every fact, name, number and quotation, and keep the claim exactly as strong or as uncertain as it is. Put the best options first.

## Output A

ref `o-be1dd600d1b6`, raw sha256 `b9274d52192441e5078b0c4df7627d01851153b944481976b8551982701f4d41`

Format: strict (json_object), 5 options

1. Our hearts pump more blood to the brain, supplying it with extra oxygen.
2. Exercise increases blood flow to the brain, delivering more oxygen.
3. Pumping more blood to the brain during exercise brings it additional oxygen.
4. The brain receives extra oxygen when more blood is pumped to it during exercise.
5. Exercise causes increased blood flow to the brain, resulting in extra oxygen supply.

## Output B

ref `o-d3bfc53d073e`, raw sha256 `ed57b02efce9a7854053c349fb16059bdef299c93ff9094935f8b242d129597d`

Format: strict (json_object), 5 options

1. Exercise increases blood flow to the brain, delivering extra oxygen.
2. During exercise, our hearts pump more blood to the brain for extra oxygen.
3. When we exercise, our hearts pump more blood to the brain, providing extra oxygen.
4. Exercise causes our hearts to pump more blood to the brain, bringing extra oxygen.
5. When we exercise, our hearts pump more blood to the brain, bringing it extra oxygen.  — not judged, counts as 0 (fail: duplicate)

## Output C

ref `o-d816dcef0765`, raw sha256 `650b0675d4fe0b83cdebfe3f73092006cd2a372dec4bd3d0a5f85145af200d4e`

Format: strict (json_object), 5 options

1. Exercise pumps blood to the brain, providing extra oxygen.
2. During exercise, blood flow to the brain increases, delivering more oxygen.
3. Heartbeats during exercise boost brain oxygenation.
4. Exercise enhances brain oxygen levels by increasing blood flow.
5. Exercise increases brain oxygen supply through better blood circulation.
