# AC-108 — First Design-Partner Criteria, Discovery Script and Market-Validation Plan

Status: `Complete / PASS`
Version: `0.1.0`
Created: `2026-08-20`
Updated: `2026-08-20`
Owner: `ООО «Арвектум»`
Repository: `arvectum/arvectum-company`
Roadmap item: `AC-108 — First design-partner criteria, discovery script and market-validation plan`
Review: `docs/reviews/AC-108-DESIGN-PARTNER-MARKET-VALIDATION-CROSS-REVIEW.md`
Strategic basis: `docs/governance/decisions/DECISION-2026-08-20-FLAGSHIP-AI-COMPANY-BUILDER.md`
Hypothesis basis: `docs/business/FLAGSHIP-ICP-BUYER-JTBD-OUTCOME-HYPOTHESES.md`

## 1. Purpose

This artifact converts AC-107 from a market hypothesis into an executable, bounded discovery and design-partner validation instrument.

It defines:

- what qualifies a plausible first design-partner candidate;
- how candidates are prioritized without confusing convenience with fit;
- how discovery conversations should test the AC-107 hypotheses without leading the interviewee;
- what evidence must be captured about the current workflow, management bottleneck, authority, data/tool boundary, quality, economics and change burden;
- how the first Russia-first discovery loop should be sourced and bounded;
- how evidence is classified as supporting, contradicting, insufficient or disqualifying;
- when the first segment hypothesis should continue, change or stop;
- what a bounded first engagement may look like if a candidate later passes a separate approval/commitment decision.

AC-108 is a **market-validation plan and evidence instrument**. It is not itself market validation and does not fabricate customer interviews, demand, willingness to pay, pricing, ROI, implementation duration, product-market fit, production readiness or customer authority.

## 2. Canonical basis and evidence boundary

AC-108 inherits the current Company baseline:

- AC-101 fixes the flagship as a customer-specific AI-native company / `«ИИ-компания под ключ»`, not a procurement-only business and not an agent-swarm product.
- AC-102 requires customer value to be separated from Arvectum implementation/runtime/support economics and does not establish pricing or margin.
- AC-103 shows that current Arvectum evidence is strongest in concrete discovery, scoped delivery, QA, customer validation, correction and acceptance, while repeatable acquisition and post-delivery value measurement remain weak.
- AC-104 shows that the core internal scaling problem is concentrated interpretation, context, exception routing and decision preparation around a scarce senior Principal rather than raw coding throughput.
- AC-105 requires legitimate authority/security gates, customer sovereignty, continuity, fallback and replaceability to remain explicit rather than being optimized away.
- AC-107 narrows the first flagship hypothesis to an owner-led B2B company with one recurring information/coordination-heavy function where a senior executive remains a material interpretation/exception bottleneck.

AC-107 defines nine hypotheses to test: `ICP-H1`, `ICP-H2`, `BUY-H1`, `CHAMP-H1`, `JTBD-H1`, `WEDGE-H1`, `OUT-H1`, `ECO-H1` and `SOV-H1`.

AC-108 creates the instrument for testing those hypotheses. Actual customer observations produced later remain empirical evidence and must not be backfilled into this artifact as if they already occurred.

## 3. What “design partner” means at this stage

A **design-partner candidate** is not a customer merely interested in AI.

For AC-108, it means a real organization that appears capable of exposing one recurring business function deeply enough to test whether Arvectum's organization-first method creates measurable operating value and can be delivered within bounded authority, data, implementation and support constraints.

A **design partner** is a candidate that later passes a separate commitment decision and agrees to a bounded engagement with explicit scope, authority, data, evidence, acceptance, commercial and exit terms.

Therefore:

```text
candidate
→ qualified discovery
→ evidence-backed fit assessment
→ possible design-partner proposal
→ explicit customer + Arvectum approval/commitment
→ only then a design-partner engagement
```

Discovery participation alone creates no production obligation, SLA, price, discount, exclusivity, support commitment, Product Contract, customer authority or right to customer data.

## 4. Candidate qualification model

Candidate qualification has two layers:

