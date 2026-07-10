# Last-Mile LM Reasoning Examples

These examples show the kind of supervision that should help a LoRA/QLoRA model do better at final triple adjudication.

## Example 1: Direct Support

**Assertion**
- `Aspirin | treats | headache`

**Retrieved evidence**
- Chunk 1: "Aspirin treats headache and reduces fever."

**Expected output**
- Label: `supported`
- Reasoning: The exact subject, relation, and object all appear in one chunk.
- Evidence: `chunk_1`

## Example 2: Direct Contradiction

**Assertion**
- `Aspirin | treats | malaria`

**Retrieved evidence**
- Chunk 2: "However, aspirin does not treat malaria."

**Expected output**
- Label: `contradicted`
- Reasoning: The triple appears with explicit negation.
- Evidence: `chunk_2`

## Example 3: Partial Support

**Assertion**
- `Protein X | activates | pathway Y`

**Retrieved evidence**
- Chunk 3: "Protein X is associated with pathway Y."

**Expected output**
- Label: `partial`
- Reasoning: The subject and object are related, but the relation is weaker or not explicit.
- Evidence: `chunk_3`

## Example 4: Multi-Hop Support

**Assertion**
- `Gene A | regulates | Cell response B`

**Retrieved evidence**
- Chunk 4: "Gene A provides transcription factor C."
- Chunk 5: "Transcription factor C depends on pathway D."
- Chunk 6: "Pathway D drives Cell response B."

**Expected output**
- Label: `supported`
- Reasoning: The claim is supported through a chain of intermediate concepts.
- Evidence: `chunk_4`, `chunk_5`, `chunk_6`

## Example 5: Unsupported / Unknown

**Assertion**
- `Compound Z | inhibits | enzyme Q`

**Retrieved evidence**
- Chunk 7: "Compound Z was tested in mice."
- Chunk 8: "Enzyme Q is discussed in the methods section."

**Expected output**
- Label: `unknown`
- Reasoning: The retrieved chunks do not establish the claimed relation.
- Evidence: `chunk_7`, `chunk_8`

## Example 6: Conflicting Evidence

**Assertion**
- `Drug M | reduces | inflammation`

**Retrieved evidence**
- Chunk 9: "Drug M reduces inflammation in vitro."
- Chunk 10: "Drug M failed to reduce inflammation in vivo."

**Expected output**
- Label: `partial`
- Reasoning: There is some support, but also conflicting evidence.
- Evidence: `chunk_9`, `chunk_10`

## Recommended Training Fields

Each training example should include:

- assertion fields:
  - `subject`
  - `relation`
  - `object`
  - `polarity`
- evidence fields:
  - `chunk_id`
  - `text`
  - optional `source`
  - optional graph links like `PROVIDES` and `DEPENDS_ON`
- target fields:
  - `label`
  - `confidence`
  - `rationale`
  - `evidence_chunk_ids`

## What Good Examples Look Like

Good examples are:

- short enough to fit in context
- grounded in the retrieved text
- representative of your real retrieval output
- balanced across supported, contradicted, partial, and unknown
- rich in multi-hop cases when graph reasoning matters

