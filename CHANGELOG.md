# 更新記錄

## v0.1.0

第一版。

- 裁判核心：讀 `.referee.json`，執行設定檔指定的檢查員指令，讀記分表，判定單元測試、CRAP、抓錯檢查三道關；`test`、`crap`、`mutation`、`check` 四個指令，文字和 JSON 報告（`referee.report/1`）。
- 合約：檢查員的呼叫方式（`REFEREE_OUT`、`REFEREE_CONTEXT`）、函式表（`referee.functions/1`）、改壞版本表（`referee.mutants/1`）、路徑比對規則，寫在 `docs/合約.md`。
- Go 標準檢查員 `inspectors/go.py`：gocyclo、gremlins 的結果轉成記分表，參數 `--coverage-scope`、`--workers`。
- 排除清單沿用 quality-tools v2.4.0 的格式（含 `column`）。改名的檔案只算真的改到的行。
- 專案範本 `templates/go/`：`.referee.json`、`.referee-equivalents.json`、Claude Code 的 Stop hook（`gate.sh`）和 `settings.json`、GitHub Actions 的三關 workflow。
- 開發用：`selftest.py`（Go 範例專案的全部情境，含 gate.sh）、`dev/parity_qt.py`（和 quality-tools v2.4.0 對照）、`dev/walkthrough_bethere.py`（照 README 在 BeThere 的暫存複本上走一遍）、`.github/workflows/selftest.yml`。

已知限制見 README。workflow 還沒在 runner 上跑過。
