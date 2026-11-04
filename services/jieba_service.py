import warnings

import jieba

with warnings.catch_warnings():
    warnings.simplefilter("ignore", ResourceWarning)
    from jieba.analyse import default_tfidf

STOPWORD_SET = {
    # 英文停用词
    "a", "an", "the", "and", "or", "but", "in", "on", "at", "to", "for",
    "of", "with", "by", "from", "is", "are", "was", "were", "be", "been",
    "being", "have", "has", "had", "do", "does", "did", "will", "would",
    "could", "should", "may", "might", "shall", "can", "need", "must",
    "it", "its", "i", "me", "my", "we", "our", "you", "your", "he", "him",
    "his", "she", "her", "they", "them", "their", "this", "that", "these",
    "those", "not", "no", "nor", "so", "if", "then", "than", "too", "very",
    "just", "about", "above", "after", "again", "all", "also", "am", "any",
    "as", "back", "because", "before", "between", "both", "down", "during",
    "each", "few", "further", "get", "got", "here", "how", "into", "more",
    "most", "myself", "now", "once", "only", "other", "out", "over", "own",
    "same", "some", "such", "there", "through", "under", "until", "up",
    "what", "when", "where", "which", "while", "who", "whom", "why",
    "yet", "yourself", "yourselves",
    # 中文停用词
    "的", "了", "在", "是", "我", "有", "和", "就", "不", "人", "都", "一",
    "一个", "上", "也", "很", "到", "说", "要", "去", "你", "会", "着",
    "没有", "看", "好", "自己", "这", "他", "她", "它", "们", "那", "些",
    "什么", "吗", "呢", "吧", "啊", "呀", "哦", "嗯", "哈", "嘛", "么",
    "而", "及", "其", "或", "如", "但", "被", "把", "给", "让", "向",
    "对", "从", "以", "用", "于", "与", "并", "等", "里", "中", "后",
    "前", "下", "内", "外", "间", "过", "还", "可以", "因为", "所以",
    "如果", "虽然", "但是", "而且", "不过", "然后", "因此", "于是",
    "即", "且", "之", "者", "所", "为", "来", "比", "每",
    "当", "该", "本", "此", "另", "别", "各", "个", "位",
    "种", "项", "条", "件", "次", "回", "则", "面", "方", "部", "分",
    "点", "起", "以下", "以上", "以后", "以前", "以来",
    # 标点符号和数字
    "~", "!", ".", ":", '"', "'", "(", ")", "*", "--", "..", ">>",
    "<", ">", "/", "\\", "|", "-", "_", "+", "=", "&", "^", "%", "#",
    "@", "`", ";", "$", "（", "）", "——", "—", "￥", "·", "...",
    "‘", "’", "〉", "〈", "…", " ", "\n",
    "0", "1", "2", "3", "4", "5", "6", "7", "8", "9",
}

default_tfidf.stop_words = STOPWORD_SET


class JiebaService:
    """结巴分词服务"""

    @staticmethod
    def extract_keywords(text: str, top_k: int = 10) -> list[str]:
        return jieba.analyse.extract_tags(sentence=text, topK=top_k)