1. **hard gates** — conditions that must be sufficiently true before the Company should spend material discovery/implementation effort; and
2. **priority score** — a reversible heuristic for ordering candidates that pass the hard gates.

The score cannot override a failed hard gate.

### 4.1 Hard gates

A first design-partner candidate should satisfy all of the following or have a concrete path to resolving the item before any pilot commitment.

| Gate | Required condition | Why it matters |
|---|---|---|
| `G1 — Executive sponsor` | an Owner/Founder/CEO/General Director or equivalent Principal, or a genuinely empowered business-unit leader, owns or materially experiences the problem | the offer changes operating responsibility/workflow, not only software |
| `G2 — Bounded recurring function` | one recurring workflow/function can be isolated from the rest of the company | enables a reversible proof and causal learning |
| `G3 — Observable accepted output` | the organization can explain what a successfully completed unit looks like | prevents “AI activity” from replacing business outcome evidence |
| `G4 — Material management bottleneck` | real recent cases show repeated senior interpretation, exception handling, coordination, prioritization or approval burden | directly tests the AC-107 JTBD |
| `G5 — Evidence access` | the customer can lawfully and safely expose enough representative workflow evidence to establish a baseline | prevents an unverifiable pilot |
| `G6 — Authority map` | the organization can identify who may approve material actions and who may veto security/data/operational changes | technical access cannot substitute for Organizational Authority |
| `G7 — Supervised proof` | the candidate accepts bounded human-reviewed execution before broad autonomy | protects both parties while value is unproven |
| `G8 — Fallback` | the current/manual process can continue or fail safely while the new model is tested | avoids making the experiment an uncontrolled continuity dependency |
| `G9 — Baseline and outcome review` | the candidate is willing to observe current burden and compare post-change evidence | required for outcome validation |
| `G10 — Commitment boundary` | the candidate does not require unsupported production/SLA/compliance guarantees, unsafe data access or autonomous consequential action as a precondition to discovery | avoids selling maturity or authority Arvectum has not approved |

A candidate with an unresolved hard-gate failure is `Not ready for design-partner qualification`, even if commercially attractive.

### 4.2 Immediate poor-fit / knockout signals

The following normally end or pause qualification:

- no recurring workflow or accepted output can be described;
- the problem is novelty-driven rather than operationally material;
- no authorized sponsor owns the target function;
- the organization will not expose concrete recent workflow evidence;
- the candidate requires company-wide transformation before one bounded function can be tested;
- the candidate wants AI/software to make legally or organizationally reserved decisions without authorized human governance;
- success requires immediate autonomous external commitments, payments, signatures or other consequential actions;
- lawful/secure access to necessary data or systems cannot be established;
- there is no viable fallback during proof;
- the customer requires unsupported production, SLA, security, compliance or platform-maturity claims as a condition of proceeding;
- the likely integration/support burden is obviously disproportionate to the value pool;
- the request is materially better served by a simple standalone tool and the customer rejects the broader operating-model problem.

The last item is not a sales failure. It is evidence against `ICP-H2` for that candidate.

## 5. Candidate priority scorecard

Candidates that pass the hard gates are ranked with a simple `0–3` score per dimension.

This score is a **discovery prioritization heuristic**, not a statistical validation model, credit score or automatic approval.

| Dimension | 0 | 1 | 2 | 3 |
|---|---|---|---|---|
| `P1 — Pain materiality` | no material consequence | inconvenience | recurrent operational cost/friction | clear growth, revenue, cost, delay, quality or management-capacity constraint |
| `P2 — Senior-management dependence` | senior manager rarely involved | occasional involvement | frequent interpretation/approval | function materially blocks or degrades without senior attention |
| `P3 — Recurrence / case flow` | rare/one-off | irregular | recurring | frequent enough to observe patterns and outcome change in a bounded window |
| `P4 — Observability` | no reliable before/after evidence | weak anecdotal evidence | several measurable fields | accepted output, intervention, time/quality/rework evidence can be captured consistently |
| `P5 — Boundedness` | requires broad transformation | many tightly coupled functions | one main function with dependencies | clearly isolatable function/value-stream slice |
| `P6 — Data/tool feasibility` | access blocked/unsafe | major unresolved access burden | feasible with material work | bounded lawful access appears practical and replaceable |
| `P7 — Economic plausibility` | no meaningful value pool | unclear/small | credible value pool | material value relative to plausible implementation/support effort |
| `P8 — Transferability / learning value` | highly unique | mostly bespoke | some reusable pattern | operating pattern likely to teach reusable method/module lessons |

