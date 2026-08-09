# MOPS 歷史資料可靠性

台股璞玉價值的 EPS 與配息條件只能使用已取得並解析完成的 MOPS 歷史資料。MOPS
端點偶爾會對 CI 網段回傳 security page 或暫時性空回應；這些資料不可被推定為
「沒有配息」或「沒有候選」。掃描器會將該股票保留在未完成佇列，並讓研究報表維持
`scan_state=building`，直到資料完成。

`MopsPublicClient` 的可靠性策略如下：

1. 每次報表請求之間保留固定間隔，避免短時間 burst 被服務端暫時封鎖。
2. redirect API 失敗時，先嘗試同一份公開報表的 legacy MOPS endpoint。
3. 兩條端點都失敗時，旋轉短期 session cookie，再於下一個 bounded retry 重試。
4. 失敗的 ticker 寫入 cache 的 `failures`，受 cooldown 控制，不會在每輪重複轟炸。
5. cache 只保存衍生 eligibility facts；未完成資料不會進入正式候選，也不會覆蓋上一個
   成功 release。

這不是繞過 MOPS 限流或安全機制；所有重試皆有上限，且不使用登入、隱藏端點或付費資料。
若資料仍不可取得，Mini App 應顯示歷史核對中／資料缺口，並保留 last-known-good
research release。
