# P1-06：point-in-time 基本面與公司行動

本模組把「資料期間」與「市場當時可取得時間」分開保存。回測或研究在決策時間 `decision_time` 只可使用：

- `point_in_time=true` 的快照；
- `as_of` 不晚於決策時間；
- `published_at`（若有）不晚於決策時間；
- 未知或格式錯誤的時間一律 fail closed。

公司行動使用受控類型（股利、分割、增減資、併購、停牌、下市等），並保留公告時間、實施日期、來源與抓取時間。未知類型不會被當成可回測事件。

`latest_fundamental_snapshot` 會選擇最新且已公開的快照；`audit_fundamental_snapshots` 會分離可用資料與未來資料缺口。這能防止今天修正後的財報、當前成分股或事後公司行動污染歷史結果。

## 驗證與回滾

- 測試涵蓋未來發布日拒絕、快照選擇、資料缺口、公司行動正規化。
- 回滾方式：撤回本 PR；既有舊快照仍可讀取，但回測會維持原本的 point-in-time 必要條件。
- 後續接線：將 `four_strategy_walk_forward` 的基本面選取改用此模組，並在 P1-06 後半補上 MOPS／SEC 的 `published_at` 與公司行動快照欄位。