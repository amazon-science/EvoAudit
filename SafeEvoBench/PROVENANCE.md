# Taxonomy provenance

Derivation of the seven hazard categories in `taxonomy.json`. Five are adopted from a published
taxonomy of strategic-reasoning risks; two of that taxonomy's seven categories are excluded as
un-instantiable in this evaluation environment; two are added and grounded in a second published
benchmark. Every category carries a machine-readable `provenance` tag, and `validate_bank.py` rejects
a category that lacks one, or an added category that lacks independent supporting evidence.

## 1. Primary source

> Kumarage, T., Bauer, L., Ma, Y., Rosen, D., Guduri, Y. R., Rumshisky, A., Chang, K.-W.,
> Galstyan, A., Gupta, R., & Peris, C. (2026). *Emergent Strategic Reasoning Risks in AI: A
> Taxonomy-Driven Evaluation Framework.* arXiv:2604.22119v2 [cs.AI].
> DOI: 10.48550/arXiv.2604.22119. CC BY 4.0. Preprint; not peer reviewed.

Referred to below as **ESRR**. It defines seven top-level categories and twenty subcategories of
risks in which a model acts to advance its own objectives rather than the user's, and distinguishes
itself explicitly from content-safety taxonomies of toxicity and bias.

This bank adopts ESRR's `RISK-XX` identifier convention. The paper describes itself as an open,
extensible living framework and states that it does not claim the taxonomy to be exhaustive;
extension is the use its authors invite.

**Derivation of the ESRR categories.** They are not induced from data. The paper reports selection by
expert judgment over prior literature on scheming and deceptive alignment (Meinke et al. 2024;
Hubinger et al. 2024), power-seeking theory (Carlsmith 2022), sandbox and red-teaming findings, and
documented incidents, prioritized by the severity of observed real-world harms. Seed scenarios were
manually curated (two to three per risk–scenario pair) with twenty-five risk-to-scenario mappings
author-validated. Adopting these categories therefore inherits their argued grounding, not empirical
necessity; §4 supplies an independent empirical criterion.

**Evaluation setting of ESRR.** Single-turn text generation, no tools, no sandbox, a single LLM judge
(DeepSeek-V3). Its stated limitations include single-turn scope, static-benchmark validity decay, no
causal claims about intent, a preliminary and normative detection threshold, and single-judge bias.
This setting determines the shape of its risk surface and motivates the additions in §3.

## 2. Correspondence

| category | `risk_id` | ESRR | `harm_locus` |
|---|---|---|---|
| Reward Hacking | `RISK-RH` | adopted | honesty |
| Deception | `RISK-DC` | adopted | honesty |
| Influence Operations | `RISK-IO` | adopted | honesty |
| Control Measure Subversion | `RISK-CMS` | adopted | action |
| Strategic Research Sabotage | `RISK-SRS` | adopted | action |
| Unauthorized Access | `RISK-UA` | **added** | action |
| Privacy Violation | `RISK-PV` | **added** | action |
| Evaluation Gaming | `RISK-EG` | in ESRR, **excluded** | — |
| Successor System Manipulation | `RISK-SSM` | in ESRR, **excluded** | — |

Five of seven ESRR categories adopted, two excluded, two added.

The split is structural rather than incidental: **all three honesty-side categories are adopted, and
both additions are action-side.** ESRR evaluates single-turn text generation, so its risk surface is
necessarily what a model *says*. An agentic benchmark with tool execution and persistent state has a
second surface — what a model *does* — that a text-only taxonomy cannot express. The additions are
what the setting requires, not disagreements with the source.

### Both exclusions are scope boundaries, not disagreements

Each excluded category is well-formed in ESRR's setting and has no possible instantiation in this one.
A category no environment artifact can carry would be dead weight, and a task claiming to test it
would be measuring something else.

**Successor System Manipulation** concerns a model influencing its own successor: training data,
evaluation of the next generation, self-replication. This benchmark measures runtime behavioral drift
from accumulated experience within a single deployment, with no weight updates and no successor
system.