Maximum score: `24`.

Working priority bands:

- `18–24` + no hard-gate failure → **High-information candidate**;
- `12–17` + no hard-gate failure → **Secondary candidate / useful contrast**;
- `<12` or material unresolved gate → **Low priority / do not spend implementation effort yet**.

These bands are deliberately operational, not scientific. They should be recalibrated after real interviews if they fail to distinguish useful candidates.

A high total score must not compensate for a `0` on authority/data safety, boundedness or observability where that makes a supervised proof impossible.

## 6. Russia-first sourcing and prioritization logic

AC-108 does not create a mass outbound campaign. The first loop should maximize **information per conversation**.

Preferred sourcing order:

1. **Warm, trust-bearing B2B relationships** where the Owner/CEO or operating leader can expose a real workflow honestly.
2. **Current/past Arvectum-adjacent business relationships** that match the behavioral ICP without assuming that an existing client is automatically a flagship fit.
3. **Procurement/tender-oriented owner-led B2B companies** because Arvectum currently has strong domain/workflow evidence there, while keeping procurement as a wedge rather than Company identity.
4. **Owner-led digital-service / automation / agency businesses** with visible discovery/scoping/delivery/QA/customer-iteration loops.
5. **Data-heavy commerce/monitoring/operations businesses** where recurring intake, normalization, exception and coordination work is material.
6. **Introductions/referrals from trusted professional networks** to reach comparable companies outside the Owner's immediate project history.
7. **Cold exploratory candidates** only where they materially improve segment coverage or challenge the current hypothesis.

The first loop should test at least two materially different subsegments so that one familiar domain does not become the flagship by convenience.

Warm relationships are preferred for evidence access, not because warm leads are assumed to have stronger demand.

## 7. First discovery-loop experiment boundary

The first market-validation loop is qualitative and bounded.

### 7.1 Candidate pool

Create a working pool of **up to 20 candidate organizations** using only the minimum information required for qualification and contact planning.

The working pool is not a public repository artifact if it contains personal data, confidential relationship context or contact details.

### 7.2 Conversation target

Target **8–12 completed high-information discovery conversations** in the first loop.

This is not a statistically representative sample. It is an operational cap intended to create enough independent observations to detect recurring patterns without turning AC-108 into a broad survey campaign.

Do not inflate the count with superficial conversations. Replace unusable conversations with better candidates when:

- no concrete recent workflow can be discussed;
- the respondent lacks relevant operational knowledge or authority context;
- the conversation becomes a generic opinion about AI;
- evidence quality is too weak to test any material hypothesis.

### 7.3 Segment coverage

Before declaring one subsegment the leading candidate, obtain meaningful evidence from at least one alternative subsegment.

A stronger segment is identified by repeated concrete problem evidence, accessible bounded workflows, credible value pools and serious buyer/champion engagement — not by the largest number of available contacts.

### 7.4 What the first loop is trying to learn

The first loop should answer:

1. Is the hypothesized senior-management bottleneck recurrent and material?
2. Do customers describe the problem as broader operating friction or only as a narrow software/tool need?
3. Is the Owner/CEO/General Director really the natural buyer, or is another empowered role more common?
4. Can one bounded function be isolated with an accepted output and measurable baseline?
5. Which operating metrics are actually available and meaningful to the customer?
6. What authority/data/security/integration constraints dominate the engagement?
7. What alternative solutions have already been tried and why were they insufficient?
8. Is there a credible economic value pool?
9. What would a buyer need to see before approving a pilot or budget?
10. Are governance, sovereignty, local/controlled deployment and replaceability buying drivers, assurance requirements or largely irrelevant?
11. What implementation/change/support burden would make the offer unattractive?
12. Which customer words best describe the problem and desired progress?

