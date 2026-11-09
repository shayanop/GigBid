| Source | Precision | Recall |
| --- | --- | --- |
| hand-written case study | 0.961 | 0.658 |
| README | 0.000 | 0.000 |
| code detector | 0.809 | 0.940 |
| case study + code detector | 0.818 | 0.993 |
| model summary, before verification | 0.807 | 0.899 |
| model summary, after verification | 0.807 | 0.899 |

| Index | Recall@5 | MRR | nDCG@10 | Recall@5, jobs with a repo project | p95 ms |
| --- | --- | --- | --- | --- | --- |
| without verified case studies | 0.595 | 0.717 | 0.629 | 0.584 (n=498) | 26 |
| with verified case studies | 0.591 | 0.721 | 0.628 | 0.581 (n=498) | 25 |
