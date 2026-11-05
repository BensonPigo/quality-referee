// crap 計算專案每個函式的 CRAP 分數，有函式超過門檻就以結束碼 1 結束。
//
// 計算方式：CRAP = C² × (1 − p)³ + C
//   - C：圈複雜度，由 gocyclo 計算
//   - p：函式的敘述覆蓋率，由 go test -coverprofile 計算
//
// 用法（在專案根目錄執行）：
//
//	go run ./tools/crap                      # 檢查所有函式，門檻 12
//	go run ./tools/crap -threshold 30        # 自訂門檻
//	go run ./tools/crap -base origin/main    # 只檢查和 origin/main 相比有改到的函式
//	go run ./tools/crap -baseline            # 量出現況：列出分布和改善方向，不判定成敗
package main

import (
	"bufio"
	"flag"
	"fmt"
	"go/parser"
	"go/token"
	"math"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"sort"
	"strconv"
	"strings"

	"github.com/fzipp/gocyclo"
)

type result struct {
	name       string
	file       string // 相對於專案根目錄，以 / 分隔
	line       int
	complexity int
	coverage   float64 // 0～1
	crap       float64
}

func (r result) pos() string { return posKey(r.file, r.line) }

// span 是一段改動過的行號範圍，包含頭尾。
type span struct{ from, to int }

func main() {
	threshold := flag.Float64("threshold", 12, "CRAP 門檻，超過即判定失敗")
	base := flag.String("base", "", "只檢查和這個分支或 commit 相比有改到的函式，例如 origin/main")
	baseline := flag.Bool("baseline", false, "量出現況：列出分布和改善方向，結束碼固定為 0")
	flag.Parse()

	if *base != "" && *baseline {
		fmt.Fprintln(os.Stderr, "-base 和 -baseline 不能同時使用")
		os.Exit(2)
	}

	coverage, err := measureCoverage()
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(2)
	}
	results := analyze(coverage)

	if *baseline {
		printTable(results, *threshold, true)
		printBaseline(results, *threshold)
		return
	}

	debt := 0
	if *base != "" {
		changed, err := changedLines(*base)
		if err != nil {
			fmt.Fprintln(os.Stderr, err)
			os.Exit(2)
		}
		var touched []result
		for _, r := range results {
			if isChanged(r, changed) {
				touched = append(touched, r)
			} else if r.crap > *threshold {
				debt++
			}
		}
		results = touched
		fmt.Printf("只檢查和 %s 相比有改到的函式（共 %d 個）\n\n", *base, len(results))
	}

	failed := printTable(results, *threshold, *base != "")

	fmt.Println()
	if debt > 0 {
		fmt.Printf("另有 %d 個沒改到的函式超過門檻，列為技術債，不計入這次判定。\n", debt)
	}
	if failed > 0 {
		fmt.Printf("FAIL：%d 個函式的 CRAP 超過門檻 %.0f\n", failed, *threshold)
		os.Exit(1)
	}
	if *base != "" && len(results) == 0 {
		fmt.Println("PASS：這次沒有改到任何函式")
		return
	}
	fmt.Printf("PASS：所有函式的 CRAP 都在門檻 %.0f 以內\n", *threshold)
}

// analyze 用 gocyclo 算每個函式的圈複雜度，配上覆蓋率算出 CRAP，由高到低排序。
func analyze(coverage map[string]float64) []result {
	// 只分析正式程式碼：排除測試檔、tools、vendor、testdata 目錄。
	ignore := regexp.MustCompile(`_test\.go$|^tools[/\\]|(^|[/\\])(vendor|testdata)[/\\]`)
	stats := gocyclo.Analyze([]string{"."}, ignore)

	var results []result
	for _, s := range stats {
		file := filepath.ToSlash(filepath.Clean(s.Pos.Filename))
		p := coverage[posKey(file, s.Pos.Line)]
		c := float64(s.Complexity)
		results = append(results, result{
			name:       s.FuncName,
			file:       file,
			line:       s.Pos.Line,
			complexity: s.Complexity,
			coverage:   p,
			crap:       c*c*math.Pow(1-p, 3) + c,
		})
	}
	sort.Slice(results, func(i, j int) bool { return results[i].crap > results[j].crap })
	return results
}