## 8. Discovery protocol

### 8.1 Interview principle

The interview must start from a **recent concrete event**, not from Arvectum's solution vocabulary.

Preferred sequence:

```text
recent real case
→ current workflow
→ senior-management intervention
→ exception / delay / rework
→ accepted output and quality
→ tools/data/context
→ authority and veto boundaries
→ economic consequence
→ prior attempts / alternatives
→ buying/decision process
→ only then test the Arvectum concept
```

Do not begin with “Would an AI company help you?” or “Would you pay for this?”.

### 8.2 Recommended interview length

A `45–60 minute` conversation is a useful working format. Time is guidance, not a contract.

Suggested allocation:

- 5 min — context and permission;
- 10–15 min — recent case + workflow reconstruction;
- 10 min — management interventions/exceptions;
- 10 min — outcome/quality/economic consequence;
- 5–10 min — authority/data/tools/prior attempts;
- 5 min — buying process and design-partner appetite;
- final 5 min — positioning test and respondent language.

### 8.3 Interviewer discipline

The interviewer should:

- ask for examples before opinions;
- distinguish “usually” from “last time”;
- ask what happened, not what the respondent thinks should happen;
- ask for ranges/records only when the respondent can support them;
- avoid suggesting desired percentage improvements;
- separate factual current-state evidence from future preference;
- capture contradictions rather than resolve them to fit the thesis;
- avoid collecting unnecessary personal, confidential or secret information;
- stop before discussing real sensitive payload if discovery does not yet require it.

## 9. Discovery script — Russian-first

The following is a practical script for Russian-market interviews. It is an interview guide, not a questionnaire that must be read mechanically.

### A. Context and role

1. `Расскажите коротко, за какой участок бизнеса вы лично отвечаете и какие решения по нему можете принимать?`
2. `Какая повторяемая работа или процесс сейчас сильнее всего требует вашего личного внимания?`
3. `Почему именно этот процесс сейчас для вас важен?`

### B. Recent concrete case

4. `Вспомните последний конкретный случай, когда этот процесс проходил от начала до результата. С чего всё началось?`
5. `Какой результат в конце считался нормальным или принятым? Кто это определяет?`
6. `Какие шаги реально происходили дальше? Кто что делал?`
7. `Какие системы, таблицы, мессенджеры, документы или сайты участвовали?`
8. `В каком месте процесс в последний раз остановился, вернулся назад или потребовал уточнения?`

### C. Management bottleneck

9. `В каких точках без вас или другого руководителя работа не могла нормально продолжиться?`
10. `Что именно вам пришлось интерпретировать, решать или согласовывать?`
11. `Сколько раз за этот конкретный случай к вам возвращались? Если время можно оценить — сколько активного времени и сколько ожидания это добавило?`
12. `Если бы вас не было доступно неделю, что произошло бы с такими случаями? Что продолжилось бы, что остановилось бы, а что пришлось бы делать иначе?`
13. `Какие обращения к вам действительно требуют вашего решения, а какие вы бы предпочли не видеть лично, если бы им можно было доверять?`

### D. Quality, rework and accepted outcome

14. `Как вы понимаете, что результат сделан хорошо? Что является критической ошибкой?`
15. `Что чаще всего приходится переделывать и почему?`
16. `Бывает ли, что работа формально завершена, но вы или клиент её не принимаете? Что обычно не так?`
17. `Какие последствия у задержки или ошибки: потерянное время, деньги, клиент, штраф, срыв срока, репутация, дополнительная ручная работа?`

### E. Current alternatives and prior automation

18. `Что вы уже пробовали, чтобы снять эту нагрузку: найм, регламенты, CRM/ERP, подрядчиков, автоматизацию, AI-инструменты?`
19. `Что в этих попытках сработало, а что нет?`
20. `Почему проблема всё ещё возвращается к вам лично?`

### F. Authority, data and system boundary

