# Validation Report — 2026-05-22T12:51:53

Indices: 42 (7 broad, 15 sector, 9 strategy, 11 thematic).
Source: index_history/data/index_membership_history.csv

=== Gate 1: snapshot match (today) ===
  ✓ all 42 indices match their published snapshot
  Result: 0/42 mismatches

=== Gate 2: internal consistency ===
  FAIL  Nifty Next 50 ⊆ Nifty 100                   violated on 19/19 dates  (worst: 5 extra symbols on 2020-01-01)
  FAIL  Nifty 100 ⊆ Nifty 500                       violated on 3/19 dates  (worst: 1 extra symbols on 2017-01-01)
  FAIL  Nifty Midcap 150 ⊆ Nifty 500                violated on 13/19 dates  (worst: 5 extra symbols on 2018-07-01)
  FAIL  Nifty Smallcap 250 ⊆ Nifty 500              violated on 12/19 dates  (worst: 3 extra symbols on 2018-01-01)
  FAIL  Nifty Bank ⊆ Nifty 500                      violated on 1/19 dates  (worst: 1 extra symbols on 2017-07-01)
  FAIL  Nifty IT ⊆ Nifty 500                        violated on 6/19 dates  (worst: 1 extra symbols on 2020-01-01)
  FAIL  Nifty Metal ⊆ Nifty 500                     violated on 1/19 dates  (worst: 2 extra symbols on 2022-07-01)
  FAIL  Nifty Realty ⊆ Nifty 500                    violated on 5/19 dates  (worst: 3 extra symbols on 2022-01-01)
  FAIL  Nifty Energy ⊆ Nifty 500                    violated on 16/19 dates  (worst: 6 extra symbols on 2018-07-01)
  FAIL  Nifty PSU Bank ⊆ Nifty 500                  violated on 17/19 dates  (worst: 2 extra symbols on 2021-07-01)
  FAIL  Nifty Financial Services ⊆ Nifty 500        violated on 1/19 dates  (worst: 1 extra symbols on 2018-01-01)
  FAIL  Nifty Media ⊆ Nifty 500                     violated on 19/19 dates  (worst: 6 extra symbols on 2019-07-01)
  FAIL  Nifty Oil & Gas ⊆ Nifty 500                 violated on 1/19 dates  (worst: 1 extra symbols on 2022-07-01)
  Result: 13/20 invariants failed