// printTable 印出 CRAP 表格，回傳超過門檻的函式數量。advice 為 true 時，超標的函式後面附上改善方向。
func printTable(results []result, threshold float64, advice bool) int {
	fmt.Printf("%-8s %-6s %-8s %-24s %s\n", "CRAP", "C", "Cover", "Func", "Pos")
	failed := 0
	for _, r := range results {
		mark := "  "
		if r.crap > threshold {
			mark = "❌"
			failed++
			if advice {
				mark += " " + adviceFor(r, threshold)
			}
		}
		fmt.Printf("%-8.1f %-6d %-8s %-24s %s %s\n",
			r.crap, r.complexity, fmt.Sprintf("%.1f%%", r.coverage*100), r.name, r.pos(), mark)
	}
	return failed
}

// adviceFor 判斷超標的函式要補測試還是拆函式。CRAP 最低就是 C，所以 C 超過門檻時補測試沒有用。
func adviceFor(r result, threshold float64) string {
	c := float64(r.complexity)
	if c > threshold {
		return "要拆函式"
	}
	// 解 C² × (1 − p)³ + C ≤ 門檻，得到 p ≥ 1 − ∛((門檻 − C) / C²)
	need := 1 - math.Cbrt((threshold-c)/(c*c))
	return fmt.Sprintf("覆蓋率要到 %.0f%%", math.Ceil(need*100))
}

func printBaseline(results []result, threshold float64) {
	var pass, needTests, needSplit int
	for _, r := range results {
		switch {
		case r.crap <= threshold:
			pass++
		case float64(r.complexity) > threshold:
			needSplit++
		default:
			needTests++
		}
	}

	fmt.Println()
	fmt.Printf("現況（門檻 %.0f）\n", threshold)
	fmt.Printf("  函式總數：%d\n", len(results))
	fmt.Printf("  通過：%d\n", pass)
	fmt.Printf("  超標：%d\n", needTests+needSplit)
	fmt.Printf("    補測試就能過：%d\n", needTests)
	fmt.Printf("    要拆函式：%d（圈複雜度超過門檻，覆蓋率 100%% 也過不了）\n", needSplit)
	if len(results) > 0 {
		worst := results[0]
		fmt.Printf("  最高分：%.1f（%s，%s）\n", worst.crap, worst.name, worst.pos())
	}
}

// measureCoverage 執行測試並回傳每個函式的覆蓋率，key 為「檔案相對路徑:行號」。
func measureCoverage() (map[string]float64, error) {
	module, err := exec.Command("go", "list", "-m").Output()
	if err != nil {
		return nil, fmt.Errorf("讀不到模組名稱，請在 go.mod 所在的目錄執行：%w", err)
	}
	modPath := strings.TrimSpace(string(module))

	pkgs, err := testPackages(modPath)
	if err != nil {
		return nil, err
	}

	dir, err := os.MkdirTemp("", "crap")
	if err != nil {
		return nil, err
	}
	defer os.RemoveAll(dir)
	profile := filepath.Join(dir, "cover.out")

	test := exec.Command("go", append([]string{"test", "-coverprofile=" + profile}, pkgs...)...)
	test.Stdout, test.Stderr = os.Stdout, os.Stderr
	if err := test.Run(); err != nil {
		return nil, fmt.Errorf("測試沒有全部通過，請先修好第一重約束（單元測試）再量 CRAP：%w", err)
	}

	out, err := exec.Command("go", "tool", "cover", "-func="+profile).Output()
	if err != nil {
		return nil, fmt.Errorf("go tool cover 執行失敗：%w", err)
	}

	// 每行格式：crap/checkout.go:30:	Checkout	85.7%
	// 檔名開頭是模組名稱，去掉之後就是相對於專案根目錄的路徑。
	coverage := map[string]float64{}
	sc := bufio.NewScanner(strings.NewReader(string(out)))
	for sc.Scan() {
		fields := strings.Fields(sc.Text())
		if len(fields) != 3 || fields[0] == "total:" {
			continue
		}
		loc := strings.Split(strings.TrimSuffix(fields[0], ":"), ":")
		if len(loc) < 2 {
			continue
		}
		line, err := strconv.Atoi(loc[len(loc)-1])
		if err != nil {
			continue
		}
		file := strings.TrimPrefix(strings.Join(loc[:len(loc)-1], ":"), modPath+"/")
		pct, err := strconv.ParseFloat(strings.TrimSuffix(fields[2], "%"), 64)
		if err != nil {
			continue
		}
		coverage[posKey(file, line)] = pct / 100
	}
	return coverage, sc.Err()
}

