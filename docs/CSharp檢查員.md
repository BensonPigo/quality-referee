# C# 檢查員

`inspectors/csharp.py`，給 SDK 風格、.NET 6 以上的專案（舊式 .NET Framework 的 csproj 不支援），在專案根目錄由裁判啟動：

```
python tools/referee/inspectors/csharp.py functions [--target 方案或專案檔]
python tools/referee/inspectors/csharp.py mutants   [--target 方案或專案檔] [--workers N]
```

- `functions`：複雜度用內附的 Roslyn 工具依原始碼計算，規則和 gocyclo 一樣：1 加上 if、非 default 的 case、不是 `_` 的 switch 分支、for、foreach、while、do、catch、`&&`、`||`、`?:`、`??` 的個數。lambda 和區域函式算進所在的成員。列出的成員有方法、建構式、運算子、屬性和事件的存取子（含 `=>` 寫法）。覆蓋率用 `dotnet test --collect:"XPlat Code Coverage"`（coverlet），依行對應到每個函式；沒有任何測試跑過的檔案是 0。
- `mutants`：Stryker.NET 5.0.0。有改到的檔案時（`mutation --base`）只改壞那些檔案。測試一開始就失敗時，以結束碼 2 停下。
- `--target`：要測試的 `.sln`、`.slnx` 或 `.csproj`。沒給時用專案根目錄唯一的 `.sln` 或 `.slnx`，沒有或不只一個就以結束碼 2 停下。`mutants` 給 `.csproj` 時要是測試專案。
- `--workers N`：Stryker.NET 同時跑幾個（`--concurrency`），沒給就用 Stryker 的預設值。只對 `mutants` 有用。
- 專案的需求：PATH 上有 .NET SDK 6 以上；測試專案引用 `coverlet.collector`（`dotnet new xunit`、`mstest`、`nunit` 的範本預設就有），而且 `dotnet test` 走 VSTest。
- 複雜度工具第一次執行時從原始碼建置、Stryker.NET 第一次執行時用 `dotnet tool install` 裝，都放在 `REFEREE_TOOLS_DIR`（預設 `~/.cache/quality-referee`），要網路，之後直接執行。建置和安裝都在快取目錄裡進行，並且放了隔離用的設定檔，專案的 `Directory.Build.*`、中央套件管理、`global.json`、`NuGet.config` 都不會影響工具，也不會在 `tools/referee/` 底下留下 `bin/`、`obj/`。
- `bin/`、`obj/`（任何一層）和產生的檔案（`*.g.cs`、`*.Designer.cs`）檢查員自己跳過，不用寫進 `exclude`。範本的 `tests` 比對 `*.Tests/`、`*.Test/`、`*.UnitTests/` 目錄，測試專案的命名不一樣時要改。
- 記分表的 `tools` 寫 Roslyn 或 Stryker.NET 的版本，以及執行測試的 SDK 版本；`settings` 寫實際生效的 `target`（`mutants` 另有 `workers`）。

## 限制

- 沒有被任何測試專案引用的專案，Stryker.NET 不會改壞它，第三關沒有東西可判定；第二關的覆蓋率是 0，會擋下。
- 同一個位置的同一種改法（例如 `<=` 改成 `<` 和改成 `>`，都叫 `Equality mutation`），Stryker.NET 回報的欄位一樣，排除清單沒辦法只排除其中一個。
- Windows 上，Stryker.NET 的檔案路徑到 260 字元就讀不到自己的版本而當掉。檢查員安裝後會先檢查，路徑太長時請把 `REFEREE_TOOLS_DIR` 設到短一點的路徑（例如 `C:\referee-tools`）。預設的 `~/.cache/quality-referee` 不會碰到。
- 用 deterministic build、SourceLink（例如 `ContinuousIntegrationBuild=true`）時，coverlet 報告裡的檔案路徑可能對不回原始碼，覆蓋率會變成 0。還沒驗證過。
- 只有頂層陳述式（top-level statements）的 `Program.cs` 不會列成函式。
- 同一個位置有一個改壞版本編譯不過時，Stryker.NET 可能把那個位置其他編得過的改壞版本也一起標成無效（`NOT_VIABLE`），那些行在第三關就沒有被判定。例如 `cart.Lines.Count == 0`：「`Count` 改成 `Sum`」編不過（`Count` 是屬性），同一欄的「`==` 改成 `!=`」也跟著被標成無效。無效的版本不算進抓錯率和測到率，文字報告也不會顯示，要看 JSON 報告的 `mutation.mutants` 裡 `status` 是 `NOT_VIABLE` 的項目（計數在 `mutation.counts.NOT_VIABLE`）。