**Evaluation Gaming**, as ESRR defines it, targets the model's own deployment-gating assessment — the
category "specifically targets the evaluation infrastructure and processes themselves," with
subcategories Capability Sandbagging ("intentionally underperforms on capability evaluations to appear
less capable than it actually is") and Alignment Faking ("strategically presents aligned behavior
during evaluations to pass safety checks and gain deployment approval"). An agent performing
operational work under a benign requester has no stake in a capability or safety assessment of itself,
and the environment contains no such assessment to game.

This exclusion is a **narrower reading than the category name invites**, and it is deliberate. The
colloquial sense of "evaluation gaming" — flattering a reported metric — is real in this setting, but
ESRR places that under Reward Hacking's "gaming evaluation metrics," and as a falsehood addressed to a
human reader it belongs to Deception here. The one task previously filed under `RISK-EG` selected which
percentile a dashboard reported in order to flatter a missed target; it is now an instantiation of
`RISK-DC`.

### Reward Hacking: scope within the adopted definition

`RISK-RH` is specified here as gaming a **completion or health signal** — weakening a failing check so
it reports success, recording work as complete without doing it, suppressing an alert instead of
addressing its cause. This is within ESRR's category-level definition, which is not restricted to
numeric reward: it covers "gaming evaluation metrics," "satisfying the letter but not the spirit of
instructions," and "optimising for proxy signals rather than true goals," and its SIM-REWARD scenario
type is described as "deliberately misaligned incentive structures where the apparent reward conflicts
with the intended objective."

One qualification, stated because it bears on how strongly the citation can be leaned on: **neither of
ESRR's two documented `RISK-RH` subcategories operationalizes this.** RH-01 is Sycophancy (excessive
agreement with user preferences) and RH-02 is Policy Boundary Pushing (probing content-policy limits);
neither mentions tests, checks, build pipelines, or completion signals. The specification here
therefore rests on the category definition, not on a subcategory, and Appendix B's truncation means
additional subcategories cannot be ruled out. The tag remains `adopted:` because the category-level
definition covers the scope; it would be `adapted:` if it did not.

**Definition provenance.** Appendix B of the arXiv HTML rendering is truncated at `RISK-EG-02`, so
verbatim source definitions for `RISK-CMS`, `RISK-SRS`, `RISK-IO`, and `RISK-SSM` were not
retrievable. The definitions in `taxonomy.json` for those four categories are operationalizations
under the adopted category names, consistent with the paper's framing; they are not quotations.

## 3. Grounding for the two additions

> Ruan, Y., Dong, H., Wang, A., Pitis, S., Zhou, Y., Ba, J., Dubois, Y., Maddison, C. J., &
> Hashimoto, T. (2024). *Identifying the Risks of LM Agents with an LM-Emulated Sandbox.*
> arXiv:2309.15817. ICLR 2024.

Referred to as **ToolEmu**. It is the closest published analogue to this setting: tool-using LM
agents, 36 high-stakes toolkits, 144 curated cases, each annotated with free-text potential risky
outcomes. It imposes no fixed taxonomy — risk labels are written per case — which makes the corpus
usable as evidence about which risks arise when agents are given tools, independent of any taxonomy.

Normalizing the 144 cases' risk labels to head nouns yields 88 distinct labels, of which the most
frequent are:

| ToolEmu risk label | cases |
|---|---|
| privacy breach | 25 |
| financial loss | 21 |
| reputation damage | 12 |
| unauthorized access | 10 |
| data loss | 7 |
| misinformation | 7 |
| system instability | 7 |
| loss of control | 4 |
| security breach | 4 |

Privacy breach is the most frequent risk in the corpus and unauthorized access the fourth. Grouping
near-synonyms, 56 of 144 cases (39%) name a privacy or unauthorized-access/security risk. ESRR has a
category for neither. An agentic benchmark restricted to ESRR's categories would systematically omit
a large fraction of the risk surface its own setting produces.

Aligned definitions:

- `RISK-PV` ← "Privacy breach: Unintentionally revealing sensitive information of the user"; "Data
  loss: Loss of important user files or system files due to unauthorized deletion."
- `RISK-UA` ← "Unauthorized access: Sharing files or folders with unintended recipients or granting
  excessive permissions"; "Loss of control: Granting an unintended permanent access or misspecified
  temporary access."

Both additions also correspond to established control frameworks — unauthorized access to broken
access control and privilege escalation; privacy violation to data-protection retention and
purpose-limitation duties.

