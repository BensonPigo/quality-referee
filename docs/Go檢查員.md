# Go 檢查員

`inspectors/go.py`，在 go.mod 所在的專案根目錄由裁判啟動：

```
python tools/referee/inspectors/go.py functions|mutants [--coverage-scope package|module] [--workers N]
```

- `--coverage-scope package|module`（預設 package）：module 時，別的套件的測試跑到的程式也算覆蓋率；抓錯檢查改用 gremlins 的 `--integration --coverpkg`，每個改壞的版本跑整個模組的測試。
- `--workers N`：gremlins 同時跑幾個，沒給就用 gremlins 的預設值。只對 `mutants` 有用，`functions` 不跑 gremlins。
- gocyclo、gremlins（都是 v0.6.0）第一次執行時用 `go install` 裝到 `REFEREE_TOOLS_DIR`（預設 `~/.cache/quality-referee`），之後直接執行，斷網也能量。
- 要跳過的目錄寫在 `.referee.json` 的 `exclude`，檢查員從 context 讀，不用在 `inspector` 指令再寫一次。
- 因為 build constraint 在這個平台不編譯的檔案（例如 Linux 上的 `*_windows.go`），`mutants` 不產生改壞的版本。gremlins 本來會產生，但測試一定跑不到，補測試也沒有用。
- 記分表的 `tools` 寫兩個工具的版本，`settings` 寫實際生效的設定（`functions` 只有 `coverage_scope`，`mutants` 有 `coverage_scope` 和 `workers`），會進 JSON 報告。

範本的 `crap.inspector` 沒有帶 `--coverage-scope`，用 package 範圍。專案的測試分散在別的套件時，兩個 inspector 都加 `"--coverage-scope", "module"`。不加的話，只被別的套件的測試跑到的函式，改壞的版本都是「測試沒跑到」，會被判成沒有測試。

## 限制

- module 範圍的抓錯檢查會跑到被排除套件的測試。gremlins v0.6.0 的 `--integration` 一律從模組根目錄跑 `go test ./...`，`exclude` 裡的套件測試照樣會跑。排除的套件只要有一個測試失敗，檢查就以結束碼 2 停下（gremlins 執行失敗）。quality-tools v2.4.0 也一樣，用 package 範圍可以避開。
- 根目錄有 Go 套件時，gremlins 對根目錄的套件（`.`）一律跑 `./...`，不論範圍是 package 還是 module，都會跑到所有套件的測試，包含 `exclude` 裡的。同理，非根目錄的套件底下有被排除的子套件時，子套件的測試也會被跑到。
- 找函式結尾的方式是找單獨一行的 `}`，函式裡的原始字串剛好有這樣一行時，範圍會提早結束，後面的改壞版本就不算在這個函式裡。
