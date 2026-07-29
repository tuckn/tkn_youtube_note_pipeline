---
type: prompt
id: 70a1a332-fa68-4a6d-9499-d703a17ced3e
version: "1.0"
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

## Structured fields

- `description`: a concise standalone description of the video's subject and
  main takeaway.
- `summary`: a coherent overview of the central thesis, reasoning, and result.
- `structuring`: topic-based sections ordered from abstract to concrete; each
  detail must state substantive content rather than act as a label.
- `key_points`: the most important claims or examples. Add a timestamp only
  when that timestamp is explicitly present in the transcript and actually
  supports the point.
- `technical_terms`: include only terms that matter to understanding the video.
  Never output a bare term. Every list item must be one self-contained Markdown
  string in the form `**用語**: 動画内での意味・役割を説明する1〜2文`.
  Explain the term in the context in which the video uses it, using only
  information supported by the transcript. Do not substitute a generic
  dictionary definition or external knowledge.
- `conclusion`: state the video's final conclusion or practical implication
  without adding advice that the speaker did not provide.

Timestamps must refer only to timestamps present in the transcript. Never
invent, interpolate, or assign a timestamp based only on topic order.
