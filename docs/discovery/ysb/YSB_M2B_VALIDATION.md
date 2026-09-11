# YSB M2B validation

Mart: `C:\Users\NPC-003\Documents\ChatGPT\Business Ops Workbench\business-ops-workbench\data\marts\ysb\mart_merchant_monthly_priority.csv`
Target month: 2026-05; valid shared GMV merchants=82.

## 2026-05 regional summary

- Regional GMV (shared valid population): 7101294.94
- Previous-month GMV (shared valid population): 9487204.62
- Regional GMV MoM: -25.15%
- GMV decline merchants: 64
- GMV growth merchants: 18
- Aftersales high/worsening merchants: 6
- PRIORITY: 18
- ATTENTION: 6
- WATCHLIST: 25
- DATA_QUALITY_ALERT: 32

## Top GMV loss merchants

| merchant | current_gmv | previous_gmv | gmv_loss | loss_contribution | scale | priority |
|---|---:|---:|---:|---:|---|---|
| 四川众恩德科技 | 90271.63 | 476978.23 | 386706.60 | 16.16% | KEY | PRIORITY |
| 希尔康 | 214109.73 | 531311.37 | 317201.64 | 13.26% | KEY | PRIORITY |
| 鲁鸿医疗 | 1098122.69 | 1378516.70 | 280394.01 | 11.72% | KEY | PRIORITY |
| 四川微至 | 58804.78 | 229498.96 | 170694.18 | 7.13% | KEY | PRIORITY |
| 聚药汇 | 104870.63 | 246505.76 | 141635.13 | 5.92% | KEY | PRIORITY |
| 四川多多邦健康管理 | 117565.96 | 230184.50 | 112618.54 | 4.71% | KEY | PRIORITY |
| 四川弗佑斯贸易 | 177421.79 | 278886.68 | 101464.89 | 4.24% | KEY | WATCHLIST |
| 四川锐源通 | 24716.71 | 104299.00 | 79582.29 | 3.33% | MID | PRIORITY |
| 壹药师 | 281899.83 | 360492.01 | 78592.18 | 3.29% | KEY | WATCHLIST |
| 济郎中医药科技 | 344720.02 | 418735.61 | 74015.59 | 3.09% | KEY | WATCHLIST |

## Acceptance checks

- Priority count is less than M2A business alert pool: 18 < 38.
- Missing/unresolved rows in GMV loss ranking: 0.
- Sample rows written: 15.
- Priority reasons are dimension-level and explainable; no composite health score is used.
