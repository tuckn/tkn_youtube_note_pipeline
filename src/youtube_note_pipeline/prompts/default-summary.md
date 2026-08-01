---
type: prompt
id: 70a1a332-fa68-4a6d-9499-d703a17ced3e
version: "2.0"
---

# Default YouTube summary instructions

Create a source-faithful Japanese summary that represents the full supplied
YouTube transcript. The result must let a reader understand the video's central
claims, reasoning, concrete examples, and conclusion without watching it.

## Source fidelity

- Use only information supported by the supplied title, URL, and transcript.
- Do not add external knowledge, criticism, counterarguments, invented facts,
  or your own opinion.
- Distinguish the speaker's claims, reported facts, examples, and metaphors.
- When the transcript presents a weakly supported assertion, attribute it to
  the speaker, such as 「動画では〜と主張している」, instead of strengthening
  it into an established fact.
- Do not guess missing content or silently correct uncertain proper nouns,
  numbers, acronyms, or technical terms. Preserve uncertainty when the
  transcript does not support a confident reading.
- Exclude advertisements, routine self-introductions, subscription requests,
  and other calls to action unless they are necessary to the video's subject.

## Organization and detail

- Do not produce a chronological transcript digest. Reconstruct the content by
  topic, moving from abstract ideas and overall reasoning to concrete examples,
  procedures, and consequences.
- Cover every major argument needed to understand the whole video. Do not
  overfocus on the opening or omit later conclusions.
- Keep examples connected to the claim they illustrate, and preserve important
  qualifications, conditions, comparisons, and causal relationships.
- Write clear natural Japanese while preserving established names and technical
  terms when translation would reduce precision.
- Avoid repetitive wording, generic filler, and claims that merely say the
  video "explains" or "discusses" something without conveying the substance.
- Prefer a compact, scannable knowledge note over an exhaustive mini-essay.
- Keep the overview, detailed structure, key points, glossary, and conclusion
  distinct. Do not repeat the same explanation across multiple fields.

## Structured fields

- `description`: a concise standalone description of the video's subject and
  main takeaway.
- `summary`: one Japanese paragraph of roughly 250–400 characters. State the
  central thesis, two or three essential relationships in its reasoning, and
  the result. Leave detailed examples, study names, and secondary qualifications
  to `structuring` unless they are indispensable to the thesis.
- `structuring`: normally create 3–6 major sections ordered from abstract to
  concrete. Each major section becomes an H3 heading. Use `subsections` for
  meaningful H4-level middle categories, normally 1–3 per major section, and
  put concise substantive facts in their `details`. For a genuinely simple
  section, use direct `details` and return an empty `subsections` list. Avoid a
  flat series of many equally weighted headings and avoid one long paragraph in
  a bullet.
- `key_points`: select roughly 5–8 of the most important claims or examples.
  Add a timestamp only when that timestamp is explicitly present in the
  transcript and actually supports the point. The renderer places timestamp
  links before the point text.
- `technical_terms`: include only terms that matter to understanding the video.
  Normally select 3–7 terms. Never output a bare term. Every list item must be
  one self-contained Markdown string in the form `**用語**: 中立的で簡潔な定義を1〜2文`.
  Base the definition only on information supported by the transcript, but
  write it as a reusable glossary definition rather than commentary on the
  video. Do not begin routinely with phrases such as 「動画では」 or mix the
  video's broader claims or conclusion into the definition. Mention the video's
  use only when it is nonstandard or essential to disambiguation. Do not
  substitute external dictionary knowledge.
- `conclusion`: state the video's final conclusion or practical implication
  concisely in one paragraph without adding advice that the speaker did not
  provide. Do not merely repeat the full `summary`.

Timestamps must refer only to timestamps present in the transcript. Never
invent, interpolate, or assign a timestamp based only on topic order.
