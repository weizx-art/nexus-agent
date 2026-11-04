import re
from typing import Callable

from langchain_text_splitters import RecursiveCharacterTextSplitter, TextSplitter

from models import ProcessRule


class ProcessRuleService:

    @classmethod
    def get_text_splitter_by_process_rule(
        cls, process_rule: ProcessRule, length_function: Callable
    ) -> TextSplitter:
        rule = process_rule.rule if isinstance(process_rule.rule, dict) else {}
        segment = rule.get("segment", {})
        return RecursiveCharacterTextSplitter(
            chunk_size=segment.get("chunk_size", 500),
            chunk_overlap=segment.get("chunk_overlap", 50),
            separators=segment.get("separators", ["\n\n", "\n", "。", "！", "？", "；", ".", "!", "?", ",", "，", " ", ""]),
            is_separator_regex=True,
            length_function=length_function,
        )

    @classmethod
    def clean_text_by_process_rule(cls, text: str, process_rule: ProcessRule) -> str:
        rule = process_rule.rule if isinstance(process_rule.rule, dict) else {}
        for pre_rule in rule.get("pre_process_rules", []):
            if pre_rule["id"] == "remove_extra_space" and pre_rule.get("enabled"):
                text = re.sub(r"\n{3,}", "\n\n", text)
                text = re.sub(
                    r"[\t\f\r\x20\u00a0\u1680\u180e\u2000-\u200a\u202f\u205f\u3000]{2,}",
                    " ",
                    text,
                )
            if pre_rule["id"] == "remove_url_and_email" and pre_rule.get("enabled"):
                text = re.sub(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+", "", text)
                text = re.sub(r"https?://[^\s]+", "", text)
        return text
