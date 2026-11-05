package pricing

import "testing"

// ❌ 反面教材：標準答案抄學生的作答。
//
// 這個測試的正確答案（want），是拿被測的程式自己算出來的。
// 程式算錯，答案也跟著錯，兩邊永遠一樣，所以永遠綠燈，什麼錯都抓不到。
//
// AI「先寫程式、再補測試」時，很容易寫出這種測試。
func TestFinalPrice_Mirror(t *testing.T) {
	price, qty := 1000, 4

	want := applyThresholdRebate(applyMemberDiscount(price * qty))

	if got := FinalPrice(price, qty, true); got != want {
		t.Errorf("FinalPrice = %d, want %d", got, want)
	}
}
