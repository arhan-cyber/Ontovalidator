# Fine-Tuning vs. Few-Shot Prompting for Implicit Concept Mapping

This document outlines how to train or guide an LLM to predict implicit concepts (such as mapping *"reports to"* to `"hierarchy"`) during query preprocessing.

---

## 1. The Few-Shot Prompting Approach (In-Context Learning)

Instead of training a new model, you supply concrete examples within the prompt. This guides the existing LLM to extract both explicit and implicit ontological concepts.

### Sample System Prompt Setup
```python
system_prompt = """
You are an ontology concept mapper. Your task is to identify implicit concepts needed to answer the query.

Examples:
Query: "Who does the worker report to in an emergency?"
Implicit Concepts: ["hierarchy", "escalation procedures"]

Query: "Is the supervisor allowed to override the system?"
Implicit Concepts: ["access control", "privileges"]

Query: "The worker reports to the emergency mitigator only when an emergency incident occurs"
Implicit Concepts: ["hierarchy", "emergency mitigation procedures"]
"""
```

### Pros & Cons
* **Pros:**
  * Zero setup time (no training pipeline needed).
  * Extremely easy to update or add new rules.
  * Works out-of-the-box with any standard LLM API.
* **Cons:**
  * Increases input token usage (higher cost per query).
  * May degrade in accuracy if you have hundreds of distinct concepts that cannot all fit into the prompt examples.

---

## 2. The Fine-Tuning Approach (LoRA/QLoRA)

If you have a large list of custom domain-specific concepts, you can fine-tune a lightweight base model (like `Qwen2.5-7B-Instruct` or `Llama-3-8B-Instruct`) to learn the mappings directly.

### Step A: Dataset Construction (`dataset.jsonl`)
Prepare a file containing training messages:

```json
{"messages": [{"role": "system", "content": "Identify implicit concepts required for the query."}, {"role": "user", "content": "The worker reports to the emergency mitigator only when an incident occurs."}, {"role": "assistant", "content": "[\"hierarchy\", \"emergency mitigation procedures\"]"}]}
{"messages": [{"role": "system", "content": "Identify implicit concepts required for the query."}, {"role": "user", "content": "Who is responsible for overriding the alarm system?"}, {"role": "assistant", "content": "[\"access control\", \"role privileges\"]"}]}
```

### Step B: Run QLoRA Training
Use a library like `unsloth` or `peft` to run fine-tuning on a single GPU. Here is a minimal PyTorch/PEFT training script layout:

```python
from datasets import load_dataset
from trl import SFTTrainer
from transformers import AutoModelForCausalLM, AutoTokenizer, TrainingArguments
from peft import LoraConfig, get_peft_model

model_id = "Qwen/Qwen2.5-7B-Instruct"
model = AutoModelForCausalLM.from_pretrained(model_id, device_map="auto", load_in_4bit=True)
tokenizer = AutoTokenizer.from_pretrained(model_id)

peft_config = LoraConfig(
    r=16,
    lora_alpha=32,
    target_modules=["q_proj", "v_proj"],
    lora_dropout=0.05,
    bias="none",
    task_type="CAUSAL_LM"
)

training_args = TrainingArguments(
    output_dir="./concept_mapping_lora",
    per_device_train_batch_size=4,
    gradient_accumulation_steps=4,
    learning_rate=2e-4,
    logging_steps=10,
    max_steps=100,
    fp16=True
)

trainer = SFTTrainer(
    model=model,
    train_dataset=load_dataset("json", data_files="dataset.jsonl", split="train"),
    peft_config=peft_config,
    max_seq_length=512,
    tokenizer=tokenizer,
    args=training_args
)

trainer.train()
```

### Pros & Cons
* **Pros:**
  * Ultra-low inference latency and cost (no long system prompt/examples needed).
  * Highly specialized on your specific taxonomy and domain.
* **Cons:**
  * Requires building a dataset (typically 500+ examples).
  * Incurs compute costs to train and host the model.
