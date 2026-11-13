Policy graph against passage retrieval on 32 questions about policy v2.5 (versions stored: v2.5, v2.6): 9 dev questions, used while the graph's recognition of questions was built, and 23 test questions written afterwards. Embedding model: `nomic-embed-text`. Evidence: every passage the question rests on is in the context. Derived: the graph's facts state the answer, checked against their values (passage retrieval states none). Questions written by the authors.

| Method | Questions | Evidence complete | Derived answer stated | Passages | Characters |
|---|---|---|---|---|---|
| lexical | dev | 4/9 | – | 5.0 | 1576 |
| lexical, all versions | dev | 3/9 | – | 5.0 | 1356 |
| dense | dev | 4/9 | – | 5.0 | 1581 |
| hybrid | dev | 3/9 | – | 5.0 | 1679 |
| graph | dev | 8/9 | 9/9 | 3.1 | 1179 |
| graph + lexical | dev | 8/9 | 9/9 | 5.4 | 2082 |
| lexical | test | 11/23 | – | 5.0 | 1580 |
| lexical, all versions | test | 13/23 | – | 5.0 | 1480 |
| dense | test | 12/23 | – | 5.0 | 1525 |
| hybrid | test | 12/23 | – | 5.0 | 1701 |
| graph | test | 21/23 | 17/19 | 2.8 | 1164 |
| graph + lexical | test | 22/23 | 17/19 | 5.3 | 2092 |

Test questions by type (evidence complete; derived answer for the graph methods):

| Method | routing | change | checker | set | multi | single |
|---|---|---|---|---|---|---|
| lexical | 4/5 | 0/5 | 2/4 | 1/3 | 0/2 | 4/4 |
| lexical, all versions | 3/5 | 3/5 | 2/4 | 1/3 | 0/2 | 4/4 |
| dense | 4/5 | 0/5 | 3/4 | 2/3 | 0/2 | 3/4 |
| hybrid | 4/5 | 0/5 | 2/4 | 2/3 | 0/2 | 4/4 |
| graph | 5/5; 5/5 | 4/5; 3/5 | 4/4; 4/4 | 3/3; 3/3 | 2/2; 2/2 | 3/4 |
| graph + lexical | 5/5; 5/5 | 4/5; 3/5 | 4/4; 4/4 | 3/3; 3/3 | 2/2; 2/2 | 4/4 |

Test questions the graph methods did not fully answer:

- T6 (change, graph): derived answer not stated
- T6 (change, graph + lexical): derived answer not stated
- T7 (change, graph): missing 2.1.1@2.6; derived answer not stated
- T7 (change, graph + lexical): missing 2.1.1@2.6; derived answer not stated
- T23 (single, graph): missing 4.4.1@2.5
