# P7-01～P7-02 設定與安全

統一 runtime freshness、timeout、retry、storage 與 dashboard 設定，啟動時驗證 HTTPS 與非負限制；提供 workflow 靜態檢核，要求明確 permissions 且禁止把 secret 寫入 log。敏感值只由環境變數注入，不進入 artifact。

驗證：`pytest -q tests/test_settings_security.py`。

回滾：撤回本 PR 即可移除設定與 workflow audit。
