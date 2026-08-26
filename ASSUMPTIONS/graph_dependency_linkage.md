# Project Assumptions

This document outlines the core architectural and graph database assumptions for the retrieval pipeline, bypassing the need for an external reasoning/concept-expansion model.

---

## 1. Concept Dependency Linkage
Instead of implementing an active query expansion reasoner (such as LLM few-shot prompting or LoRA fine-tuning) to map implicit concepts like `"hierarchy"` from queries:

* **Assumption:** Any chunk related to `"emergency procedures"` (or similar emergency mitigation actions) will be modeled to point directly to the `"hierarchy"` concept via a `DEPENDS_ON` relationship in the graph database.
* **Graph Structure:**
  ```
  (c:Chunk) -[:PROVIDES]-> (conceptA:Concept {name: "emergency procedures"})
  (c:Chunk) -[:DEPENDS_ON]-> (conceptB:Concept {name: "hierarchy"})
  ```
* **Retrieval Path:** When the lexical Lucene engine matches `"emergency procedures"`, the multi-hop Cypher traversal query `MATCH path = (node)-[:PROVIDES|DEPENDS_ON*1..3]-(c:Chunk)` will naturally traverse the relationships to retrieve chunks connected to `"hierarchy"` within the 3-hop limit.
