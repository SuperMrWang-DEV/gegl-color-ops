#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""===========================================================================
 SuperMrWang · 提示词小工具 —— 中文 → SD 认得的英文
 ---------------------------------------------------------------------------
 purpose   SD1.5 / SDXL 的文本编码器只认英文（OpenCLIP 词表里没有汉字），
           中文提示词会被切成未知 token，等价于「随机重绘」。但让人写英文
           不现实——「画一只小猫」才是他脑子里的话。这里做两件事：
             1. 内置一张常用词对照表，把中文提示词按最长匹配换成英文；
             2. 换不掉的词直接报错点名，绝不把半截中文静默送给模型。
           纯标准库、纯函数，tools/check_ai_inpaint.py 直接测。

 note      为什么要「最长匹配」：中文没有空格，逐字换会把「油画」拆成
           「oil」+「画」，把「小猫」拆成「小」+「猫」。先按词长从大到小
           试，命中即走，才不会把多字词切碎。

 license   GPL-3.0-or-later，见工程根目录 LICENSE
 ==========================================================================="""

import re

# ---- 中文词表 ---------------------------------------------------------------
# 长词在前不重要，get_words() 会按长度排序；这里按语义分组只为好维护。
# 值写成 "" 的，是数量词 / 虚词 / 方位词——中文靠语序，英文也靠语序，
# 直接丢掉反而通顺（「一只小猫坐在木桌上」→ small kitten sitting wooden table）。

_ZH = {
    # 数量词 / 虚词
    "一只": "", "一个": "", "一条": "", "一张": "", "一朵": "", "一棵": "",
    "一片": "", "一杯": "", "一双": "", "一件": "", "一群": "", "一些": "",
    "的": "", "了": "", "着": "", "和": "", "与": "", "及": "", "以及": "",
    "请": "", "帮我": "", "麻烦": "", "把": "", "在": "", "有": "",
    "画": "", "绘制": "", "生成": "", "做一个": "", "做": "",
    "添加": "", "加上": "", "增加": "", "放一个": "", "放": "",
    "上": "", "下": "", "里": "", "中": "", "内": "", "外": "",
    "上面": "", "下面": "", "里面": "", "中间": "", "旁边": "next to",
    "非常": "", "很": "", "特别": "", "一点": "", "稍微": "", "更": "",
    "像": "like",
    "替换成": "replacing with", "换成": "replacing with", "变成": "becoming",

    # 动物
    "小猫": "small kitten", "猫咪": "cat", "猫": "cat",
    "小狗": "small puppy", "狗狗": "dog", "狗": "dog",
    "小鸟": "small bird", "鸟": "bird", "马": "horse", "牛": "cow",
    "羊": "sheep", "猪": "pig", "兔子": "rabbit", "仓鼠": "hamster",
    "狐狸": "fox", "鹿": "deer", "老虎": "tiger", "狮子": "lion",
    "熊": "bear", "熊猫": "panda", "大象": "elephant", "猴子": "monkey",
    "鱼": "fish", "蝴蝶": "butterfly", "蜜蜂": "bee", "蛇": "snake",
    "鲸鱼": "whale", "海豚": "dolphin", "老鹰": "eagle", "猫头鹰": "owl",
    "鸡": "chicken", "鸭": "duck", "鹅": "goose", "老鼠": "mouse",
    "松鼠": "squirrel", "狼": "wolf", "豹": "leopard", "长颈鹿": "giraffe",
    "斑马": "zebra", "企鹅": "penguin", "海豹": "seal", "螃蟹": "crab",
    "章鱼": "octopus", "乌龟": "turtle", "青蛙": "frog", "蜘蛛": "spider",
    "蚂蚁": "ant", "恐龙": "dinosaur", "独角兽": "unicorn", "龙": "dragon",

    # 人
    "人像": "portrait", "人": "person", "男人": "man", "女人": "woman",
    "男孩": "boy", "女孩": "girl", "小孩": "child", "孩子": "child",
    "婴儿": "baby", "老人": "elderly person", "模特": "model",
    "脸": "face", "手": "hand", "眼睛": "eyes", "头发": "hair",
    "微笑": "smiling", "笑": "smiling",

    # 家具 / 室内
    "木桌": "wooden table", "桌子": "table", "书桌": "desk", "椅子": "chair",
    "沙发": "sofa", "床": "bed", "窗户": "window", "门": "door",
    "墙": "wall", "地板": "floor", "天花板": "ceiling", "书架": "bookshelf",
    "书": "books", "电脑": "computer", "笔记本": "laptop", "手机": "phone",
    "相机": "camera", "地毯": "carpet", "枕头": "pillow", "台灯": "desk lamp",
    "灯": "lamp", "蜡烛": "candle", "相框": "picture frame", "镜子": "mirror",
    "杯子": "cup", "咖啡杯": "coffee cup", "咖啡": "coffee", "茶": "tea",
    "瓶子": "bottle", "酒瓶": "wine bottle", "碗": "bowl", "盘子": "plate",
    "刀": "knife", "叉子": "fork", "勺子": "spoon", "锅": "pot",
    "面包": "bread", "蛋糕": "cake", "苹果": "apple", "香蕉": "banana",
    "橙子": "orange", "草莓": "strawberry", "葡萄": "grapes",
    "西瓜": "watermelon", "食物": "food", "水果": "fruit",
    "花束": "bouquet", "鲜花": "fresh flowers", "花": "flower",
    "玫瑰": "rose", "树叶": "leaves", "树": "tree", "草": "grass",
    "草地": "lawn", "森林": "forest", "植物": "plant", "盆栽": "potted plant",

    # 户外 / 场景
    "山": "mountain", "海": "sea", "海洋": "ocean", "沙滩": "beach",
    "天空": "sky", "云": "clouds", "太阳": "sun", "月亮": "moon",
    "星星": "stars", "房子": "house", "建筑": "building", "城市": "city",
    "街道": "street", "小路": "path", "桥": "bridge", "河": "river",
    "湖": "lake", "雪": "snow", "雨": "rain", "雾": "fog",
    "汽车": "car", "卡车": "truck", "自行车": "bicycle",
    "摩托车": "motorcycle", "飞机": "airplane", "船": "boat",
    "火车": "train", "路灯": "street lamp", "广告牌": "billboard",
    "背景": "background", "前景": "foreground",
    "衣服": "clothes", "裙子": "dress", "鞋子": "shoes", "帽子": "hat",
    "包": "bag", "眼镜": "glasses", "手表": "watch", "项链": "necklace",
    "戒指": "ring", "画作": "painting", "标志": "logo",

    # 材质
    "木质": "wooden", "木纹": "wood grain", "木头": "wood", "金属": "metal",
    "玻璃": "glass", "石头": "stone", "石砖": "cobblestone",
    "混凝土": "concrete", "布料": "fabric", "棉布": "cotton",
    "皮革": "leather", "陶瓷": "ceramic", "塑料": "plastic", "纸": "paper",
    "沙子": "sand", "冰": "ice", "水": "water", "水花": "splashing water",

    # 颜色
    "红色": "red", "蓝色": "blue", "绿色": "green", "黄色": "yellow",
    "白色": "white", "黑色": "black", "灰色": "gray", "棕色": "brown",
    "粉色": "pink", "紫色": "purple", "橙色": "orange-colored",
    "金色": "golden", "银色": "silver", "透明": "transparent",
    "彩色": "colorful", "暖色": "warm colors", "冷色": "cool colors",

    # 形容词
    "大的": "large", "很小": "tiny", "小的": "small",
    "小": "small", "大": "large", "新的": "new", "旧的": "old",
    "干净的": "clean", "脏的": "dirty", "漂亮的": "beautiful",
    "可爱的": "cute", "安静的": "quiet", "明亮的": "bright",
    "昏暗的": "dim", "温暖的": "warm", "冷的": "cold",
    "柔软的": "soft", "粗糙的": "rough", "光滑的": "smooth",
    "模糊的": "blurry", "清晰的": "sharp", "简单的": "simple",
    "复杂的": "complex", "现代的": "modern", "复古的": "vintage",
    "极简的": "minimalist", "空的": "empty", "破旧的": "worn",
    "闪亮的": "shiny", "毛茸茸的": "fluffy", "毛茸茸": "fluffy",
    "光滑": "smooth", "干净": "clean", "漂亮": "beautiful",
    "可爱": "cute", "空": "empty", "破损": "damaged",

    # 动作
    "坐在": "sitting on", "坐着": "sitting", "坐": "sitting",
    "站着": "standing", "站": "standing", "躺着": "lying down",
    "躺": "lying down", "跑": "running", "走": "walking",
    "睡觉": "sleeping", "睡": "sleeping", "看起来": "looking",
    "看着镜头": "looking at the camera", "看": "looking at",
    "拿着": "holding", "吃": "eating", "喝": "drinking",
    "飞": "flying", "游泳": "swimming", "跳舞": "dancing",

    # 光照 / 摄影 / 风格
    "阳光": "sunlight", "柔光": "soft light", "自然光": "natural light",
    "灯光": "lighting", "阴影": "shadow", "虚化背景": "blurred background",
    "景深": "depth of field", "特写": "close-up", "广角": "wide angle",
    "写实": "photorealistic", "照片": "photo", "摄影": "photography",
    "35毫米": "35mm", "油画": "oil painting", "水彩": "watercolor",
    "素描": "sketch", "插画": "illustration", "动漫": "anime",
    "卡通": "cartoon", "3D渲染": "3D render", "电影感": "cinematic",
    "高质量": "high quality", "细节": "detailed", "高清": "high resolution",
    "8k": "8K", "8K": "8K",

    "去掉": "", "删除": "", "移除": "", "去除": "", "消除": "", "擦掉": "",
    "拿掉": "", "遮住": "covering", "替换": "replacing", "补充": "adding",
    "一顶": "", "一身": "", "一套": "", "一对": "", "一层": "", "一块": "",
    "戴着": "wearing", "穿着": "wearing", "戴": "wearing", "穿": "wearing",
    "超级": "", "酷": "cool", "帅气": "handsome", "美丽": "beautiful",
    "赛博朋克": "cyberpunk", "机甲": "mecha robot", "科幻": "sci-fi",
    "未来感": "futuristic", "蒸汽朋克": "steampunk", "中国风": "chinese style",
    "水墨": "ink wash painting", "古风": "ancient chinese style",
    "古城": "ancient town", "庭院": "courtyard", "花园": "garden",
    "厨房": "kitchen", "卧室": "bedroom", "客厅": "living room",
    "办公室": "office", "教室": "classroom", "咖啡馆": "cafe",
    "餐厅": "restaurant", "商店": "shop", "市场": "market",
    "公园": "park", "山顶": "mountain top", "海边": "seaside",
    "天上": "sky", "街景": "street view", "风景": "scenery",
    "有些": "some", "些": "",
    "雨滴": "raindrops", "雾气": "mist",
    "大风": "wind", "微风": "breeze", "风格": "style",
    "风": "",          # 「赛博朋克风」这类后缀，丢掉；说真风用「大风/微风」
    "室内": "indoor", "室外": "outdoor", "白天": "daytime", "夜晚": "night",
    "黄昏": "dusk", "清晨": "early morning", "春天": "spring",
    "夏天": "summer", "秋天": "autumn", "冬天": "winter",
    "幼猫": "kitten", "小动物": "small animal",
    "宠物": "pet", "动物": "animal", "植物园": "botanical garden",
    "水杯": "glass of water", "酒杯": "wine glass", "茶壶": "teapot",
    "笔记本电脑": "laptop", "键盘": "keyboard", "耳机": "headphones",
    "玩具": "toy", "气球": "balloon", "礼物": "gift", "信封": "envelope",
    "地毯花纹": "carpet pattern", "窗帘": "curtain", "床单": "bed sheet",
    "毛巾": "towel", "肥皂": "soap", "牙刷": "toothbrush",
    "汉堡": "burger", "披萨": "pizza", "面条": "noodles", "米饭": "rice",
    "寿司": "sushi", "冰淇淋": "ice cream", "巧克力": "chocolate",
    "咖啡豆": "coffee beans", "枝干": "branches",
    "岩石": "rock", "悬崖": "cliff", "瀑布": "waterfall", "溪流": "stream",

    # 负面词（negative prompt 里也会出现中文）
    "模糊": "blurry", "低质量": "low quality", "水印": "watermark",
    "文字": "text", "变形": "deformed", "畸形": "disfigured",
    "多余的肢体": "extra limbs", "签名": "signature",
    "低分辨率": "low resolution", "噪点": "noise", "过曝": "overexposed",
}

# ---- 标点 / 空白 ------------------------------------------------------------

_PUNCT = "，。、；：！？（）【】《》「」“”‘’,.;:!?()[]{}<>\"'\n\t\r"
_CJK_RE = re.compile("[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff"
                     "\uac00-\ud7af\uf900-\ufaff\uff00-\uffef]")

_WORDS = None
_MAXLEN = 1


def get_words():
    """按长度从大到小排好的 (词, 译) 列表，只算一次。"""
    global _WORDS, _MAXLEN
    if _WORDS is None:
        _WORDS = sorted(_ZH.items(), key=lambda kv: -len(kv[0]))
        _MAXLEN = max(len(k) for k in _ZH) if _ZH else 1
    return _WORDS


def has_cjk(text):
    return bool(_CJK_RE.search(text or ""))


# ---- 主体预设 ---------------------------------------------------------------
# 「菜单里能直接选一只小猫」比「自己拼一句英文」重要得多：用户点下拉、
# 点确定，出来的就是猫。preset 只是打底，用户写的提示词接在后面做细节。

PRESETS = [
    ("none", "None (write my own)", ""),
    ("cat", "A small cat", "a small cat, fluffy fur, detailed eyes"),
    ("dog", "A small dog", "a small dog, soft fur, detailed eyes"),
    ("person", "A person", "a person, natural pose, detailed face"),
    ("flower", "Flowers", "a bouquet of fresh flowers, soft petals"),
    ("tree", "A tree", "a leafy green tree, soft daylight"),
    ("coffee", "A coffee cup", "a cup of coffee on a saucer, gentle steam"),
    ("food", "A plate of food", "a plate of food, appetizing, detailed"),
    ("car", "A car", "a modern car, glossy paint, clean background"),
]

PRESET_IDS = [p[0] for p in PRESETS]


def preset_prompt(preset_id):
    for pid, _label, prompt in PRESETS:
        if pid == (preset_id or "none"):
            return prompt
    return ""


# ---- 翻译 -------------------------------------------------------------------

def to_english(text, strict=True):
    """中文提示词 → 英文。

    strict=True（正面提示词）：换不掉的词抛 ValueError 并点名——宁可让人
    改一句，也不要把半截中文静默送进模型变成随机噪声。
    strict=False（负面提示词）：换不掉的跳过，不因为一个生词废掉整段。
    返回 (英文, 未收录词列表)。
    """
    raw = (text or "").strip()
    if not raw:
        return "", []
    if not has_cjk(raw):
        return _tidy(raw), []

    words = get_words()
    out, unknown = [], []
    i, n = 0, len(raw)
    while i < n:
        ch = raw[i]
        if ch in _PUNCT:
            i += 1
            continue
        # ASCII 段（数字、英文缩写、连字符）整段保留
        if not _CJK_RE.match(ch):
            j = i
            while j < n and raw[j] not in _PUNCT and not _CJK_RE.match(raw[j]):
                j += 1
            out.append(raw[i:j])
            i = j
            continue
        # 最长匹配
        hit = None
        for zh, en in words:
            if raw.startswith(zh, i):
                hit = (zh, en)
                break
        if hit is None:
            # 连续几个没收录的字算一个词，报错时读得懂（「赛博朋克」而不是「赛 博 朋 克」）
            if unknown and unknown[-1][1] == i:
                unknown[-1] = (unknown[-1][0] + ch, i + 1)
            else:
                unknown.append((ch, i + 1))
            i += 1
            continue
        if hit[1]:
            out.append(hit[1])
        i += len(hit[0])

    if unknown and strict:
        raise ValueError(
            "这些词还没收进中文词表：%s（SD 只认英文）——换成常见说法，"
            "或直接用英文写这一段。" % "、".join(w for w, _end in unknown))
    return _tidy(" ".join(out)), [w for w, _end in unknown]


def _tidy(text):
    """收拾空格和逗号：中文换出来的英文常带多余空格 / 空逗号。"""
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"\s*,\s*(?=,)", "", text)
    text = re.sub(r",\s*,", ",", text)
    return text.strip(" ,")


def compose(prompt, preset="none"):
    """提示词 + 预设 → 最终送给模型的英文。空的就是空，交给调用方报错。"""
    body, _ = to_english(prompt)
    head = preset_prompt(preset)
    if head and body:
        return "%s, %s" % (head, body)
    return head or body


def polish_negative(text):
    """负面提示词也允许写中文，翻不出来的词跳过，不能因此中断重绘。"""
    return to_english(text, strict=False)[0]


def list_presets():
    """给 GTK 下拉 / PDB 枚举用的 (id, 英文标签) 列表。"""
    return [(pid, label) for pid, label, _p in PRESETS]
