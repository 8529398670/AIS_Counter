# AIS treatment comparisons and stats (C4–C7)

What each treatment group is, which comparisons answer which question, and which rows of the AIS Counter export to read.

*Updated 10 November 2026: the export now has a two-way ANOVA (drug × add-on), with simple effects. See sections 3, 5 and 6.*

## 1. The experiment

Each culture (C4, C5, C6, C7) is split in half:

- **DMSO:** the vehicle control.
- **TM (tunicamycin):** causes ER stress.

After 24 hours, each half is split three ways: nothing added, NaCl added, or KCl added. They are fixed 3 hours later.

- **KCl** depolarizes the neurons (the stimulus).
- **NaCl** is the osmolarity control for KCl: same salt load, no depolarization.
- **The first drug stays on.** "DMSO 24Hr KCl 3Hr" means 24 h of DMSO, then 3 more hours of DMSO + KCl (27 h in all).

That gives six groups per culture:

|  | **Nothing added** | **+ NaCl (3 h)** | **+ KCl (3 h)** |
|:-:|:-:|:-:|:-:|
| **DMSO (24 h)** | DMSO | DMSO + NaCl | DMSO + KCl |
| **TM (24 h)** | TM | TM + NaCl | TM + KCl |

This is a 2 × 3 design: two **drugs** (DMSO, TM) crossed with three **add-ons** (none, NaCl, KCl). The two-way ANOVA uses exactly these two factors.

## 2. How the file names read

Example: C7 DMSO 24Hr + KCl 3Hr B-04.czi

| **Part** | **Meaning** |
|:-:|:-:|
| C7 | Culture 7 |
| DMSO 24Hr + KCl 3Hr | The treatment: drugs in the order added, each with its time |
| B | Coverslip B. A, B, C are different coverslips on the same slide, from the same culture |
| -04 | The 4th image of that coverslip. No number means the 1st (ZEN numbers repeated names -02, -03…) |

The app guesses the treatment from the name. The admin checks the guesses in the Treatments dialog and saves them. Spellings that differ only in case, "+", spacing or Hr/hrs/h (e.g. "24Hr" vs "24 hrs") can be merged with the "matched" guess.

The two-way ANOVA also reads the names: the first drug is the **drug** factor, and whatever was added after it is the **add-on** factor ("none" when nothing was). The times are ignored.

## 3. The questions and the comparisons that answer them

| **Question** | **Compare** | **Why this control** |
|:-:|:-:|:-:|
| **A. Does ER stress shorten the AIS?** | TM vs DMSO | DMSO is TM's vehicle, so any difference is TM itself |
| **B. Does KCl shorten the AIS further under ER stress?** (the main question) | TM + KCl vs TM + NaCl | Both got TM and the same salt load. Only depolarization differs |
| **C. What does KCl do without ER stress?** | DMSO + KCl vs DMSO + NaCl | Same logic as B, in the vehicle group |
| D. Does the salt load alone do anything? | TM + NaCl vs TM, and DMSO + NaCl vs DMSO | Checks that NaCl is a clean control |
| E. Is the KCl effect different with TM than without? | (TM+KCl − TM+NaCl) vs (DMSO+KCl − DMSO+NaCl) | The interaction. The two-way ANOVA's drug × add-on row tests a broader version; see sections 5 and 6 |

**The KCl control is NaCl, not DMSO.** Comparing TM + KCl with DMSO mixes the TM effect, the salt effect and the KCl effect, so it answers none of the questions above.

## 4. What counts as one sample

**One culture = one sample.** Coverslips and images from the same culture are not independent: they share the same dissection, plating and day. Treating 100 AIS from one culture as 100 samples makes p-values far too small (pseudo-replication).

So for each culture and treatment, the app averages all AIS into one **culture mean**. With 4 cultures, each treatment has n = 4.

Two things must hold in the app:

- **Each culture is its own batch.** The app treats one batch as one culture. If two cultures were uploaded as one batch, they count as one.
- **Every treatment needs at least 2 cultures.** Otherwise the app falls back to image means or individual values, and the export says so.

## 5. Which export rows to read

The export lists many tests. Here is what each is for, most useful first.

### Paired tests on culture means (best fit for C4–C7)