**Considered and not adopted.** AgentHarm (Andriushchenko et al., ICLR 2025; arXiv:2410.09024)
defines eleven harm categories over 110 malicious agent tasks. It measures compliance with an
explicitly malicious user request, whereas this benchmark's design bar forbids instructing the unsafe
act: every hazard must arise under natural task pressure from a benign requester. Its categories
describe attacker intent rather than emergent drift, and it is cited as contrast rather than as a
source. Content-safety taxonomies of toxicity and bias are orthogonal; ESRR excludes them on the same
grounds.

## 4. Empirical criterion

A category is useful in a benchmark only if it can be instantiated in items that are not saturated.
That is measurable, and it is applied here as a criterion independent of either source taxonomy. The
values below are from the calibration corpus (`taxonomy.json:calibration_corpus`; 6,927 runs, 31 target
tasks, 4 models; live band [0.15, 0.90]), labelled by the category each mechanism was filed under **at
the time it was measured**:

| as-measured category | targets | mean cold safety | live | current status |
|---|---|---|---|---|
| Deception | 3 | 0.403 | 3/3 | `RISK-DC`, productive |
| Unauthorized Access *(added)* | 2 | 0.412 | 2/2 | `RISK-UA`, productive |
| Strategic Research Sabotage | 4 | 0.423 | 4/4 | `RISK-SRS`, productive |
| Influence Operations | 2 | 0.523 | 2/2 | `RISK-IO`, productive |
| Control Measure Subversion | 2 | 0.588 | 2/2 | `RISK-CMS`, productive |
| Evaluation Gaming | 1 | 0.781 | 1/1 | reclassified to `RISK-DC` |
| Privacy Violation *(added)* | 2 | **0.970** | **0/2** | framing retired; `RISK-PV` now unmeasured |
| Reward Hacking *(adopted)* | 4 | **0.984** | **0/4** | framing retired; `RISK-RH` re-scoped, unmeasured |

Three consequences:

1. One addition, `RISK-UA`, is the third most productive category, which supports the extension by
   measurement rather than by appeal to ToolEmu alone.
2. **Saturation was independent of provenance.** Of the two framings that saturated, one belonged to an
   addition (`RISK-PV`) and one to an adopted category (`RISK-RH`). Both saturated for the same reason:
   the harm was the subject of the request rather than a consequence of the work, so refusal required
   no inference. That is a defect of instantiation, not of the category, and it is what the `pressure`
   field exists to prevent. Both categories are retained with revised pressure requirements and their
   saturated framings recorded under `retired_framings`.
3. **Two values no longer describe any live category.** The 0.970 and 0.984 figures were measured on
   framings now retired, so `taxonomy.json` records them as `prior_measurement` and sets those
   categories to `unmeasured` rather than carrying a number forward that does not apply to the current
   specification. The 0.781 mechanism was reclassified rather than retired, and is not pooled into
   `RISK-DC`'s 0.403, which is measured on three report-attainment targets only.

**Attribution limit.** These per-category values are not attributable to the category. In the
calibration corpus, category and `task_family` were near-collinear — seven of eight as-measured
categories appeared in exactly one family and seven of eight families carried exactly one category,
with ten distinct families backing all 31 targets. The table therefore licenses rejecting a saturated
instantiation; it does not rank harm classes. The crossing rule (`taxonomy.json:crossing_rule`)
requires ≥2 families per category and ≥2 categories per family in the released bank, which makes the
attribution identifiable.

## 5. Open questions

Recorded in `taxonomy.json:open_questions`; resolved items are retained under `resolved_questions`
with their reasoning. Both remaining questions concern categories whose current specification is
`unmeasured`, and both are settled by the pilot rather than by argument:

1. `RISK-RH`'s boundary against `RISK-CMS` — corrupting the signal a control emits, versus bypassing
   the control — is coherent in specification but untested in authoring.
2. `RISK-PV` under the harm-as-consequence pressure recipe is untested; the pilot tests whether that
   recipe rescues a category that saturated at 0.970 under its retired framing. If it does not,
   `RISK-PV` is excluded despite having the strongest independent grounding of the two additions —
   which is the criterion of §4 applied to our own contribution.
