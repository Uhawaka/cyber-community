"""把一局写成一篇有几幕的读物，而不是只写最后两幕。

分段时间窗的想法试过就废弃了：一幕的两半常常跨在分界线上（问在第 7 Tick、答在第 9 Tick），
按时段切会把这一幕整个切掉，结果是一幕都写不出来。连续性本来就由事件序号保证，
所以直接按顺序最多开发五幕，接成一篇。

只读已提交事实，不发明任何东西；后面的幕过不了编辑或事实核对，就退回前面的幕。
"""

from __future__ import annotations

from engine.narrative.community_prose import _compose, _develop_scenes

SCENES_PER_EPISODE = 5


def compose_episode(run, facts, *, limit=SCENES_PER_EPISODE):
    """按时间顺序开发最多 ``limit`` 幕，合成一篇。"""
    scenes = _develop_scenes(run, facts, limit=limit)
    if not scenes:
        return None
    for count in range(len(scenes), 0, -1):
        draft = _compose(run, scenes[:count])
        if draft is not None:
            return draft
    return None