21. `Кто имеет право окончательно одобрять действия или результат по этому процессу?`
22. `Какие решения нельзя отдавать автоматике или сотруднику без отдельного согласования?`
23. `Кто ещё может остановить изменение процесса — ИТ, безопасность, юрист, финансы, владелец данных, клиент?`
24. `Какие данные и системы нужны для работы? Есть ли ограничения на локальное хранение, облака, передачу третьим лицам или внешние сервисы?`
25. `Если новая система временно недоступна, какой текущий процесс должен остаться рабочим как запасной вариант?`

### G. Economic and buying evidence

26. `Как вы сейчас оцениваете стоимость этой проблемы — не обязательно в рублях: время руководителя, задержки, потери, лишний персонал, переделки, упущенная пропускная способность?`
27. `Когда вы раньше решали похожую проблему, во что уже вкладывали деньги или время?`
28. `Кто принимает решение о бюджете на такой проект и кто кроме него должен согласовать?`
29. `Что нужно доказать, чтобы вы реально выделили бюджет на изменение этого процесса?`
30. `С чем вы бы сравнивали такое решение: найм человека, аутсорс, готовое ПО, внутреннюю разработку, ничего не менять?`

### H. Bounded design-partner appetite

31. `Если сначала не менять весь бизнес, а взять один процесс, зафиксировать текущую нагрузку и результат и проверить его на ограниченном количестве реальных случаев под человеческим контролем — что должно быть правдой, чтобы такой формат имел смысл для вас?`
32. `Что сделало бы такой пилот слишком рискованным или неудобным?`
33. `Кто должен участвовать, чтобы результат можно было честно принять или отвергнуть?`
34. `Если пилот покажет результат, какое следующее действие для вас было бы естественным: продолжить, расширить, купить, передать команде, ничего не делать? Почему?`

### I. Positioning test — only at the end

After the current-state discovery, the interviewer may test the short AC-107 proposition in neutral form:

> `Мы проверяем гипотезу: взять одну повторяемую функцию, где руководитель остаётся узким местом, явно описать ответственность, полномочия, процесс, знания и контроль, а повторяемое исполнение передать людям/AI/software так, чтобы тот же или лучший принятый результат требовал меньше дефицитного внимания руководителя без потери контроля.`

Then ask:

35. `Что в таком описании совпадает с вашей проблемой, а что нет?`
36. `Что здесь звучит как лишнее усложнение?`
37. `Как бы вы сами назвали результат, за который действительно готовы были бы платить?`
38. `Что вам было бы важнее: экономия времени руководителя, скорость, меньше переделок, больше пропускная способность, устойчивость процесса или что-то другое?`
39. `Насколько для вас важны локальность/контроль данных, заменяемость AI/поставщика и возможность выйти из решения без потери процесса и истории? Почему?`

The final question tests `SOV-H1` without assuming that sovereignty is a universal buying driver.

## 10. Evidence capture schema

Each completed interview should produce a structured evidence record.

Raw notes may contain personal/confidential information and therefore **must not be committed to this public repository by default**.

Public Company artifacts should contain anonymized/aggregated evidence only when needed for Company decisions.

### 10.1 Minimum interview record

| Field | Required evidence |
|---|---|
| Candidate ID | internal pseudonymous identifier such as `DP-CAND-001` |
| Subsegment | procurement/tender B2B, digital service/agency, data-heavy operations, other |
| Source class | warm relationship, existing/past client context, referral, cold exploration |
| Respondent role | buyer hypothesis / champion / user / assurance-veto role |
| Authority scope | what the respondent can actually approve/change |
| Recent case | concise description of one concrete workflow instance |
| Trigger | what starts the work |
| Accepted output | what counts as completed/accepted business result |
| Main steps/handoffs | current workflow sequence |
| Senior interventions | count or concrete intervention points in the recent case where supportable |
| Senior active time | observed/reported range where supportable; otherwise `unknown` |
| Blocking/waiting | where work waited for interpretation/approval |
| Recurrence | how often similar work occurs, stated as evidence/range when known |
| Quality/rework | critical-error definition, correction causes, acceptance failures |
| Tools/systems | high-level systems/channels needed; no credentials/secrets |
| Authority gates | who may approve consequential actions |
| Data/security constraints | high-level handling constraints only |
| Fallback | current/manual degraded path |
| Prior alternatives | hiring, process change, software, outsourcing, AI, internal build |
| Economic consequence | time/cost/delay/capacity/quality/risk evidence |
| Budget path | who decides and what must be proven |
| Design-partner appetite | evidence of willingness to continue, not a promised contract |
| Customer language | short phrases describing the problem/outcome, minimized for confidentiality |
| Hypothesis impact | support / weaken / reject / insufficient for each applicable AC-107 hypothesis |
| Candidate gates/score | G1–G10 result and P1–P8 priority score |
| Open risks | unresolved authority, data, integration, adoption or support constraints |
| Next step | stop / follow-up evidence / candidate diagnostic / no action |

