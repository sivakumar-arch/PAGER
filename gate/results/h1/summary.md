# H1 result: **GRAY**

Reason: no rule matched; default outcome NARROW unless the review memo records a reason
D* (primary): llm_off; D* (parse failures excluded): llm_off
Outcome under the excluded version: GRAY

| Policy / detector | FA full | FA std | FD_neg full | FD_neg std | FD_all | OR full | OR std | D hop-3 FA/FD/OR |
|---|---|---|---|---|---|---|---|---|
| PROP|llm_off | 18/50 | 18/43 | 0/26 | 0/16 | 5/72 | 4/67 | 3/53 | 0/5/4 |
| PROP|llm_on | 15/50 | 15/43 | 4/26 | 1/16 | 9/72 | 5/63 | 4/52 | 0/5/4 |
| PROP|presidio | 32/50 | 26/43 | 4/26 | 0/16 | 4/72 | 3/68 | 1/56 | 0/0/0 |
| PROP|rule | 18/50 | 18/43 | 6/26 | 0/16 | 10/72 | 3/62 | 3/53 | 0/4/3 |
| REDETECT|llm_off | 23/50 | 23/43 | 0/26 | 0/16 | 5/72 | 4/67 | 3/53 | 0/5/4 |
| REDETECT|llm_on | 20/50 | 20/43 | 3/26 | 1/16 | 8/72 | 6/64 | 4/52 | 0/5/4 |
| REDETECT|presidio | 43/50 | 37/43 | 5/26 | 0/16 | 5/72 | 3/67 | 1/56 | 0/0/0 |
| REDETECT|rule | 25/50 | 25/43 | 6/26 | 0/16 | 10/72 | 3/62 | 3/53 | 0/4/3 |
| SRC|llm_off | 0/50 | 0/43 | 0/26 | 0/16 | 5/72 | 4/67 | 3/53 | 0/5/4 |
| SRC|llm_on | 0/50 | 0/43 | 4/26 | 1/16 | 9/72 | 5/63 | 4/52 | 0/5/4 |
| SRC|presidio | 3/50 | 0/43 | 4/26 | 0/16 | 4/72 | 3/68 | 1/56 | 3/0/0 |
| SRC|rule | 0/50 | 0/43 | 6/26 | 0/16 | 10/72 | 3/62 | 3/53 | 0/4/3 |
| SRC-FC|llm_off | 0/50 | 0/43 | 0/26 | 0/16 | 5/72 | 4/67 | 3/53 | 0/5/4 |
| SRC-FC|llm_on | 0/50 | 0/43 | 4/26 | 1/16 | 9/72 | 5/63 | 4/52 | 0/5/4 |
| SRC-FC|presidio | 3/50 | 0/43 | 4/26 | 0/16 | 4/72 | 3/68 | 1/56 | 3/0/0 |
| SRC-FC|rule | 0/50 | 0/43 | 6/26 | 0/16 | 10/72 | 3/62 | 3/53 | 0/4/3 |

Parse failures per LLM configuration: {"llm_off": 0, "llm_on": 0}
