# ws2-full-p12-condense-1

Kind: `condense`, asks for 5 options.

Paragraph:

> Antibiotics are medicines that kill bacteria, and they have saved millions of lives since they were discovered. The problem is that bacteria can change over time so that the medicine does not work on them anymore. This happens faster when people take antibiotics they do not really need, like for a cold, which is caused by a virus. It also happens when people stop taking their pills early because they start to feel better. If this keeps going, simple infections could become deadly again. To stop this, doctors need to be careful about giving out antibiotics, and patients need to finish the whole treatment.

Selected: This happens faster when people take antibiotics they do not really need, like for a cold, which is caused by a virus.

Instruction given to every model:

> Give 5 different rewrites of the selected text that say the same thing in fewer words. Keep every fact, name, number and quotation, and keep the claim exactly as strong or as uncertain as it is. Put the best options first.

## Output A

ref `o-0e03ded53db7`, raw sha256 `e9525a7afe5086a27bd9860d9a31dc8ccf654c574c44af8084598a67f96d17d7`

Format: strict (json_object), 5 options

1. This happens faster when people take unnecessary antibiotics, such as for a viral cold.  — check: negation_changed
2. This accelerates when antibiotics are used for viral infections, like colds, that are unnecessary.  — check: negation_changed
3. This occurs more rapidly when antibiotics are prescribed for unnecessary viral illnesses, such as colds.  — check: negation_changed
4. This happens more quickly with antibiotics taken for viral causes, like colds, which are not needed.
5. This speeds up when antibiotics are used for unnecessary viral infections, such as colds.  — check: negation_changed

## Output B

ref `o-9a1c8e156f5a`, raw sha256 `941acb0e2bb38006a1792e1dc5b7319a50fed0dab7fcd78907f850d2dc5f6fb0`

Format: strict (json_object), 5 options

1. Taking unnecessary antibiotics, such as for a viral cold, speeds up resistance.  — check: negation_changed
2. Unneeded antibiotics, like for colds, hasten bacterial resistance.  — check: negation_changed
3. Antibiotics for colds, viruses, quicken resistance.  — check: negation_changed
4. Taking antibiotics for colds, viruses, accelerates resistance.  — check: negation_changed
5. Unnecessary antibiotics, like for colds, increase resistance speed.  — check: negation_changed

## Output C

ref `o-5da642128470`, raw sha256 `9986cbace80b40e4fdce61d72f024c987ea458fa1ce7867b3eb2d792a29f92de`

Format: strict (json_object), 5 options

1. Bacteria change over time to resist antibiotics faster when people take them for unnecessary reasons, like colds caused by viruses.  — check: negation_changed
2. The resistance of bacteria to antibiotics accelerates when people use them for viral infections, such as colds.  — check: negation_changed
3. Antibiotic resistance increases when people take antibiotics for viral conditions like the common cold.  — check: negation_changed
4. Bacteria become resistant to antibiotics more quickly when antibiotics are prescribed for viral infections like colds.  — check: negation_changed
5. When people use antibiotics for viral illnesses such as colds, bacteria become resistant more rapidly.  — check: negation_changed
