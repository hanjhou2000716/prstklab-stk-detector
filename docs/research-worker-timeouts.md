# 研究工作流單工逾時

八個策略工作者都以 `WORKER_TIMEOUT_SECONDS`（手動執行預設 240 秒）執行，
逾時會寫入 `research-artifacts/scan-failures.ndjson`，並由研究報表明確標示
來源失敗／資料缺口。工作流不會因單一來源卡住而把半成品誤發布；正式發布仍須通過
production research gate。若資料來源暫時變慢，可在下一輪以較高的逾時重試，不能把
逾時記錄刪除或解釋為沒有候選。
