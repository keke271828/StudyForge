"""Bounded search diversity; source eligibility is checked by the callers."""


def passage_order(hit):
    return (-hit['semantic_score'], hit['reading_id'], hit['page'], hit['ordinal'])


class PassagePool:
    """Consume reading-ordered hits, keeping three distinct pages per reading.

    At most limit completed reading groups plus one current group are retained.
    Every retained group contributes its best page before extra pages are added.
    No raw vectors or complete source text are retained here.
    """
    def __init__(self, limit):
        self.limit = max(1, min(40, limit))
        self.reading_id = None
        self.pages = {}
        self.groups = []

    def add(self, hit):
        if hit['reading_id'] != self.reading_id:
            self._flush()
            self.reading_id = hit['reading_id']
        current = self.pages.get(hit['page'])
        if current is None or passage_order(hit) < passage_order(current):
            self.pages[hit['page']] = hit
        if len(self.pages) > 3:
            self.pages = {h['page']:h for h in sorted(self.pages.values(), key=passage_order)[:3]}

    def _flush(self):
        if self.pages:
            self.groups.append(sorted(self.pages.values(), key=passage_order))
            self.groups.sort(key=lambda group:passage_order(group[0]))
            del self.groups[self.limit:]
        self.pages = {}

    def result(self):
        self._flush()
        selected = [group[0] for group in self.groups]
        extra = sorted((hit for group in self.groups for hit in group[1:]), key=passage_order)
        return sorted(selected + extra[:self.limit-len(selected)], key=passage_order)


def fused_page_order(lexical, semantic):
    """Use ranks, never add unrelated lexical and cosine score scales."""
    lr = {page:index for index,(score,page) in enumerate(lexical) if score > 0}
    sr = {page:index for index,page in enumerate(semantic)}
    pages = set(lr) | set(sr)
    return sorted(pages, key=lambda page:(-(
        (.55/(12+lr[page]) if page in lr else 0) +
        (.45/(12+sr[page]) if page in sr else 0)), page))
