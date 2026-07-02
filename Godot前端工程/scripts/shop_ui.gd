extends Control
## 商城界面

@onready var title_label: Label = $Margin/VBox/ShopTitle
@onready var gold_label: Label = $Margin/VBox/GoldLabel
@onready var item_list: VBoxContainer = $Margin/VBox/ItemList
@onready var close_btn: Button = $Margin/VBox/CloseBtn
@onready var status_label: Label = $Margin/VBox/StatusLabel


func _ready() -> void:
    visible = false
    close_btn.pressed.connect(func(): visible = false)
    NetworkManager.shop_data_received.connect(_on_shop_data)
    NetworkManager.buy_result_received.connect(_on_buy_result)


func open_shop() -> void:
    visible = true
    status_label.text = ""
    NetworkManager.request_shop_data()


func _on_shop_data(data: Dictionary) -> void:
    gold_label.text = "💰 持有金币：%d" % data.get("gold", 0)

    # 显示当前持有
    var battery = data.get("battery", 0)
    var blank_cards = data.get("blank_cards", 0)
    status_label.text = "当前：🔋%d%%  📼%d张" % [battery, blank_cards]

    # 刷新商品列表
    for child in item_list.get_children():
        child.queue_free()

    var items = data.get("items", [])
    for item in items:
        var item_key := str(item.get("key", "")).strip_edges()
        var item_name := str(item.get("name", "")).strip_edges()
        # 前端隐藏“嫁祸卡”商品入口（后端逻辑不动）
        if item_key.to_lower().find("blame") >= 0 or item_name.find("嫁祸") >= 0:
            continue

        var hbox := HBoxContainer.new()
        hbox.custom_minimum_size = Vector2(0, 45)

        var info_label := Label.new()
        info_label.size_flags_horizontal = Control.SIZE_EXPAND_FILL
        info_label.text = "%s - %s（%d金币）" % [
            item.get("name", "?"),
            item.get("description", ""),
            item.get("price", 0),
        ]
        hbox.add_child(info_label)

        var buy_btn := Button.new()
        buy_btn.custom_minimum_size = Vector2(100, 0)
        var affordable: bool = item.get("affordable", false)
        if affordable:
            buy_btn.text = "购买"
            buy_btn.disabled = false
        else:
            buy_btn.text = "买不起"
            buy_btn.disabled = true
        buy_btn.pressed.connect(_on_buy.bind(item_key, buy_btn))
        hbox.add_child(buy_btn)

        item_list.add_child(hbox)


func _on_buy(item_key: String, btn: Button) -> void:
    btn.disabled = true
    btn.text = "购买中..."
    NetworkManager.buy_item(item_key)


func _on_buy_result(data: Dictionary) -> void:
    if data.get("success", false):
        status_label.text = "✅ %s（剩余%d金币）" % [
            data.get("message", "购买成功"),
            data.get("gold_remaining", 0),
        ]
    else:
        status_label.text = "❌ %s" % data.get("message", "购买失败")

    # 刷新商城
    NetworkManager.request_shop_data()