// testPackages 列出要跑測試的套件，排除 tools 底下的量測工具。
func testPackages(modPath string) ([]string, error) {
	out, err := exec.Command("go", "list", "./...").Output()
	if err != nil {
		return nil, fmt.Errorf("go list 執行失敗：%w", err)
	}
	var pkgs []string
	for _, p := range strings.Fields(string(out)) {
		if p == modPath+"/tools" || strings.HasPrefix(p, modPath+"/tools/") {
			continue
		}
		pkgs = append(pkgs, p)
	}
	return pkgs, nil
}

// changedLines 回傳和 base 相比改動過的行號，key 為檔案相對路徑。
// 比較的起點是 base 和 HEAD 的分岔點，所以 base 之後別人合併進去的改動不會算進來；
// 比較的終點是工作目錄，所以還沒 commit 的改動和新增的檔案也會算進來。
func changedLines(base string) (map[string][]span, error) {
	mergeBase, err := git("merge-base", base, "HEAD")
	if err != nil {
		return nil, fmt.Errorf("找不到 %s 和 HEAD 的分岔點（CI 上要把 git 歷史完整抓下來）：%w", base, err)
	}
	diff, err := git("diff", "-U0", "--no-color", "--relative", "--ignore-cr-at-eol", strings.TrimSpace(mergeBase), "--", "*.go")
	if err != nil {
		return nil, err
	}

	// 只需要新版本的行號：@@ -舊起點,舊行數 +新起點,新行數 @@
	hunk := regexp.MustCompile(`^@@ -\S+ \+(\d+)(?:,(\d+))? @@`)
	changed := map[string][]span{}
	file := ""
	for _, line := range strings.Split(diff, "\n") {
		line = strings.TrimRight(line, "\r")
		switch {
		case strings.HasPrefix(line, "+++ "):
			file = strings.TrimPrefix(line, "+++ b/")
			if line == "+++ /dev/null" { // 整個檔案被刪除
				file = ""
			}
		case file != "" && strings.HasPrefix(line, "@@"):
			m := hunk.FindStringSubmatch(line)
			if m == nil {
				continue
			}
			start, _ := strconv.Atoi(m[1])
			n := 1
			if m[2] != "" {
				n, _ = strconv.Atoi(m[2])
			}
			if n == 0 { // 只刪除沒新增：刪除位置在 start 和 start+1 之間
				changed[file] = append(changed[file], span{start, start + 1})
			} else {
				changed[file] = append(changed[file], span{start, start + n - 1})
			}
		}
	}

	untracked, err := git("ls-files", "--others", "--exclude-standard", "--", "*.go")
	if err != nil {
		return nil, err
	}
	for _, f := range strings.Fields(untracked) {
		changed[f] = append(changed[f], span{1, math.MaxInt})
	}
	return changed, nil
}

// isChanged 判斷函式從 func 那一行到結尾的 } 之間，有沒有任何一行被改動。
func isChanged(r result, changed map[string][]span) bool {
	spans := changed[r.file]
	if len(spans) == 0 {
		return false
	}
	end := funcEnd(r.file, r.line)
	for _, s := range spans {
		if s.from <= end && s.to >= r.line {
			return true
		}
	}
	return false
}

var funcEnds = map[string]map[int]int{}

// funcEnd 回傳從第 line 行開始的函式，結尾在第幾行。
func funcEnd(file string, line int) int {
	ends, ok := funcEnds[file]
	if !ok {
		ends = map[int]int{}
		fset := token.NewFileSet()
		if f, err := parser.ParseFile(fset, file, nil, 0); err == nil {
			for _, d := range f.Decls {
				ends[fset.Position(d.Pos()).Line] = fset.Position(d.End()).Line
			}
		}
		funcEnds[file] = ends
	}
	if end, ok := ends[line]; ok {
		return end
	}
	return line
}

func git(args ...string) (string, error) {
	cmd := exec.Command("git", append([]string{"-c", "core.quotepath=false"}, args...)...)
	cmd.Stderr = os.Stderr
	out, err := cmd.Output()
	return string(out), err
}

// posKey 以「檔案相對路徑:行號」對應 gocyclo 與 go tool cover 的函式位置。
func posKey(file string, line int) string {
	return fmt.Sprintf("%s:%d", file, line)
}
