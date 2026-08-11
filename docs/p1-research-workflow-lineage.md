# P1：研究工作流血緣綁定

`unified-research-report.yml` now passes the exact GitHub Actions run ID、attempt
and checkout SHA to `src.run_research_report`。報表及每個可見候選會保存相同的
`research_run`／`source_commit_sha`，因此可以從公開 release 追溯到產生它的
workflow 執行，不會把重跑或舊快照誤當成最新結果。

## 驗證

- workflow contract test checks both explicit flags。
- Existing research run contract tests verify propagation to the report and
  candidates。

## 回滾

撤回本 PR 即可回到由 `GITHUB_*` 環境變數自動推導的相容行為；不會修改既有
市場資料或 Telegram 發送閘門。
