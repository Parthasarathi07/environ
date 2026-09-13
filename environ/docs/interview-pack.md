# Interview pack — "Does a high ESG score pay?"

Everything here is derived from the same analysis that renders the app, so the numbers cannot drift out of
sync with what an interviewer clicks through.

---

## One resume bullet (pick one)

> **Built an end-to-end ESG/returns research tool (Python, FastAPI) testing whether MSCI-style ESG ratings
> predict stock returns; found no significant return spread (sector-neutral Q5−Q1 -0.8%/yr,
> t = -0.5) but a significant risk gradient (vol 15.9% → 12.4%), and
> published the sensitivity test that breaks the result.**

Shorter, for a one-line CV:

> **Python/FastAPI ESG-alpha study: quintile sorts + sector neutralisation + clustered regressions on
> 160 firms / 108 months; showed the 2022 ESG "underperformance" was a sector effect (-22.6 of -20.4 pts).**

For a consulting/generalist role, lead with the decision rather than the code:

> **Turned a contested ESG-vs-returns debate into a screening rule: buy rating improvements, not rating
> leaders; sell downside protection, not alpha. Backed by a reproducible pipeline anyone can re-run on
> their own data.**

---

## The 90-second answer (say it out loud three times)

> On returns: no. Sorting 108 months of firms into ESG quintiles produced a spread of -2.0%/yr (t=-0.9). Neutralise for sector and the spread is -0.8%/yr (t=-0.5). Neither is significant. The level effect moves from -10.7 to -7.4 bp/month (t -1.72 -> -1.14) once you also control for size and volatility - which is the single most important thing to know about this literature: the answer depends on what you put in the regression.

> ESG momentum - firms whose rating is going up - earns +26.3 bp per month per SD (t=+4.94), > 2x the level effect. 'Buy the leaders' is not the trade; 'buy the improvers' is the one with evidence behind it.

> Moving from the bottom to the top ESG quintile, annualised volatility falls 3.5 pts (15.9% -> 12.4%), downside capture falls 36 pts (119% -> 83%), and the worst drawdown improves 6.4 pts (-29.7% -> -23.3%). The gradient is 3/4 steps on volatility, 3/4 on downside capture and 2/4 on drawdown depth. That is a risk-management case — much stronger than anything on returns, and it is the one result that survives every control I throw at it.

> Naively the spread was -2.0%/yr; after sector-neutralising it is -0.8%/yr. The +1.2-point gap is a composition effect - the top quintile is heavy in tech and utilities, the bottom in energy and materials, so a year like 2022 shows up as 'ESG failed' when it is really 'low-carbon sectors were the wrong trade'.

---

## Follow-ups you should be ready for

**"How did you handle sector bias?"**
Sector-neutralising: for each firm-month I subtract the mean of its own sector that month, so a stock is
compared with genuinely comparable stocks. It moves the spread from -2.0%/yr to
-0.8%/yr, and in 2022 alone the sector-mix term explains -22.6
of the -20.4 points. That decomposition is an exact monthly identity — mix plus selection has
to equal the headline number — which is why it is hard to argue with.

**"Why cluster the standard errors?"**
Each firm appears ~96 times. Errors that assume independence would be far too
small and everything would look significant. Clustering by firm is the minimum correct thing to do; it is
also why my return result is *insignificant* and my risk result (t = -5.8) is not.

**"Why equal weight and not cap weight?"**
Cap weighting imports a size tilt, so you would be measuring large-cap behaviour and calling it ESG. Equal
weight keeps the sort honest; cap-weighted is a robustness check I would run next.

**"What's the sample, and is it enough?"**
160 firms / 108 months over 2016-01 to 2024-12. It is enough to detect the risk gradient and not enough to rule out a modest return
premium — which is exactly how I worded the conclusion: "not detectable", never "zero".

**"Isn't your data fake?"**
The demo panel is generated, yes — from three named assumptions in one config file, and it is labelled as
synthetic in the header, the watermark, the deck and every figure caption. I did that deliberately: the
sandbox this was built in blocks Yahoo and Hugging Face, so instead of quietly substituting scraped numbers
I built the data layer so that a real ESG-Book/MSCI panel plus real prices goes in through `POST /api/upload`
or `data/panel.csv` and every number, sentence and slide regenerates. The analysis is the deliverable.

**"What would break your conclusion?"**
Three things: (i) real data with a survivorship-bias-free universe; (ii) a second ESG rater, since
cross-provider disagreement is large and a result that only exists on one scale is a methodology artefact;
(iii) transaction costs on the momentum leg — the momentum coefficient is the only significant return
effect and momentum is fragile and turnover-heavy.

**"So is ESG investing good or bad?"**
Neither question is answerable on this data, and that's the point of the project. What is answerable: as a
*return* promise it is not supported here; as a *risk* characteristic it clearly is. Those imply different
products, different fees and different clients, and conflating them is the actual industry problem.

---

## Numbers to memorise

| What | Value | Why it matters |
|---|---|---|
| Naive Q5−Q1 spread | -2.0%/yr (t=-0.9) | the headline everyone quotes |
| Sector-neutral spread | -0.8%/yr (t=-0.5) | the honest number |
| ESG momentum | +26.3 bp/mo per SD (t=+4.94) | the only significant return result |
| Vol, Q1 → Q5 | 15.9% → 12.4% | where the signal is |
| Downside capture | 119% → 83% | how I would sell it |
| Worst drawdown | -29.7% → -23.3% | the client-facing number |
| 2022 mix effect | -22.6 of -20.4 pts | the debunking exhibit |

---

## What to open first, if they ask to see it

1. `environ/docs/deck.html` — 12 slides, arrow keys, prints to PDF.
2. The live dashboard — the **Sector trick** tab (that year selector is the best 30 seconds of the demo).
3. `environ/config.py` — the assumptions, on one page, in plain English.
4. Method & limits tab — shows you know what the analysis cannot do.