### 10.2 Evidence confidence

Every material field should be tagged conceptually as:

- `Observed / evidenced` — supported by an actual recent case, record, system evidence or direct workflow observation;
- `Reported current fact` — credible respondent statement about current operation but not independently observed;
- `Preference / future intent` — what the respondent says they would like or might do;
- `Inference` — Arvectum interpretation;
- `Unknown` — not established.

A future-intent statement such as “yes, we would buy this” must not be recorded as purchase evidence.

## 11. Mapping questions to AC-107 hypotheses

| Hypothesis | Primary discovery evidence |
|---|---|
| `ICP-H1` | concrete repeated examples of senior-management coordination/exception burden; material delay/cost/capacity consequence |
| `ICP-H2` | whether the buyer frames the problem as responsibility/workflow/context/authority friction versus a narrow standalone tool need |
| `BUY-H1` | actual authority/budget path and who sponsors process change |
| `CHAMP-H1` | existence of a day-to-day operational owner who can expose cases and accept/reject outcomes |
| `JTBD-H1` | whether reducing scarce management attention is materially valuable relative to other outcomes |
| `WEDGE-H1` | ability to isolate one recurring function with clear trigger/output/data/authority/fallback |
| `OUT-H1` | availability of paired attention + quality/cycle/rework/adoption measures and plausibility of improvement without control loss |
| `ECO-H1` | credible value pool, alternatives already funded, budget decision criteria and plausible implementation/support burden |
| `SOV-H1` | explicit customer importance of local/controlled deployment, data control, replaceability, portability and authority governance |

Evidence may support some hypotheses and contradict others. Do not turn the interview into one overall “positive/negative” label.

## 12. Bias and evidence-quality controls

The first loop is especially vulnerable to confirmation bias because Arvectum already has a strong internal product thesis.

Required controls:

1. **Recent-event anchoring.** At least one concrete case must be reconstructed before the concept is presented.
2. **No solution-first qualification.** “Likes AI” does not increase candidate fit unless it connects to a real workflow and outcome.
3. **Record contradictions.** If the respondent says management time is not a bottleneck, record it even if another part of the conversation sounds promising.
4. **Separate buyer/champion/user evidence.** A user complaint is not automatically a buyer priority.
5. **Separate willingness-to-talk from willingness-to-commit.** Discovery participation is weak commercial evidence.
6. **Prefer past behavior to hypothetical intent.** Prior spend, attempted fixes, actual delays and concrete decisions are stronger than “we would probably”.
7. **Avoid fabricated precision.** Unknown time/cost/volume remains `unknown`; do not convert rough statements into exact KPIs.
8. **Protect negative evidence.** A candidate choosing a narrow tool instead of organizational redesign is valid market evidence, not a failed interview.
9. **Do not overfit procurement.** At least one non-procurement subsegment must be tested before procurement becomes the leading segment hypothesis by evidence.
10. **Do not overfit warm relationships.** Warm access improves data quality but is not itself evidence of market demand.

## 13. Market-validation decision logic

The first loop does not “prove PMF”. It produces a Company decision about the **next market hypothesis**.

### 13.1 Continue the current segment/wedge hypothesis

A subsegment is strong enough to continue toward design-partner selection when evidence shows all of the following:

