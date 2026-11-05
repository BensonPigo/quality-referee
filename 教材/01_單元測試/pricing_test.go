package pricing

import "testing"

// 答案卷：題目和「應該算出多少」的標準答案。
//
// 每個 want（標準答案）都是人依照「規格」親手算出的寫死數字，
// 不呼叫任何實作程式碼，因此不會跟著學生作答一起錯。
func TestFinalPrice(t *testing.T) {
	tests := []struct {
		name     string
		price    int
		qty      int
		isMember bool
		want     int
	}{
		{"非會員_未達門檻_原價", 1000, 2, false, 2000},
		{"會員_打九折", 1000, 2, true, 1800},
		{"非會員_剛好3000_要折300", 1000, 3, false, 2700}, // 邊界：>= 而非 >
		{"非會員_差1元_不折", 2999, 1, false, 2999},
		{"會員_4000九折3600再折300", 1000, 4, true, 3300},
		{"會員_原價3000九折後2700_不再折", 1000, 3, true, 2700}, // 鎖住「先打折、再判斷滿額」的順序
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			got := FinalPrice(tt.price, tt.qty, tt.isMember)
			if got != tt.want {
				t.Errorf("FinalPrice(%d, %d, %v) = %d，規格要求 %d（答錯了）",
					tt.price, tt.qty, tt.isMember, got, tt.want)
			}
		})
	}
}
