## Meeting Summary — FSO Knowledge Transfer (June 24, 2026)

**Duration:** ~79 minutes | **Participants:** Anurag/Stephanie (IBM), Nahid (outgoing engineer)

### Purpose
Knowledge transfer handoff for the FSO (Fuel Supply Optimization) project. Anurag has been reviewing documentation but lacks access to key systems and is trying to learn enough to onboard whoever takes over from Nahid.

---

### Critical Findings

**1. Severe Access Bottleneck — URGENT**
- Anurag requested access to ARise, KTEs, GitHub, and Azure DevOps 2+ days ago with **zero progress**. This is the single biggest blocker for any meaningful handoff.
- **July 1 Canada Day edge case:** The model training pipeline runs automatically on July 1 but requires manual approval to promote from UAT → prod. Since it's a holiday, no one will approve it that day. Only **Lamine** and the SA (**Duke, who left last week**) have approval permissions. Someone must approve on Day 2 (Thursday). Nahid will alert Yassine/Lamine, but the new team needs pipeline permissions ASAP.

**2. Key Personnel Departures — Bus Factor Risk**
- **Duke** (SA who managed all access/permissions) left last week
- **Alex** (worked on training pipeline automation) left end of last year
- This leaves a critical gap — no clear SA has been assigned to replace Duke for provisioning FSO access

**3. No Formal Weekly/Monthly Checklist Exists**
There is no documented runbook or SOP for ongoing maintenance. Everything Nahid does was self-taught/figured out organically, not captured in any procedures document.

**4. Monitoring Gap — Only One Person Has Alerts**
- Currently **only Nahid** receives email alerts for ARise job failures and orchestrator failures
- The new team member must add themselves to: (a) Databricks job notification groups for all 5 ARise-related jobs in dev + prod, (b) Azure portal action groups for orchestrator function apps across all 3 environments
- Without this, failures will go unnoticed

---

### Technical Details Discussed

**ARise Monitoring Setup:**
- Long-term models (60-month forecast) cannot be monitored — no actuals exist until 2031
- Mid-term monitoring hasn't been implemented; drifting deprioritized in favor of other projects. Lamine may implement by end of year
- Short-term and flown-flight models are monitored. Monitors based on ~10% threshold from historical values; one trigger recently fired at 14%

**Data Flow:**
- Predictions/actuals stored in Databricks Unity Catalog tables (`ml_prod` schema)
- ARise reads from these tables, ingests via notebooks using a specific key for joins
- Batch processing happens overnight (UTC-5); not immediately merged

**Two Prediction Types (often confused):**
- *Scheduled* predictions — based on scheduled flight data, updated weekly as new schedule files arrive
- *Flown* predictions — re-run at month-end using actual flown features; compared against actual station/flight-level consumption
- Drift on scheduled data is expected and less alarming (aircraft type swaps, etc.); drift on flown data requires investigation

**Orchestrator Troubleshooting SOP (informal):**
1. Check orchestrator invocation table → identify which step failed (pre-process/process/post-process)
2. Check Databricks job runs directly for fuel demand orchestrator issues
3. For optimization models (pricing/nomination/supply-plan): check Service Bus messages from AKS cluster
4. Common failure: timeout (~45 min limit). If timeout, just rerun the full orchestrator — partial-rerun not supported
5. Resource unavailability (Databricks/AKS cluster) is frequent; resolve by rerun

**Automation Debt:**
- Automating baseline update post-training would be "not difficult" — requires adding a job to `EzPipeline` YAML. Was planned but deprioritized after Alex left. Important technical debt item.

---

### Action Items

| # | Action | Owner | Priority |
|---|--------|-------|----------|
| 1 | **Get Azure DevOps pipeline permissions** — specifically for approving model promotion | Anurag/Yassine | **CRITICAL** (for July 2) |
| 2 | Add self to Databricks notification groups for all 5 ARise jobs (dev + prod) | New MLE | **HIGH** |
| 3 | Add self to Azure portal action groups for orchestrator alerts (all 3 envs) | New MLE | **HIGH** |
| 4 | Reach out to Obi for ARise access coordination | Anurag | HIGH |
| 5 | Yassine to alert Lamine about July model promotion on holiday | Nahid | CRITICAL |
| 6 | Automate baseline update post-training in EzPipeline | Future dev work | MEDIUM |
| 7 | Review KT session recordings (Nahid will share links) | Anurag | MEDIUM |
| 8 | Identify and onboard replacement SA to replace Duke | IBM leadership | HIGH |

---

### Blockers

- **Access provisioning is stalled** — no clear owner after Duke's departure. Vikrant (new to FSO, handling all AI projects) may not have authority. Need someone from IBM side to identify who takes over access management.
- **Documentation gap** — the ARise setup was done "last minute" with no formal requirements from the DS team. Most knowledge lives in Nahid's head or unstructured KT recordings.