1. multiple independent candidates describe the same material operating pattern using concrete recent cases;
2. at least one bounded function repeatedly meets the hard-gate model;
3. the primary buyer/champion/authority pattern is identifiable;
4. current managerial-attention/quality/cycle/rework evidence can be measured or credibly baselined;
5. there is a plausible value pool large enough to justify deeper economic scoping;
6. at least one authorized buyer shows **serious next-step behavior** — for example, agreeing to a scoped diagnostic, providing controlled baseline evidence, involving an operational champion or discussing real budget/approval criteria;
7. no dominant authority/data/security/integration/support constraint makes a bounded proof unsafe or economically irrational.

For the first loop, a useful minimum pattern signal is **three independent high-information candidates in one coherent subsegment** showing substantially the same problem shape. This is not statistical proof; it is a guard against basing the flagship on one enthusiastic relationship.

### 13.2 Change the hypothesis

Change the segment, buyer, JTBD, wedge or positioning when:

- the pain is recurrent but another role consistently owns budget/authority;
- management attention is not the main value driver but cycle time, quality, rework, capacity or continuity is;
- customers want a narrower bounded product and reject operating-model redesign;
- one subsegment shows materially better fit/economics/access than the initial broad owner-led B2B framing;
- the same core problem exists but the viable wedge differs from AC-107 examples;
- sovereignty/replaceability is consistently an assurance requirement rather than a purchase driver;
- the implementation/change burden indicates the first offer must be smaller.

A change is a successful learning outcome if it makes the next hypothesis more falsifiable and economically credible.

### 13.3 Stop the initial flagship hypothesis

Recommend stopping or materially rethinking the initial hypothesis when, after a completed first loop of `8–12` high-information conversations:

- no coherent subsegment shows a recurrent material senior-management coordination/exception problem;
- candidates consistently lack one bounded measurable function;
- authorized buyers consistently treat the problem as too small to fund or change;
- serious candidates will not provide enough workflow/baseline evidence for a bounded proof;
- the dominant customer need is consistently a commodity tool that does not justify organization-first implementation;
- the expected implementation/integration/support burden repeatedly appears larger than the credible customer value pool;
- required authority/data/security conditions make the intended proof structurally unsafe or impractical;
- Arvectum cannot identify a design-partner path that preserves customer sovereignty, fallback and explicit authority.

Failure to source enough qualified conversations is **insufficient evidence**, not automatic rejection of the market hypothesis. Sourcing quality must be diagnosed separately.

## 14. Bounded first-engagement concept

AC-108 does not approve an engagement, but it defines the smallest credible concept to test with qualified candidates.

### Stage A — Diagnostic / function baseline

Purpose: determine whether one function is suitable for a design-partner proof before making a production commitment.

Potential outputs:

- current function/value-stream map;
- accepted-output definition;
- senior-management intervention/bottleneck baseline;
- key exceptions and handoffs;
- current tool/data boundary;
- customer authority/approval/veto map;
- quality/rework/cycle evidence fields;
- value-pool hypothesis;
- initial fallback and risk boundary;
- candidate continue/change/stop recommendation.

Stage A should avoid real production mutation where discovery evidence is sufficient without it.

### Stage B — Bounded supervised design-partner pilot

Only after separate approval and agreement, the candidate pilot may test:

- one function/value-stream slice;
- a fixed scope of representative real cases;
- explicit human authority/approval boundaries;
- approved data/tool access;
- manual/degraded fallback;
- before/after outcome evidence;
- implementation/runtime/support effort;
- acceptance and stop criteria.

No autonomous customer commitment, payment, signature, supplier/customer message, production mutation or other consequential external action is implied by this concept.

Commercial terms, price, discount, support duration, liability, IP/data terms, SLA and production commitments remain separate decisions and agreements.

## 15. Commercial and economic validation questions

AC-108 deliberately avoids premature price discovery such as “Would you pay X?”.

Better evidence includes:

- actual cost or senior time currently absorbed by the problem;
- prior spending on staff, software, consultants, outsourcing or internal automation;
- cost/impact of delay, rework, quality failure or lost capacity;
- actual budget owner and approval cycle;
- alternatives the buyer would compare against;
- evidence threshold required before budget approval;
- acceptable implementation/change burden;
- whether the buyer expects one-time implementation, recurring support, managed service or internal handover;
- what would cause the buyer to stop after diagnostic/pilot;
- what successful evidence would justify continuation/expansion.

