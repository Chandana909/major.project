Policy retrieval over 27 passages, 16 questions per group. Embedding model: `nomic-embed-text`. Question rewriting by `qwen2.5-coder:7b`. Default ranking of the application: dense for a question as asked, hybrid for a restated one.

| Ranker | Questions | Recall@1 | Recall@3 | MRR |
|---|---|---|---|---|
| lexical | wording | 1.000 | 1.000 | 1.000 |
| lexical | paraphrase (dev) | 0.062 | 0.250 | 0.234 |
| lexical | paraphrase (test) | 0.250 | 0.312 | 0.340 |
| dense | wording | 0.938 | 1.000 | 0.969 |
| dense | paraphrase (dev) | 0.625 | 0.812 | 0.733 |
| dense | paraphrase (test) | 0.438 | 0.812 | 0.637 |
| hybrid | wording | 1.000 | 1.000 | 1.000 |
| hybrid | paraphrase (dev) | 0.250 | 0.688 | 0.467 |
| hybrid | paraphrase (test) | 0.312 | 0.312 | 0.415 |
| lexical + rewrite | wording | 1.000 | 1.000 | 1.000 |
| lexical + rewrite | paraphrase (dev) | 0.625 | 0.938 | 0.786 |
| lexical + rewrite | paraphrase (test) | 0.625 | 0.812 | 0.750 |
| dense + rewrite | wording | 1.000 | 1.000 | 1.000 |
| dense + rewrite | paraphrase (dev) | 0.625 | 0.875 | 0.763 |
| dense + rewrite | paraphrase (test) | 0.562 | 0.938 | 0.745 |
| hybrid + rewrite | wording | 1.000 | 1.000 | 1.000 |
| hybrid + rewrite | paraphrase (dev) | 0.750 | 0.938 | 0.849 |
| hybrid + rewrite | paraphrase (test) | 0.625 | 0.938 | 0.768 |
