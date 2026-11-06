# 更新記錄

## v0.1.3

- 加上 `.gitattributes`：`*.sh` 一律以 LF 取出。之前在 Windows 上 `core.autocrlf=true` 時，submodule 裡的 `gate.sh` 會是 CRLF，照 README 用 `cp` 複製到專案後，bash 可能因為 `$''` 執行失敗。
- `gate.sh`：`&&` 和 `[` 之間補一個空格（v0.1.2 漏掉，不影響執行）。
- **升級注意**：v0.1.2 在 Windows 上用 `cp` 複製過 `gate.sh` 的專案，確認檔案是 LF（`git ls-files --eol .claude/hooks/gate.sh` 的 `w/` 要是 `lf`）。升到 v0.1.3 後重新複製一次即可。

## v0.1.2

- `gate.sh`：判斷有沒有改東西的 `git diff` 不再把警告（例如 Windows 上 `core.autocrlf=true` 時的「LF will be replaced by CRLF」）混進交給 AI 的訊息。
- **升級注意**：`gate.sh` 是複製到專案裡的，升級 submodule 不會更新它。要重新執行 `cp tools/referee/templates/go/.claude/hooks/gate.sh .claude/hooks/`。
- README 的驗證狀態：BeThere 實際導入的三關結果，以及 Claude Code 實際觸發 Stop hook，改列為已驗證。

## v0.1.1

- `crap` 不加 `--base`（整個專案）時，超標的函式後面也附改善方向（「要拆函式」或「覆蓋率要到 X%」），跟 `--base` 和 JSON 報告一致。
- Go 檢查員的 `functions` 不再把 `workers` 寫進 `settings`：量 CRAP 不跑 gremlins，`--workers` 不生效，之前沒帶時會顯示「workers null」。

## v0.1.0

第一版。

- 裁判核心：讀 `.referee.json`，執行設定檔指定的檢查員指令，讀記分表，判定單元測試、CRAP、抓錯檢查三道關；`test`、`crap`、`mutation`、`check` 四個指令，文字和 JSON 報告（`referee.report/1`）。
- 合約：檢查員的呼叫方式（`REFEREE_OUT`、`REFEREE_CONTEXT`）、函式表（`referee.functions/1`）、改壞版本表（`referee.mutants/1`）、路徑比對規則，寫在 `docs/合約.md`。
- Go 標準檢查員 `inspectors/go.py`：gocyclo、gremlins 的結果轉成記分表，參數 `--coverage-scope`、`--workers`。
- 排除清單沿用 quality-tools v2.4.0 的格式（含 `column`）。改名的檔案只算真的改到的行。
- 專案範本 `templates/go/`：`.referee.json`、`.referee-equivalents.json`、Claude Code 的 Stop hook（`gate.sh`）和 `settings.json`、GitHub Actions 的三關 workflow。
- 開發用：`selftest.py`（Go 範例專案的全部情境，含 gate.sh）、`dev/parity_qt.py`（和 quality-tools v2.4.0 對照）、`dev/walkthrough_bethere.py`（照 README 在 BeThere 的暫存複本上走一遍）、`.github/workflows/selftest.yml`。

已知限制見 README。workflow 還沒在 runner 上跑過。