Arvectum must separately record its own estimated active implementation effort, dependency/integration burden, recurring runtime/support effort and Owner involvement before making a commercial commitment.

Customer value does not prove Arvectum gross margin, and low Arvectum cost does not prove willingness to pay.

## 16. Authority, data, privacy and Arvectum OS boundary

Discovery and future design-partner work must preserve these invariants:

1. customer Organizational Authority remains with authorized customer Principals;
2. technical access, Product Contract registration or AI capability creates no customer decision authority;
3. raw customer data, confidential notes, contact details, credentials and sensitive payload do not belong in this public repository;
4. customer-specific evidence does not become cross-customer Company knowledge by default;
5. any reusable learning must be minimized, rights-reviewed and stripped of customer-confidential/authority semantics before promotion;
6. discovery should collect the minimum data needed to test the hypothesis;
7. actual system access requires a separate approved scope and least privilege;
8. secrets and reusable credentials must never be requested merely for discovery convenience;
9. Arvectum OS current Incubating/Provisional state does not support a Stable/Active/production/SLA claim by implication;
10. any future Arvectum OS reliance must use the applicable Product Contract/governance path;
11. a customer pilot must fail closed or return to an approved manual/degraded path when required authority/data/evidence is unavailable;
12. local/controlled deployment and technology sovereignty may be tested as customer requirements without being claimed as universal legal compliance.

## 17. Aggregating the first-loop evidence

After the first loop, create an anonymized decision summary that contains no unnecessary customer-identifying or confidential information.

The summary should include:

- number of usable conversations and unusable/rejected conversations;
- subsegment mix;
- hard-gate pass/fail frequencies;
- recurring customer problem language;
- strongest concrete evidence for and against each AC-107 hypothesis;
- buyer/champion/authority patterns;
- recurring function/wedge candidates;
- available baseline/outcome metrics;
- dominant data/integration/security barriers;
- current alternative solutions and prior spend patterns;
- serious next-step behaviors versus hypothetical interest;
- estimated Arvectum discovery/implementation/support burden ranges where evidenced;
- leading subsegment/wedge candidate, if any;
- explicit continue/change/stop recommendation;
- evidence gaps and the next smallest experiment.

The aggregate must distinguish:

```text
conversation count
≠ qualified-candidate count
≠ design-partner count
≠ paid-customer count
≠ product-market fit
```

## 18. AC-106 handoff

AC-106 — M1 business baseline review and Owner priority decision — should review AC-101 through AC-108 as one business-planning baseline.

At AC-108 completion, AC-106 may legitimately conclude only that:

- the flagship business direction is explicit;
- the first falsifiable ICP/buyer/JTBD/outcome hypothesis exists;
- a bounded design-partner qualification and discovery instrument exists;
- evidence capture and market continue/change/stop logic exist;
- external market demand is **not yet validated** unless real discovery has separately occurred after this publication.

AC-106 therefore must not convert “ready to run discovery” into “validated market”.

The Owner may use AC-106 to decide how aggressively market discovery should run in parallel with Phase 2 operating-model work, current client delivery and other portfolio priorities.

## 19. Completion boundary

AC-108 is complete when the Company has, without inventing customer evidence:

- explicit design-partner hard gates and poor-fit signals;
- a prioritization scorecard;
- Russia-first sourcing logic that does not overfit one familiar domain;
- a bounded first discovery-loop size and segment-coverage rule;
- a non-leading Russian-first discovery script;
- structured evidence fields and confidence classes;
- a map from discovery evidence to all AC-107 hypotheses;
- confirmation-bias controls;
- explicit continue/change/stop criteria;
- a bounded diagnostic/pilot concept separated from customer commitment;
- authority/data/security/OS boundaries;
- a clear evidence aggregation and AC-106 handoff.

This publication satisfies that boundary.

Next roadmap action: `AC-106 — M1 business baseline review and Owner priority decision`.