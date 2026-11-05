# quality-referee

裁判和檢查員分開的品質工具。裁判不認得任何語言，只執行設定檔寫的指令、讀檢查員交出的記分表，依門檻判定單元測試、CRAP、抓錯檢查三道關。

目前狀態：R2，裁判核心、合約，加上 Go 標準檢查員（`inspectors/go.py`）。完整的介面定義在 [docs/合約.md](docs/合約.md)。

## 用法

Python 3.8 以上，只用標準函式庫。在專案根目錄放 `.referee.json`（格式見合約），然後：

```
python referee.py test
python referee.py crap --base origin/main
python referee.py mutation --base origin/main --json mutation.json
python referee.py check --base origin/main --skip mutation --json reports/
```

結束碼：0 通過，1 沒過門檻，2 量測失敗或設定有誤。

## 測試

```
python -m unittest
```

端到端測試在暫存 git repo 裡用 `tests/fake_inspector.py` 當檢查員，不需要任何語言的量測工具。

## Go 標準檢查員

`inspectors/go.py` 要在 go.mod 所在的專案根目錄執行，由裁判啟動。`.referee.json` 這樣寫：

```json
"crap": {"threshold": 12,
         "inspector": ["python", "tools/referee/inspectors/go.py", "functions", "--coverage-scope", "module"]},
"mutation": {"inspector": ["python", "tools/referee/inspectors/go.py", "mutants", "--coverage-scope", "module", "--workers", "4"]}
```

- `--coverage-scope package|module`（預設 package）：module 時，別的套件的測試跑到的程式也算覆蓋率；抓錯檢查改用 gremlins 的 `--integration --coverpkg`，每個改壞的版本跑整個模組的測試。
- `--workers N`：gremlins 同時跑幾個，沒給就用 gremlins 的預設值。
- gocyclo、gremlins（都是 v0.6.0）第一次執行時用 `go install` 裝到 `REFEREE_TOOLS_DIR`（預設 `~/.cache/quality-referee`），之後直接執行，斷網也能量。
- 要跳過的目錄寫在 `.referee.json` 的 `exclude`，檢查員從 context 讀，不用在 `inspector` 指令再寫一次。

已知限制：

- gremlins 的 `--integration`（`--coverage-scope module` 的抓錯檢查）一律從模組根目錄跑 `go test ./...`，`exclude` 裡的套件測試照樣會跑。排除的套件只要有一個測試失敗，module 範圍的抓錯檢查就以結束碼 2 停下（gremlins 執行失敗）。quality-tools v2.4.0 也一樣，用 package 範圍可以避開。
- gremlins 對根目錄的套件（`.`）一律跑 `./...`，不論範圍是 package 還是 module，都會跑到所有套件的測試，包含 `exclude` 裡的。專案的根目錄有 Go 套件時，這個限制也適用 package 範圍。

## 開發用的檢查

```
python selftest.py go                 # Go 範例專案的全部情境，要 Go 和網路（第一次裝 gocyclo、gremlins）
python selftest.py go --only 排除     # 只跑名稱含「排除」的情境
python dev/parity_qt.py sample        # 和 quality-tools v2.4.0 對照範例專案的 CRAP 表和抓錯計數
python dev/parity_qt.py bethere       # 同上，對 BeThere 的暫存複本，約 1 小時
```
