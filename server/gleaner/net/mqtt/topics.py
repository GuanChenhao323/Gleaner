"""主题名与主题过滤器（MQTT 3.1.1 §4.7）。"""

from __future__ import annotations


def valid_filter(f: str) -> bool:
    """``#`` 只能单独占据最后一层；``+`` 必须占满一层（§4.7.1）。"""
    if not f or len(f.encode()) > 65535 or "\x00" in f:
        return False
    levels = f.split("/")
    for i, lv in enumerate(levels):
        if "#" in lv and (lv != "#" or i != len(levels) - 1):
            return False
        if "+" in lv and lv != "+":
            return False
    return True


def valid_topic(t: str) -> bool:
    return bool(t) and "+" not in t and "#" not in t and "\x00" not in t


def matches(filt: str, topic: str) -> bool:
    """判断主题是否匹配过滤器。

    - ``sport/#`` 同时匹配 ``sport`` 本身（§4.7.1.2）
    - ``+`` 匹配恰好一层，可以是空层
    - 以通配符开头的过滤器不匹配 ``$`` 开头的主题（§4.7.2）
    """
    if topic.startswith("$") and filt[:1] in ("#", "+"):
        return False
    fl = filt.split("/")
    tl = topic.split("/")
    for i, f in enumerate(fl):
        if f == "#":
            return True
        if i >= len(tl):
            return False
        if f != "+" and f != tl[i]:
            return False
    return len(fl) == len(tl)


class SubscriptionTree:
    """按层级组织的订阅树，O(层数) 找到所有匹配的订阅者（同 mosquitto 的做法）。"""

    def __init__(self) -> None:
        self._root: dict[str, object] = {}

    def _node(self, filt: str, create: bool) -> dict[str, object] | None:
        node = self._root
        for lv in filt.split("/"):
            child = node.get(lv)
            if child is None:
                if not create:
                    return None
                child = {}
                node[lv] = child
            assert isinstance(child, dict)
            node = child
        return node

    def add(self, filt: str, client_id: str, qos: int) -> None:
        node = self._node(filt, True)
        assert node is not None
        subs = node.setdefault("\x00subs", {})
        assert isinstance(subs, dict)
        subs[client_id] = qos

    def remove(self, filt: str, client_id: str) -> None:
        node = self._node(filt, False)
        if node is not None:
            subs = node.get("\x00subs")
            if isinstance(subs, dict):
                subs.pop(client_id, None)

    def match(self, topic: str) -> dict[str, int]:
        """返回 {client_id: 最大授予 QoS}。同一客户端多条重叠订阅取最大 QoS（§3.3.5）。"""
        out: dict[str, int] = {}
        levels = topic.split("/")
        dollar = topic.startswith("$")

        def visit(node: dict[str, object], i: int) -> None:
            first = i == 0
            hash_node = node.get("#")
            if isinstance(hash_node, dict) and not (first and dollar):
                _collect(hash_node, out)
            if i == len(levels):
                _collect(node, out)
                return
            exact = node.get(levels[i])
            if isinstance(exact, dict):
                visit(exact, i + 1)
            plus = node.get("+")
            if isinstance(plus, dict) and not (first and dollar):
                visit(plus, i + 1)

        visit(self._root, 0)
        return out


def _collect(node: dict[str, object], out: dict[str, int]) -> None:
    subs = node.get("\x00subs")
    if isinstance(subs, dict):
        for cid, q in subs.items():
            out[cid] = max(q, out.get(cid, 0))
