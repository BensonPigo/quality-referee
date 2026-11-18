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
- switch 的 case 條件（`case a > b:` 冒號前面那段，包括有 tag 的 switch 的 case 值、分成好幾行的 case 清單），Go 的覆蓋率不記錄那個位置，gremlins 因此把上面的改壞版本一律判成「測試沒跑到」、不跑測試。`mutants` 會挑出這些改壞的版本：位置不在任何覆蓋率區塊裡、所屬的 switch 敘述有被執行，就自己用 `go test -overlay` 換進改壞的檔案，一個一個補跑測試，跑法和結果的判定都照 gremlins（時限不會比 gremlins 短），只有改壞後編譯不過或被 go vet 擋下（例如跟別的 case 常數重複）算「無效」不算抓到。有「測試沒跑到」的改壞版本時，會多跑一次 `go test` 量覆蓋率。
- 記分表的 `tools` 寫兩個工具的版本，`settings` 寫實際生效的設定（`functions` 只有 `coverage_scope`，`mutants` 有 `coverage_scope` 和 `workers`），會進 JSON 報告。

範本的 `crap.inspector` 沒有帶 `--coverage-scope`，用 package 範圍。專案的測試分散在別的套件時，兩個 inspector 都加 `"--coverage-scope", "module"`。不加的話，只被別的套件的測試跑到的函式，改壞的版本都是「測試沒跑到」，會被判成沒有測試。

## 限制

- module 範圍的抓錯檢查會跑到被排除套件的測試。gremlins v0.6.0 的 `--integration` 一律從模組根目錄跑 `go test ./...`，`exclude` 裡的套件測試照樣會跑。排除的套件只要有一個測試失敗，檢查就以結束碼 2 停下（gremlins 執行失敗）。用 package 範圍可以避開。
- 根目錄有 Go 套件時，gremlins 對根目錄的套件（`.`）一律跑 `./...`，不論範圍是 package 還是 module，都會跑到所有套件的測試，包含 `exclude` 裡的。同理，非根目錄的套件底下有被排除的子套件時，子套件的測試也會被跑到。
- 補跑 switch case 條件時，「switch 有被執行」是看包住 switch 那一行的覆蓋率區塊有沒有跑到，所以兩種情況會被算成「沒抓到」而不是「測試沒跑到」：前面的 case 每次都成立，後面的 case 條件從沒被算到；同一個區塊裡、switch 前面的敘述 panic 或結束程式，switch 其實沒執行（gremlins 對一般敘述也是這樣算）。
- 找 case 條件所屬的 switch，依賴 gofmt 的排版（case 跟 switch 同一層縮排，多行的 case 清單前一行以逗號結尾）。找不到時不補跑，維持「測試沒跑到」。
- GOFLAGS 裡有 `-overlay` 時，只要有需要補跑的 case 條件，檢查就以結束碼 1 停下：補跑用的 `-overlay` 會蓋掉 GOFLAGS 裡的。
- 找函式結尾的方式是找單獨一行的 `}`，函式裡的原始字串剛好有這樣一行時，範圍會提早結束，後面的改壞版本就不算在這個函式裡。
