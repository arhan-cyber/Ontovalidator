# Last-Mile LM Reasoning Assumptions

This document captures the assumptions for using a language model only at the final adjudication stage of the pipeline.

## Assumption 1: Retrieval is Good Enough
We assume the retrieval layer already returns mostly relevant evidence chunks.

- Lexical retrieval finds exact or near-exact text matches.
- Semantic retrieval finds paraphrases or conceptually related chunks.
- Graph retrieval finds multi-hop supporting context through `PROVIDES` and `DEPENDS_ON`.

This means the LM is not expected to search the whole document corpus. It only reasons over a small candidate set.

## Assumption 2: The LM Is a Last-Mile Reasoner
We assume the LM is used only after candidate evidence has already been assembled.

- It does not replace retrieval.
- It does not replace graph traversal.
- It does not decide what evidence to collect.

Its job is to read the retrieved evidence and decide whether the assertion is supported, contradicted, partially supported, or unknown.

## Assumption 3: Structured Context Is Provided
We assume the LM receives evidence in a structured form.

- The assertion fields are explicit: `subject`, `relation`, `object`, and optionally `polarity`.
- Retrieved chunks are included with chunk IDs and text.
- Graph relationships such as `PROVIDES` and `DEPENDS_ON` are included when available.

This is meant to help the LM perform multi-hop reasoning instead of free-form guessing.

## Assumption 4: The LM Should Be Constrained to Evidence
We assume the LM should only reason from the supplied evidence.

- It should cite or reference the relevant chunk IDs.
- It should not invent missing facts.
- It should not use outside knowledge unless that is explicitly allowed by policy.

## Assumption 5: Fine-Tuning Can Improve the Last Mile
We assume supervised fine-tuning with LoRA or QLoRA may improve the LM on this specific task.

- The target behavior is evidence-based adjudication.
- The target output is a stable label plus rationale.
- The training set should reflect the retrieval style and graph structure used by the system.

## Assumption 6: Retrieval Errors Still Matter
We assume fine-tuning will not fix bad retrieval.

- If the right chunks are not retrieved, the LM cannot reliably recover the answer.
- The model can only reason over the evidence it sees.

## Assumption 7: Heuristics Remain Useful
We assume the heuristic adjudication path remains as a baseline.

- It is useful for easy cases.
- It is useful as a fallback when the LM is uncertain or unavailable.
- It provides a comparison point for evaluating the LM.

## Working Policy
Recommended operating policy:

1. Retrieve candidate chunks.
2. Expand via graph evidence when needed.
3. Use heuristic scoring for obvious cases.
4. Invoke the LM only for ambiguous, partial, or multi-hop cases.
5. Store the heuristic verdict and LM verdict separately when possible.