=== Gate 3: famous transitions ===
  [PASS] HDFC absent post-merger — HDFC on 2023-07-14: expected=False got=False
  [PASS] HDFCBANK still in Nifty 50 on merger day — HDFCBANK on 2023-07-14: expected=True got=True
  [PASS] SHRIRAMFIN added 2024-03-28 — SHRIRAMFIN on 2024-03-28: expected=True got=True
  [PASS] UPL excluded 2024-03-28 — UPL on 2024-03-28: expected=False got=False
  [PASS] BPCL was member on 2022-01-01 — BPCL on 2022-01-01: expected=True got=True
  [PASS] ETERNAL (was ZOMATO) joined Nifty 50 in Mar 2025 — ETERNAL on 2025-04-01: expected=True got=True
  [PASS] ETERNAL NOT in Nifty 50 pre-Mar 2025 — ETERNAL on 2024-12-31: expected=False got=False
  [PASS] INDIGO joined Nifty 50 on 2025-09-30 — INDIGO on 2025-10-01: expected=True got=True
  [PASS] MAXHEALTH joined Nifty 50 on 2025-09-30 — MAXHEALTH on 2025-10-01: expected=True got=True
  [PASS] HEROMOTOCO excluded from Nifty 50 on 2025-09-30 — HEROMOTOCO on 2025-10-01: expected=False got=False
  [PASS] INDUSINDBK excluded from Nifty 50 on 2025-09-30 — INDUSINDBK on 2025-10-01: expected=False got=False
  [PASS] ATGL (was ADANIGAS) member of Nifty 500 in 2021 — ATGL on 2021-06-01: expected=True got=True
  [PASS] LTM (was MINDTREE→LTIM) member of Nifty 500 in 2022 — LTM on 2022-12-31: expected=True got=True
  [PASS] HDFC merged into HDFCBANK — HDFC absent from Nifty Bank post-2023-07-13 — HDFC on 2023-07-14: expected=False got=False
  [PASS] HDFCBANK is in Nifty Bank today — HDFCBANK on 2026-05-22: expected=True got=True
  [PASS] ICICIBANK is in Nifty Bank today — ICICIBANK on 2026-05-22: expected=True got=True
  [PASS] TCS is in Nifty IT today — TCS on 2026-05-22: expected=True got=True
  [PASS] INFY is in Nifty IT today — INFY on 2026-05-22: expected=True got=True
  [PASS] LTM (was LTIM) is in Nifty IT today — LTM on 2026-05-22: expected=True got=True
  [PASS] HINDUNILVR is in Nifty FMCG today — HINDUNILVR on 2026-05-22: expected=True got=True
  [PASS] ITC is in Nifty FMCG today — ITC on 2026-05-22: expected=True got=True
  [PASS] SUNPHARMA is in Nifty Pharma today — SUNPHARMA on 2026-05-22: expected=True got=True
  [PASS] CIPLA is in Nifty Pharma today — CIPLA on 2026-05-22: expected=True got=True
  [PASS] MARUTI is in Nifty Auto today — MARUTI on 2026-05-22: expected=True got=True
  [PASS] M&M is in Nifty Auto today — M&M on 2026-05-22: expected=True got=True
  [PASS] ONGC is in Nifty CPSE today — ONGC on 2026-05-22: expected=True got=True
  [PASS] COALINDIA is in Nifty CPSE today — COALINDIA on 2026-05-22: expected=True got=True
  [PASS] HINDUNILVR is in Nifty MNC today — HINDUNILVR on 2026-05-22: expected=True got=True
  [PASS] HDFCBANK is in Nifty Services today — HDFCBANK on 2026-05-22: expected=True got=True
  Result: 0/29 failures

