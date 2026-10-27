import asyncio
import json

from studyforge.review import CHECKS, review_explanation


def test_three_independent_reviews_run_together_and_revision_is_rechecked():
    class Reviewer:
        def __init__(self):
            self.active = 0
            self.max_active = 0
            self.attempts = {title: 0 for title, _ in CHECKS}
            self.revisions = 0

        async def complete(self, system, user, json_mode=False):
            if "独立审查员" not in system:
                self.revisions += 1
                return "修订后的完整讲解"
            self.active += 1
            self.max_active = max(self.max_active, self.active)
            await asyncio.sleep(.02)
            self.active -= 1
            title = next(title for title, _ in CHECKS if title in user)
            self.attempts[title] += 1
            if title == "成品审查" and self.attempts[title] == 1:
                return json.dumps({"passed": False, "issues": [{"location": "段落 2", "problem": "引用不准确"}]})
            return json.dumps({"passed": True, "issues": []})

    client = Reviewer()
    progress = []
    document, reports = asyncio.run(review_explanation(client, "原资料", "初稿", lambda name, value: progress.append((name, value))))
    assert client.max_active == 3
    assert client.revisions == 1
    assert all(count == 2 for count in client.attempts.values())
    assert len(reports) == 6
    assert document == "修订后的完整讲解"
    assert progress[-1] == ("三项审查完成", 1)
