# Agent Seer Rubric & Scoring Guide

## 1. Tool-Calling Correctness (TC) Rubric

The Tool-Calling Correctness ($TC$) score evaluates an agent's execution transcript across four top-level dimensions composed of 14 sub-dimensions:

### Dimensions & Sub-Dimensions (0–10 Scale)

1. **Usage:**
   - `necessity` (Direct score): Was tool calling genuinely necessary to satisfy the prompt?
   - `overuse` (Diagnostic): Did the agent issue unnecessary or redundant tool calls?
2. **Selection:**
   - `correctness`: Were the chosen tools functionally capable of solving the task?
   - `specificity`: Did the agent pick the most specific, targeted tool available?
   - `completeness`: Were all necessary tools invoked?
3. **Ordering:** *(N/A if only 1 tool was called)*
   - `sequence_logic`: Logical step-by-step progression.
   - `dependency_handling`: Outputs of upstream calls correctly piped into downstream inputs.
   - `execution_efficiency`: Optimal ordering without redundant loops.
4. **Arguments:**
   - `completeness`: All required and necessary parameters provided.
   - `name_accuracy`: Parameter keys match the schema exactly.
   - `value_accuracy`: Parameter values are correct, grounded, and valid.
   - `type_compliance`: Correct JSON types (string, number, array, boolean).
   - `format_compliance`: Adherence to string formats, regexes, and enums.
   - `relevancy`: Parameters align with the user prompt intent.

---

## 2. Mathematical Normalization & Aggregation

Each sub-dimension score $s \in [0, 10]$ is normalized:
$$\text{norm}_{10}(s) = \max\left(0, \min\left(1, \frac{s}{10}\right)\right)$$

Dimension scores:
$$\text{Usage} = \text{norm}_{10}(\text{necessity})$$
$$\text{Selection} = \frac{1}{3} \sum_{k \in \{\text{correctness}, \text{specificity}, \text{completeness}\}} \text{norm}_{10}(s_k)$$
$$\text{Arguments} = \frac{1}{6} \sum_{k \in \{\text{completeness}, \text{name\_acc}, \text{val\_acc}, \text{type\_comp}, \text{fmt\_comp}, \text{relevancy}\}} \text{norm}_{10}(s_k)$$
$$\text{Ordering} = \frac{1}{3} \sum_{k \in \{\text{seq\_logic}, \text{dep\_handling}, \text{exec\_eff}\}} \text{norm}_{10}(s_k) \quad (\text{when applicable})$$

Overall Tool-Calling score ($D = 3$ if single-call, $D = 4$ if multi-call):
$$TC = \frac{1}{D} \sum_{d \in \{\text{Usage}, \text{Selection}, \text{Arguments}, [\text{Ordering}]\}} d$$

---

## 3. Cascading Penalty Collapse Rules

To prevent broken tool calls from receiving passing grades due to arithmetic averaging:
1. **Invalid Parameter Name or Missing Required Parameter:**
   - `name_accuracy` $= 0$
   - Cascades near-zero scores ($0 \le s \le 2$) to `value_accuracy`, `type_compliance`, and `format_compliance`.
2. **Invalid Parameter Value (Capability Violation or Illegal Enum):**
   - `value_accuracy` $\le 2$
   - Cascades near-zero scores ($0 \le s \le 2$) to `type_compliance`, `format_compliance`, and `relevancy`.