=== Gate 4: daily cardinality (fixed-size indices only) ===
  FAIL  2014-01-01  Nifty Next 50                     58 (expected 50)
  FAIL  2014-01-01  Nifty 100                         101 (expected 100)
  FAIL  2014-01-01  Nifty 500                         516 (expected 500)
  FAIL  2014-01-01  Nifty Alpha 50                    69 (expected 50)
  FAIL  2014-01-01  Nifty High Beta 50                54 (expected 50)
  FAIL  2014-01-01  Nifty Midcap 50                   53 (expected 50)
  FAIL  2014-01-01  Nifty Commodities                 31 (expected 30)
  FAIL  2014-01-01  Nifty Consumption                 33 (expected 30)
  FAIL  2014-01-01  Nifty MNC                         17 (expected 30)
  FAIL  2014-04-01  Nifty Next 50                     55 (expected 50)
  FAIL  2014-04-01  Nifty 500                         516 (expected 500)
  FAIL  2014-04-01  Nifty Alpha 50                    69 (expected 50)
  FAIL  2014-04-01  Nifty High Beta 50                54 (expected 50)
  FAIL  2014-04-01  Nifty Midcap 50                   54 (expected 50)
  FAIL  2014-04-01  Nifty Commodities                 31 (expected 30)
  FAIL  2014-04-01  Nifty Consumption                 32 (expected 30)
  FAIL  2014-04-01  Nifty MNC                         16 (expected 30)
  FAIL  2014-07-01  Nifty Next 50                     55 (expected 50)
  FAIL  2014-07-01  Nifty 500                         516 (expected 500)
  FAIL  2014-07-01  Nifty Alpha 50                    69 (expected 50)
  FAIL  2014-07-01  Nifty High Beta 50                54 (expected 50)
  FAIL  2014-07-01  Nifty Midcap 50                   54 (expected 50)
  FAIL  2014-07-01  Nifty Commodities                 31 (expected 30)
  FAIL  2014-07-01  Nifty Consumption                 32 (expected 30)
  FAIL  2014-07-01  Nifty MNC                         16 (expected 30)
  FAIL  2014-10-01  Nifty Next 50                     54 (expected 50)
  FAIL  2014-10-01  Nifty 500                         513 (expected 500)
  FAIL  2014-10-01  Nifty Alpha 50                    69 (expected 50)
  FAIL  2014-10-01  Nifty High Beta 50                55 (expected 50)
  FAIL  2014-10-01  Nifty50 Value 20                  23 (expected 20)
  FAIL  2014-10-01  Nifty Midcap 50                   55 (expected 50)
  FAIL  2014-10-01  Nifty Commodities                 31 (expected 30)
  FAIL  2014-10-01  Nifty Consumption                 31 (expected 30)
  FAIL  2014-10-01  Nifty MNC                         16 (expected 30)
  FAIL  2015-01-01  Nifty Next 50                     54 (expected 50)
  FAIL  2015-01-01  Nifty 500                         513 (expected 500)
  FAIL  2015-01-01  Nifty Alpha 50                    70 (expected 50)
  FAIL  2015-01-01  Nifty High Beta 50                55 (expected 50)
  FAIL  2015-01-01  Nifty50 Value 20                  23 (expected 20)
  FAIL  2015-01-01  Nifty Midcap 50                   55 (expected 50)
  FAIL  2015-01-01  Nifty Commodities                 31 (expected 30)
  FAIL  2015-01-01  Nifty Consumption                 31 (expected 30)
  FAIL  2015-01-01  Nifty MNC                         16 (expected 30)
  FAIL  2015-04-01  Nifty Next 50                     53 (expected 50)
  FAIL  2015-04-01  Nifty 100                         99 (expected 100)
  FAIL  2015-04-01  Nifty 500                         505 (expected 500)
  FAIL  2015-04-01  Nifty Alpha 50                    69 (expected 50)
  FAIL  2015-04-01  Nifty High Beta 50                56 (expected 50)
  FAIL  2015-04-01  Nifty50 Value 20                  23 (expected 20)
  FAIL  2015-04-01  Nifty Midcap 50                   53 (expected 50)
  FAIL  2015-04-01  Nifty Commodities                 31 (expected 30)
  FAIL  2015-04-01  Nifty MNC                         15 (expected 30)
  FAIL  2015-07-01  Nifty Next 50                     53 (expected 50)
  FAIL  2015-07-01  Nifty 100                         99 (expected 100)
  FAIL  2015-07-01  Nifty 500                         505 (expected 500)
  FAIL  2015-07-01  Nifty Alpha 50                    69 (expected 50)
  FAIL  2015-07-01  Nifty High Beta 50                56 (expected 50)
  FAIL  2015-07-01  Nifty Low Volatility 50           49 (expected 50)
  FAIL  2015-07-01  Nifty50 Value 20                  23 (expected 20)
  FAIL  2015-07-01  Nifty Midcap 50                   53 (expected 50)
  ... (548 more)
  (skipped 66 pre-launch checks)
  Result: 608/984 cardinality failures

  Per-index failure counts (top 10):
    Nifty Next 50                     49
    Nifty Consumption                 47
    Nifty50 Value 20                  46
    Nifty 100                         45
    Nifty High Beta 50                43
    Nifty 500                         42
    Nifty Midcap 50                   40
    Nifty Smallcap 50                 40
    Nifty Alpha 50                    38
    Nifty Midcap 150                  38

=== Gate 5: SKIPPED ===

=== Summary ===
  Gate 1 snapshot match (today)   : 0 / 42 mismatches
  Gate 2 internal consistency     : 13 / 20 invariants failed
  Gate 3 famous transitions       : 0 / 29 failed
  Gate 4 daily cardinality        : 608 / 984 failed (fixed-size only)
  Gate 5 Wayback cross-check      : 0 / 0 drifts
  TOTAL: 621 / 1075
