package checkout

import "testing"

// 每個 want（正確答案）都是依照需求規格親手算出的寫死數字。
func TestCheckout(t *testing.T) {
	tests := []struct {
		name   string
		items  []Item
		level  MemberLevel
		coupon string
		want   int
	}{
		{"空購物車", nil, NonMember, "", 0},
		{"非會員_500元_加運費100", []Item{{500, 1, false}}, NonMember, "", 600},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			got := Checkout(tt.items, tt.level, tt.coupon)
			if got != tt.want {
				t.Errorf("Checkout() = %d，規格要求 %d（答錯了）", got, tt.want)
			}
		})
	}
}