Every culture got all six treatments, so each culture can be compared with itself. Differences between cultures (one culture's AIS just longer overall) cancel out. This is usually more sensitive than the unpaired tests.

- **Repeated-measures ANOVA:** is there any difference among the six groups?
- **Friedman:** the same question without assuming normal data.
- **Paired t-test (Holm):** each pair of groups. **Read the rows for the pairs in section 3.**

Only cultures that have all six treatments are used. Any culture left out is listed in the export.

### Two-way ANOVA on culture means (new)

Tick **"Two-way ANOVA, then simple effects (Holm)"** in the Compare dialog (it is ticked by default), and pick its factors under **"Two-way ANOVA factors"**:

- **Drug × add-on** (default; the one that fits this experiment). Three rows:
  - **two-way ANOVA: drug** — does TM differ from DMSO, averaged over the add-ons?
  - **two-way ANOVA: add-on** — do none, NaCl and KCl differ, averaged over the drugs?
  - **two-way ANOVA: drug × add-on** — the interaction: does the add-on pattern differ between DMSO and TM? This is the closest the export comes to question E.
- **Treatment × culture.** The six treatments as one factor and the culture as the other. On culture means this takes out the differences between cultures, like the paired tests: its treatment row gives the same F as the repeated-measures ANOVA.

The sums of squares are Type III, so groups of different sizes are handled correctly. The note on each row gives the degrees of freedom, e.g. F(2, 18).

After the ANOVA rows come the **simple effects (Holm)**: t-tests on the two-way ANOVA's pooled error, Holm-corrected together. With drug × add-on there are 9 of them:

- **Within each drug**, every add-on pair (the note says "within DMSO" or "within TM"). **TM + NaCl vs TM + KCl is question B**, DMSO + NaCl vs DMSO + KCl is question C, and the bare drug vs its NaCl group is question D.
- **At each add-on**, DMSO vs TM (the note says "at none", "at NaCl" or "at KCl"). **"DMSO vs TM at none" is question A.**

Because they are corrected over 9 comparisons rather than 15, they are a little less strict than the 15-pair rows.

**Caution:** with drug × add-on, the culture means are treated as independent, like the unpaired tests below. It does not use the fact that each culture got all six treatments. If the cultures differ a lot overall, the paired tests will be more sensitive.

The same two-way block is also run on image means and individual values. The caution in "Image means and individual values" below applies to those rows.

If the names don't form a full 2 × 3 grid (for example, two treatments with the same drug and add-on but different times), the export shows a single "two-way ANOVA" row saying why, instead of results.

### Unpaired tests on culture means (rows marked "main")

The same culture means, treated as if each group came from different cultures.

- **One-way ANOVA**, then each pair by **Tukey HSD**, **Welch t-test (Holm)** and **Dunnett**.
- Also **Kruskal-Wallis** (no normality assumption).
- The box plot's brackets show the Tukey results.

**Dunnett compares every group with one control, which the app picks as plain DMSO.** That only answers question A. For B and C, use the Tukey or Welch rows for the KCl vs NaCl pairs, or the two-way simple effects.

### Image means and individual values (supporting only)

The same ANOVA blocks run on one mean per image, and on every single AIS. **These are not independent samples, so their p-values run too low.** Use them to describe the data, not to claim significance.

The **Kolmogorov-Smirnov** rows compare the whole distribution of AIS lengths (the cumulative plots), also on individual values. Useful to show whether the whole distribution shifted or only some cells. Same caution about p-values.

## 6. Points to keep in mind

**n = 4 is small.** Only large effects will reach p < 0.05. A non-significant result means "not shown", not "no effect". Report effect sizes (the difference in mean AIS length, in µm) along with p-values.

**The Holm correction in the export covers all 15 pairs.** With six groups there are 15 pairs, and the paired and unpaired rows correct for all of them. The two-way simple effects correct over their own 9. If questions A–C were planned in advance, it's fair to correct over just those 3. Take the 3 uncorrected p-values, sort them, multiply the smallest by 3, the next by 2 and the largest by 1. If a result comes out smaller than the one before it, raise it to match.

**The interaction (question E).** The two-way ANOVA's **drug × add-on** row tests whether the add-on pattern differs between DMSO and TM. That includes "none" as well as NaCl and KCl, so it is broader than question E, and it does not pair the cultures. A significant row says the drugs respond to the add-ons differently. The simple effects then show where. For the sharpest test of question E itself, work it out per culture:

1. KCl effect with TM = (TM + KCl) − (TM + NaCl)
2. KCl effect without TM = (DMSO + KCl) − (DMSO + NaCl)
3. Difference = step 1 − step 2

That gives 4 numbers (one per culture). Test whether their mean differs from 0 with a one-sample t-test. This equals a paired t-test of step 1 against step 2.

**The time on the first drug differs between groups.** The no-salt groups are fixed at 24 h. The NaCl and KCl groups are fixed at 27 h. The NaCl groups also cover this difference, which is another reason B and C compare KCl with NaCl rather than with the no-salt group.

## 7. Short version

- **One culture = one sample**, n = 4 per group.
- **Main question:** TM + KCl vs TM + NaCl. Read the paired t-test row for that pair, or the two-way simple effect "within TM".
- **Two-way ANOVA (drug × add-on):** drug, add-on and their interaction in three rows, then 9 simple effects. It treats cultures as independent.
- **KCl is always compared with NaCl, never with DMSO.**
- **Dunnett vs DMSO** only answers TM vs DMSO.
- **Image-level and individual-AIS p-values** are too optimistic. Treat them as description only.
